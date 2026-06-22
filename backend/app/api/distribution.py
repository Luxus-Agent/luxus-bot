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
import json
import logging
import re
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_platform_active
from app.config import settings
from app.database import get_db
from app.models.agent import AGENT_TIER_PRICES, AgentPurchase
from app.models.pack_purchase import PackPurchase, PackPurchaseStatus
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.models.wallet import Wallet, WalletType
from app.models.wallet_address import WalletAddress

logger = logging.getLogger(__name__)

# BEP-20 address: 0x + 40 hex. Tx hash: 0x + 64 hex.
_BEP20_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TXHASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")

# Pack name → agent tier. Packs are named "Agent 1".."Agent 4".
_PACK_NAME_TO_TIER = {f"Agent {tier}": tier for tier in AGENT_TIER_PRICES}

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


# ── On-chain pack purchase (BEP-20 USDT) — API 1 & API 2 ──────────────────────
#
# A SEPARATE on-chain rail from the deposit-first matrix engine. The frontend pays
# the upline split directly from the buyer's connected wallet (single batched
# MultiSender call); the backend (1) returns the validated recipient split and
# (2) records the outcome. NO internal Wallet/Transaction ledger rows are written
# on this rail — the on-chain transfer IS the payout.
#
# Split rule (client decision): Core Agent rule only.
#   • 60% → two 30% halves to the first two ELIGIBLE uplines
#     (eligible = active + highest active tier >= buyer tier; compression + odd/even).
#   • 40% → platform fee.
#   • A half with no eligible upline (or whose recipient has no valid BEP-20
#     address) is folded into the platform fee — so the split always sums to the
#     pack amount.


class PackPurchaseRequest(BaseModel):
    pack_name: str = Field(..., description='Pack name, e.g. "Agent 1".')
    amount: float | None = Field(
        None, description="Optional; if sent it must match the pack's price (anti-tamper)."
    )


class PackStatusRequest(BaseModel):
    purchase_id: str = Field(..., description='The order id returned by API 1 ("ord_...").')
    status: str = Field(..., description='"success" or "failed".')
    tx_hash: str | None = Field(None, description="Blockchain tx hash (required on success).")
    failure_reason: str | None = Field(None, description="Optional, when status='failed'.")


def _resolve_bep20_address(db: Session, user: User) -> str | None:
    """User's payout address: registration address, else latest verified, else None.
    Only returns it if it is a valid BEP-20 address."""
    addr = user.wallet_address or _verified_addresses(db, [user.id]).get(user.id)
    return addr if addr and _BEP20_RE.match(addr) else None


def _mirror_onchain_ledger(db: Session, record: PackPurchase) -> None:
    """
    Write reporting-only Transaction rows for a settled on-chain pack purchase so
    the internal transaction history and dashboard analytics reflect it:
      • the buyer's outgoing purchase (agent_purchase, an expense), and
      • each upline's commission (core_income), paid directly to their wallet on-chain.

    NO Wallet rows are touched — the money moved on-chain, not through internal
    wallets — so these rows are purely informational (they intentionally do not
    affect withdrawable/account balances).
    """
    try:
        recipients = json.loads(record.recipients_json or "[]")
    except (ValueError, TypeError):
        recipients = []

    tx_short = (record.tx_hash or "")[:12]
    tx_suffix = f" (tx {tx_short}…)" if tx_short else ""

    # Buyer's outgoing purchase.
    db.add(Transaction(
        user_id=record.buyer_id,
        agent_tier=record.agent_tier,
        transaction_type=TransactionType.AGENT_PURCHASE,
        amount=record.amount,
        reference_id=record.order_id,
        notes=f"On-chain purchase — {record.pack_name}, paid from your wallet{tx_suffix}",
    ))

    # Upline commissions (paid directly to each upline's on-chain wallet).
    for r in recipients:
        if r.get("role") != "upline":
            continue
        uid = r.get("user_id")
        amount = r.get("amount") or 0
        if not uid or Decimal(str(amount)) <= 0:
            continue
        db.add(Transaction(
            user_id=uid,
            agent_tier=record.agent_tier,
            transaction_type=TransactionType.CORE_INCOME,
            amount=Decimal(str(amount)),
            reference_id=record.order_id,
            notes=f"On-chain Core commission — {record.pack_name}, paid to your wallet{tx_suffix}",
        ))


