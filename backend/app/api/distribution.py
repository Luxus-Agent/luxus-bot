"""
Standalone consolidated endpoint for the TokenPocket / MultiSender integration.

Per the client's "Decentralized Deposit & Distribution System" spec (Section 6),
the backend exposes ONE consolidated endpoint that tells the frontend / blockchain
team *where the money should go*: for a given user it returns that user's own
wallet address + profit, plus the list of downline users under them, each with
their wallet address and profit. Amounts are computed live from the ledger, so
they reflect distribution updates in real time with no admin-approval step.

This module only *reads* — it never moves funds. The actual on-chain payout is
performed by the frontend MultiSender contract using the figures returned here.
"""
import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.models.wallet import Wallet, WalletType
from app.models.wallet_address import WalletAddress

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/distribution", tags=["distribution"])

# Transaction types that represent profit *earned* by a user from the revenue
# engine (mirrors wallet.INCOME_TYPES). Deposits/transfers are NOT profit.
INCOME_TYPES = [
    TransactionType.CORE_INCOME,
    TransactionType.STREAM_PAYOUT,
    TransactionType.BOOST_PAYOUT,
    TransactionType.SPONSOR_MILESTONE_INCOME,
]

# Cap how many downline rows a single response can carry, to bound payload size.
MAX_LIMIT = 500


def _two_places(value: Decimal) -> float:
    """Render a Decimal as a JSON-friendly float rounded to cents."""
    return float(value.quantize(Decimal("0.0001")))


def _collect_downline_ids(db: Session, root_id: int, direct_only: bool) -> list[tuple[int, int]]:
    """
    Return [(user_id, level), ...] for the sponsor subtree under root_id,
    ordered breadth-first (level 1 = direct referrals). When direct_only is
    True, only level-1 (direct) referrals are returned.
    """
    result: list[tuple[int, int]] = []
    frontier = [root_id]
    level = 0
    seen = {root_id}
    while frontier:
        level += 1
        children = (
            db.query(User.id)
            .filter(User.sponsor_id.in_(frontier))
            .order_by(User.id.asc())
            .all()
        )
        next_frontier = []
        for (uid,) in children:
            if uid in seen:  # guard against any accidental cycle
                continue
            seen.add(uid)
            result.append((uid, level))
            next_frontier.append(uid)
        if direct_only:
            break
        frontier = next_frontier
    return result


def _wallet_totals(db: Session, user_ids: list[int]) -> dict[int, dict[str, Decimal]]:
    """
    Batch-sum wallet balances per user, grouped by wallet type.
    Returns {user_id: {"main": Decimal, "repurchase": Decimal, "account": Decimal}}.
    """
    totals: dict[int, dict[str, Decimal]] = {
        uid: {"main": Decimal("0"), "repurchase": Decimal("0"), "account": Decimal("0")}
        for uid in user_ids
    }
    if not user_ids:
        return totals
    rows = (
        db.query(Wallet.user_id, Wallet.wallet_type, func.coalesce(func.sum(Wallet.balance), 0))
        .filter(Wallet.user_id.in_(user_ids))
        .group_by(Wallet.user_id, Wallet.wallet_type)
        .all()
    )
    key_for = {
        WalletType.MAIN: "main",
        WalletType.REPURCHASE: "repurchase",
        WalletType.ACCOUNT: "account",
    }
    for uid, wtype, total in rows:
        key = key_for.get(wtype)
        if key is not None:
            totals[uid][key] = Decimal(str(total))
    return totals


def _earned_totals(db: Session, user_ids: list[int]) -> dict[int, Decimal]:
    """Batch-sum lifetime income (profit earned) per user."""
    totals = {uid: Decimal("0") for uid in user_ids}
    if not user_ids:
        return totals
    rows = (
        db.query(Transaction.user_id, func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.user_id.in_(user_ids),
            Transaction.transaction_type.in_(INCOME_TYPES),
        )
        .group_by(Transaction.user_id)
        .all()
    )
    for uid, total in rows:
        totals[uid] = Decimal(str(total))
    return totals