def _verify_tx_onchain(record: PackPurchase, tx_hash: str) -> bool:
    """
    Placeholder for on-chain verification (amount / recipients / confirmations).
    Wire up a BSC RPC check here and flip settings.VERIFY_ONCHAIN_TX to enable.
    Returns True (accept) until implemented.
    """
    return True


@router.post("/pack/purchase")
def pack_purchase(
    payload: PackPurchaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_active),
):
    """
    API 1 — create a pack purchase and return the validated on-chain payout split.

    The buyer is the authenticated user. Returns `purchase_id` plus the list of
    recipients (buyer = informational, a dynamic number of upline levels, and an
    optional platform_fee), each with a validated BEP-20 address and the USDT
    amount to send. Amounts sum to the pack price.
    """
    from app.core.pack_payout import compute_pack_split

    tier = _PACK_NAME_TO_TIER.get(payload.pack_name.strip())
    if tier is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown pack_name. Valid packs: {list(_PACK_NAME_TO_TIER)}",
        )

    price = Decimal(str(AGENT_TIER_PRICES[tier]))
    if payload.amount is not None and Decimal(str(payload.amount)) != price:
        raise HTTPException(
            status_code=400,
            detail=f"amount {payload.amount} does not match {payload.pack_name} price {price}.",
        )

    buyer = current_user
    # Advance the Core odd/even counter at purchase-creation time (mutate_counter=True).
    split = compute_pack_split(db, buyer, tier, price, mutate_counter=True)

    recipients: list[dict] = []

    # Buyer entry (informational — frontend confirms it matches the connected wallet).
    buyer_addr = _resolve_bep20_address(db, buyer)
    recipients.append({
        "role": "buyer",
        "level": 0,
        "user_id": buyer.id,
        "username": buyer.username,
        "wallet_address": buyer_addr,
        "has_wallet_address": buyer_addr is not None,
        "amount": 0.0,
    })

    # Upline recipients — merge duplicates (same user across both halves), keep order.
    platform_amount = split.platform_amount
    merged: dict[int, list] = {}   # user_id -> [user, amount, address]
    order: list[int] = []
    for user, amount in split.uplines:
        addr = _resolve_bep20_address(db, user)
        if addr is None:
            platform_amount += amount   # no valid address → platform (missing-upline rule)
            continue
        if user.id in merged:
            merged[user.id][1] += amount
        else:
            merged[user.id] = [user, amount, addr]
            order.append(user.id)

    for level, uid in enumerate(order, start=1):
        user, amount, addr = merged[uid]
        recipients.append({
            "role": "upline",
            "level": level,
            "user_id": user.id,
            "username": user.username,
            "wallet_address": addr,
            "has_wallet_address": True,
            "amount": _two_places(amount),
        })

    # Platform fee (always > 0 here = 40% + any folded halves).
    if platform_amount > 0:
        pf_wallet = settings.PLATFORM_FEE_WALLET or None
        if pf_wallet and not _BEP20_RE.match(pf_wallet):
            pf_wallet = None
        recipients.append({
            "role": "platform_fee",
            "level": None,
            "wallet_address": pf_wallet,
            "has_wallet_address": pf_wallet is not None,
            "amount": _two_places(platform_amount),
        })

    order_id = f"ord_{uuid.uuid4().hex[:12]}"
    record = PackPurchase(
        order_id=order_id,
        buyer_id=buyer.id,
        pack_name=payload.pack_name,
        agent_tier=tier,
        amount=price,
        status=PackPurchaseStatus.PENDING,
        recipients_json=json.dumps(recipients),
    )
    db.add(record)
    db.commit()

    logger.info(
        "PACK purchase: order=%s buyer=%s pack=%s price=$%s uplines=%d platform=$%s",
        order_id, buyer.username, payload.pack_name, price, len(order), _two_places(platform_amount),
    )

    return {
        "purchase_id": order_id,
        "currency": settings.PAYOUT_CURRENCY,
        "network": settings.PAYOUT_NETWORK,
        "token_contract": settings.USDT_CONTRACT,
        "decimals": settings.USDT_DECIMALS,
        "recipients": recipients,
    }