def _verified_addresses(db: Session, user_ids: list[int]) -> dict[int, str]:
    """
    Fallback wallet address: the user's most recently registered *verified*
    BEP-20 address. Used when User.wallet_address (set at registration) is empty.
    """
    addrs: dict[int, str] = {}
    if not user_ids:
        return addrs
    rows = (
        db.query(WalletAddress.user_id, WalletAddress.address)
        .filter(WalletAddress.user_id.in_(user_ids), WalletAddress.is_verified.is_(True))
        .order_by(WalletAddress.user_id.asc(), WalletAddress.created_at.desc())
        .all()
    )
    for uid, address in rows:
        addrs.setdefault(uid, address)  # first row per user = most recent (desc order)
    return addrs


def _profit_block(wallet: dict[str, Decimal], earned: Decimal) -> dict:
    """Shape the per-user profit figures the frontend distributes against."""
    main = wallet["main"]
    account = wallet["account"]
    return {
        "total_earned": _two_places(earned),          # lifetime revenue-engine income
        "main_balance": _two_places(main),            # withdrawable earnings
        "repurchase_balance": _two_places(wallet["repurchase"]),
        "account_balance": _two_places(account),      # deposits/transfers (not profit)
        "withdrawable": _two_places(main + account),  # what a payout can currently send
    }


def _user_entry(
    user: User,
    level: int | None,
    wallet: dict[str, Decimal],
    earned: Decimal,
    fallback_address: str | None,
) -> dict:
    address = user.wallet_address or fallback_address
    return {
        "user_id": user.id,
        "username": user.username,
        "level": level,  # None for the root user; 1 = direct referral, 2 = their referral, …
        "wallet_address": address,
        "wallet_address_source": (
            "registration" if user.wallet_address else ("verified" if fallback_address else None)
        ),
        "has_wallet_address": address is not None,
        "is_active": user.is_active,
        "profit": _profit_block(wallet, earned),
    }


@router.get("/wallet-map")
def wallet_map(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    username: str | None = Query(
        None,
        description="Admin-only: build the map for another user by username. "
        "Regular users always get their own map.",
    ),
    direct_only: bool = Query(
        False,
        description="When true, only direct (level-1) referrals are returned; "
        "otherwise the full sponsor subtree is included.",
    ),
    limit: int = Query(MAX_LIMIT, ge=1, le=MAX_LIMIT, description="Max downline rows to return."),
    offset: int = Query(0, ge=0, description="Downline rows to skip (pagination)."),
):
    """
    Consolidated distribution map for the TokenPocket / MultiSender integration.

    Returns, for the resolved user (the caller by default):
      • their own wallet address + profit figures, and
      • the list of downline users under them, each with wallet address + profit,
    so the frontend MultiSender knows exactly where each credited amount goes.

    Amounts are read live from the ledger — no admin approval step. JSON (not a
    bare list) is used so the root user, the paginated downline, and metadata can
    travel together in one response.
    """
    # Resolve the root user. Only admins may inspect someone else.
    root = current_user
    if username and username != current_user.username:
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Only admins may query another user's map.")
        root = db.query(User).filter_by(username=username).first()
        if not root:
            raise HTTPException(status_code=404, detail="User not found.")

    downline = _collect_downline_ids(db, root.id, direct_only)
    total_downline = len(downline)
    page = downline[offset : offset + limit]

    # Gather every user id we need data for (root + this page of downline) and
    # batch-load wallets / earnings / fallback addresses to avoid N+1 queries.
    page_ids = [uid for uid, _ in page]
    all_ids = [root.id] + page_ids
    wallets = _wallet_totals(db, all_ids)
    earned = _earned_totals(db, all_ids)
    fallback_addr = _verified_addresses(db, all_ids)

    users_by_id = {
        u.id: u for u in db.query(User).filter(User.id.in_(all_ids)).all()
    }

    root_entry = _user_entry(
        users_by_id[root.id], None, wallets[root.id], earned[root.id], fallback_addr.get(root.id)
    )

    downline_entries = []
    for uid, level in page:
        u = users_by_id.get(uid)
        if u is None:
            continue
        downline_entries.append(
            _user_entry(u, level, wallets[uid], earned[uid], fallback_addr.get(uid))
        )

    logger.info(
        "DISTRIBUTION wallet-map: requester=%s root=%s downline_total=%d returned=%d direct_only=%s",
        current_user.username, root.username, total_downline, len(downline_entries), direct_only,
    )

    return {
        "user": root_entry,
        "downline": {
            "total": total_downline,
            "count": len(downline_entries),
            "limit": limit,
            "offset": offset,
            "direct_only": direct_only,
            "users": downline_entries,
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