@router.post("/pack/status")
def pack_status(
    payload: PackStatusRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    API 2 — record the outcome of the on-chain transfer for a pack purchase.

    On success: marks the purchase active, stores the tx_hash (optionally verified
    on-chain when settings.VERIFY_ONCHAIN_TX is on). On failure: marks it failed
    with the reason. No payout/ledger is written on this rail.
    """
    status_val = (payload.status or "").strip().lower()
    if status_val not in ("success", "failed"):
        raise HTTPException(status_code=400, detail="status must be 'success' or 'failed'.")

    record = db.query(PackPurchase).filter_by(order_id=payload.purchase_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="purchase_id not found.")
    if record.buyer_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not your purchase.")
    if record.status != PackPurchaseStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Purchase already recorded as '{record.status.value}'.",
        )

    if status_val == "success":
        if not payload.tx_hash or not _TXHASH_RE.match(payload.tx_hash):
            raise HTTPException(
                status_code=400, detail="A valid tx_hash (0x + 64 hex) is required on success."
            )
        if settings.VERIFY_ONCHAIN_TX and not _verify_tx_onchain(record, payload.tx_hash):
            raise HTTPException(status_code=400, detail="On-chain verification failed for tx_hash.")
        record.status = PackPurchaseStatus.SUCCESS
        record.tx_hash = payload.tx_hash
        record.failure_reason = None

        # Reflect ownership so the rest of the app (purchase page "OWNED", the
        # sequential-unlock gate, and Core-eligibility / compression for future
        # on-chain splits) sees this agent as active. We do NOT queue the Celery
        # revenue engine. Guarded against a duplicate tier row in case ownership
        # already exists (e.g. from the deposit-first rail).
        already_owned = (
            db.query(AgentPurchase.id)
            .filter(
                AgentPurchase.user_id == record.buyer_id,
                AgentPurchase.agent_tier == record.agent_tier,
            )
            .first()
        )
        if not already_owned:
            db.add(AgentPurchase(
                user_id=record.buyer_id,
                agent_tier=record.agent_tier,
                price=record.amount,
                status="active",
                payment_id=record.order_id,
                activated_at=datetime.utcnow(),
            ))

        # Mirror the on-chain money movement into the internal ledger for
        # REPORTING ONLY (transaction history + dashboard analytics). These rows
        # carry NO wallet balance: the funds live on-chain in users' own wallets,
        # never in internal wallets — so we write Transaction rows directly and
        # never credit/debit a Wallet. pack/status is idempotent (PENDING-guarded),
        # so this mirror runs exactly once per order.
        _mirror_onchain_ledger(db, record)
    else:
        record.status = PackPurchaseStatus.FAILED
        record.failure_reason = (payload.failure_reason or "Unspecified failure")[:500]

    record.recorded_at = datetime.utcnow()
    db.commit()

    logger.info(
        "PACK status: order=%s buyer_id=%s → %s tx=%s",
        record.order_id, record.buyer_id, record.status.value, record.tx_hash,
    )

    return {
        "purchase_id": record.order_id,
        "status": record.status.value,
        "recorded_at": record.recorded_at.isoformat() + "Z",
    }
