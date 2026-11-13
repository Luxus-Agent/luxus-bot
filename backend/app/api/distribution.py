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
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.admin import get_admin_user
from app.api.deps import get_current_user, require_platform_active
from app.config import settings
from app.core.platform_state import ensure_platform_active
from app.core.user_lookup import get_user_by_username, usernames_equal
from app.core.wallet_ops import REPURCHASE_RATE, SOFTWARE_FEE_RATE, debit_withdrawable, resolve_payout_address
from app.database import get_db
from app.models.agent import AGENT_TIER_PLATFORM_FEE, AGENT_TIER_PRICES, AgentPurchase
from app.models.pack_purchase import PackPurchase, PackPurchaseStatus
from app.models.payout_batch import PayoutBatch, PayoutBatchStatus
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
    if username and not usernames_equal(username, current_user.username):
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Only admins may query another user's map.")
        root = get_user_by_username(db, username)
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


class PayoutStatusRequest(BaseModel):
    batch_id: str = Field(..., description='The batch id returned by payout/create ("pob_...").')
    status: str = Field(..., description='"success" or "failed".')
    tx_hash: str | None = Field(None, description="Blockchain tx hash (required on success).")
    failure_reason: str | None = Field(None, description="Optional, when status='failed'.")


def _platform_user_id(db: Session) -> int | None:
    """The platform/admin user that owns pool-funding + admin-income ledger rows.
    Returns the lowest-id admin, or None if no admin exists yet."""
    row = (
        db.query(User.id)
        .filter(User.is_admin.is_(True))
        .order_by(User.id.asc())
        .first()
    )
    return row[0] if row else None


def _mirror_onchain_ledger(db: Session, record: PackPurchase) -> None:
    """
    Write reporting Transaction rows for a settled on-chain pack purchase so the
    internal transaction history and dashboard analytics reflect it:
      • the buyer's outgoing purchase (agent_purchase, an expense), and
      • each upline's commission (core_income), paid directly to their wallet on-chain.

    Each upline's Core commission is split 70/20/10 (the client wallet rule) via
    mirror_onchain_earning_split: 70% main + 20% repurchase reserve credited to
    their internal per-tier wallets, and 10% software fee booked as platform profit.
    On-chain, the upline receives the 70% to their own wallet while the 20% reserve
    and 10% fee are paid to platform-held wallets, so these internal balances track
    real per-user holdings. The buyer's purchase row touches no wallet.
    """
    from app.core.wallet_ops import mirror_onchain_earning_split
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

    # Upline commissions. Each upline's gross Core share is split 70/20/10: 70%
    # main (paid to the upline on-chain), 20% repurchase reserve, 10% software fee
    # (both routed on-chain to platform wallets). Per client spec, the ledger income
    # row (what "Total Earnings" sums) records the FULL gross share, not the net
    # 90% left after the platform fee — the fee is still booked separately as its
    # own SOFTWARE_FEE transaction inside mirror_onchain_earning_split.
    for r in recipients:
        if r.get("role") != "upline":
            continue
        uid = r.get("user_id")
        # `gross_amount` is the full Core share; fall back to `amount` for any
        # legacy pending record created before the 70/20/10 split was added.
        gross = Decimal(str(r.get("gross_amount", r.get("amount") or 0)))
        if not uid or gross <= 0:
            continue
        mirror_onchain_earning_split(db, uid, record.agent_tier, gross)
        db.add(Transaction(
            user_id=uid,
            agent_tier=record.agent_tier,
            transaction_type=TransactionType.CORE_INCOME,
            amount=gross,
            reference_id=record.order_id,
            notes=f"On-chain Core commission — {record.pack_name}{tx_suffix}",
        ))

    # Stream (30%) / Boost (9%) pool funding + admin (1%) income — record against
    # the platform/admin user so the money is accounted for. The Stream pool is
    # per-tier; the Boost pool is global (booked at tier 1 — all Boost reserve goes
    # to the $10 bucket per the client spec). The matrix engines (separate) draw
    # these pools down later.
    admin_user_id = _platform_user_id(db)
    if admin_user_id is not None:
        pool_rows = {
            "stream_pool": (TransactionType.STREAM_POOL_FUND, record.agent_tier,
                            f"Stream pool funding (30%) — {record.pack_name}"),
            "boost_pool": (TransactionType.BOOST_POOL_FUND, 1,
                           f"Boost pool funding (9%) — {record.pack_name}"),
            "admin": (TransactionType.ADMIN_INCOME, 0,
                      f"Admin income (1%) — {record.pack_name}"),
            "platform_fee": (TransactionType.PLATFORM_PROFIT, record.agent_tier,
                             f"Platform fee — {record.pack_name}"),
        }
        for r in recipients:
            spec = pool_rows.get(r.get("role"))
            if spec is None:
                continue
            tx_type, tier, note = spec
            gross = Decimal(str(r.get("amount") or 0))
            if gross <= 0:
                continue
            db.add(Transaction(
                user_id=admin_user_id,
                agent_tier=tier,
                transaction_type=tx_type,
                amount=gross,
                reference_id=record.order_id,
                notes=note,
            ))


def _verify_recipients_paid(recipients_json: str | None, tx_hash: str) -> None:
    """
    Verify on-chain that `tx_hash` paid every recipient in a recipients_json
    snapshot (pack purchase OR member-payout batch) — see
    core/onchain.verify_pack_payment. Raises HTTPException: 400 when the payment
    doesn't check out, 503 when it can't be checked right now (the record stays
    PENDING, so the same call can simply be retried).
    """
    from app.core.onchain import verify_pack_payment

    expected: dict[str, Decimal] = {}
    for r in json.loads(recipients_json or "[]"):
        addr = r.get("wallet_address")
        amount = Decimal(str(r.get("amount") or 0))
        # Same filter the frontend applies when building the MultiSender call.
        if r.get("role") == "buyer" or amount <= 0 or not addr or not _BEP20_RE.match(addr):
            continue
        key = addr.lower()
        expected[key] = expected.get(key, Decimal("0")) + amount
    if not expected:
        raise HTTPException(status_code=400, detail="Nothing payable to verify on-chain.")

    status, reason = verify_pack_payment(tx_hash, expected)
    if status == "unavailable":
        raise HTTPException(
            status_code=503,
            detail=f"{reason} It is still pending — retry shortly.",
        )
    if status != "ok":
        raise HTTPException(status_code=400, detail=f"On-chain verification failed: {reason}")


def _verify_tx_onchain(record: PackPurchase, tx_hash: str) -> None:
    """Verify a pack purchase's payment (see _verify_recipients_paid)."""
    _verify_recipients_paid(record.recipients_json, tx_hash)


def _tx_hash_reused(db: Session, tx_hash: str, *, pack_id: int | None = None, batch_id: int | None = None) -> bool:
    """True if `tx_hash` already backs a DIFFERENT pack purchase or payout batch —
    one on-chain payment may only ever settle one record."""
    h = tx_hash.lower()
    q = db.query(PackPurchase.id).filter(func.lower(PackPurchase.tx_hash) == h)
    if pack_id is not None:
        q = q.filter(PackPurchase.id != pack_id)
    if q.first():
        return True
    q = db.query(PayoutBatch.id).filter(func.lower(PayoutBatch.tx_hash) == h)
    if batch_id is not None:
        q = q.filter(PayoutBatch.id != batch_id)
    return q.first() is not None


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

    # `price` is the distribution base (the 60/30/10 split is computed off this).
    # The buyer pays `cost` = base + a flat platform fee that goes straight to the
    # platform profit wallet (per the client "purchase cost" spec).
    price = Decimal(str(AGENT_TIER_PRICES[tier]))
    platform_fee = Decimal(str(AGENT_TIER_PLATFORM_FEE[tier]))
    cost = price + platform_fee
    if payload.amount is not None and Decimal(str(payload.amount)) != cost:
        raise HTTPException(
            status_code=400,
            detail=f"amount {payload.amount} does not match {payload.pack_name} cost {cost}.",
        )

    buyer = current_user

    # Sequential-unlock gate (client rule): each tier can be bought only once and
    # tiers must be purchased in order 1 → 2 → 3 → 4 (no skipping ahead). The
    # frontend already enforces this, but a direct API call would otherwise bypass
    # it — and on this on-chain rail the buyer pays BEFORE /pack/status records
    # ownership, so the check must happen here, before we compute/return the split.
    # Auto-repurchase re-buys an owned tier via app/core/repurchase.py (not this
    # endpoint), so it is unaffected by this guard.
    owned_tiers = {
        t for (t,) in db.query(AgentPurchase.agent_tier).filter(
            AgentPurchase.user_id == buyer.id,
            AgentPurchase.status == "active",
        ).all()
    }
    if tier in owned_tiers:
        raise HTTPException(
            status_code=400,
            detail=f"You already own {payload.pack_name}. Each agent can be purchased once.",
        )
    if tier > 1 and (tier - 1) not in owned_tiers:
        raise HTTPException(
            status_code=400,
            detail=f"Purchase Agent {tier - 1} before Agent {tier}.",
        )

    # Peek (never mutate) the Core odd/even split here — this just decides who the
    # buyer's wallet pays on-chain. The counter only advances for real on pack/status
    # SUCCESS (see below), so a failed/abandoned on-chain attempt (wallet rejection,
    # insufficient gas, user cancels) can never permanently skew a real recipient's
    # odd/even alternation. Since nothing else can change the same recipients' state
    # in the short pack/purchase -> pack/status window, the settlement-time mutation
    # reproduces this exact same decision.
    split = compute_pack_split(db, buyer, tier, price, mutate_counter=False)

    recipients: list[dict] = []

    # Buyer entry (informational — frontend confirms it matches the connected wallet).
    buyer_addr = resolve_payout_address(db, buyer)
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
    # The flat platform fee is added to the platform-fee bucket (alongside any
    # unroutable Core halves), so the recipients sum to the full cost (base + fee).
    platform_amount = split.platform_amount + platform_fee
    merged: dict[int, list] = {}   # user_id -> [user, amount, address]
    order: list[int] = []
    unpaid: dict[int, list] = {}   # user_id -> [user, gross_amount] — eligible Core recipient, no wallet on file
    unpaid_order: list[int] = []
    for user, amount in split.uplines:
        addr = resolve_payout_address(db, user)
        if addr is None:
            platform_amount += amount   # no valid address → platform (missing-upline rule)
            if user.id in unpaid:
                unpaid[user.id][1] += amount
            else:
                unpaid[user.id] = [user, amount]
                unpaid_order.append(user.id)
            continue
        if user.id in merged:
            merged[user.id][1] += amount
        else:
            merged[user.id] = [user, amount, addr]
            order.append(user.id)

    def _pool_address(configured: str) -> str | None:
        """Validated pool/admin wallet, or None when unset/invalid."""
        wallet = configured or None
        if wallet and not _BEP20_RE.match(wallet):
            wallet = None
        return wallet

    # Each Core commission is split 70/20/10 (per the client wallet rule): the
    # upline receives 70% to their own wallet; 20% goes to the platform reserve
    # wallet (held per-user for auto-repurchase) and 10% to the software-fee wallet.
    _four = Decimal("0.0001")
    reserve_total = Decimal("0")
    fee_total = Decimal("0")
    for level, uid in enumerate(order, start=1):
        user, gross, addr = merged[uid]
        software_fee = (gross * SOFTWARE_FEE_RATE).quantize(_four, rounding=ROUND_HALF_UP)
        reserve = (gross * REPURCHASE_RATE).quantize(_four, rounding=ROUND_HALF_UP)
        main = gross - software_fee - reserve  # 70%
        reserve_total += reserve
        fee_total += software_fee
        recipients.append({
            "role": "upline",
            "level": level,
            "user_id": user.id,
            "username": user.username,
            "wallet_address": addr,
            "has_wallet_address": True,
            "amount": _two_places(main),          # 70% paid on-chain to the upline
            "gross_amount": _two_places(gross),   # full Core share (for internal accounting)
        })

    # Repurchase reserve (20% of each Core commission) — to the platform reserve
    # wallet; tracked per user/tier internally for auto-repurchase.
    if reserve_total > 0:
        reserve_wallet = _pool_address(settings.repurchase_reserve_wallet)
        recipients.append({
            "role": "repurchase_reserve",
            "level": None,
            "wallet_address": reserve_wallet,
            "has_wallet_address": reserve_wallet is not None,
            "amount": _two_places(reserve_total),
        })

    # Software fee (10% of each Core commission) → platform profit.
    if fee_total > 0:
        fee_wallet = _pool_address(settings.PLATFORM_FEE_WALLET)
        recipients.append({
            "role": "software_fee",
            "level": None,
            "wallet_address": fee_wallet,
            "has_wallet_address": fee_wallet is not None,
            "amount": _two_places(fee_total),
        })

    # Stream (30%) + Boost pool (9%) — these matrix pools are tracked internally
    # by the Stream/Boost engines, not held in their own on-chain wallet, so they
    # fold into the platform-fee bucket below.
    platform_amount += split.stream_amount + split.boost_amount

    # Admin income (1%) — the admin cut of the Boost 10% allocation.
    admin_wallet = _pool_address(settings.admin_income_wallet)
    recipients.append({
        "role": "admin",
        "level": None,
        "wallet_address": admin_wallet,
        "has_wallet_address": admin_wallet is not None,
        "amount": _two_places(split.admin_amount),
    })

    # Reporting-only: an eligible Core recipient who couldn't be paid (no wallet
    # address on file) — their share is already folded into platform_fee above
    # (that's the real money movement); this entry just preserves WHO the routing
    # decided on, for display (e.g. the Purchase Distribution Preview), with
    # amount=0 (nothing payable) and no wallet_address so it's inert on every
    # on-chain/ledger path that filters by has_wallet_address or amount > 0.
    for uid in unpaid_order:
        user, gross = unpaid[uid]
        recipients.append({
            "role": "core_unpaid",
            "level": None,
            "user_id": user.id,
            "username": user.username,
            "wallet_address": None,
            "has_wallet_address": False,
            "amount": 0.0,
            "gross_amount": _two_places(gross),
        })

    # Platform fee — the flat per-tier purchase fee, the Stream (30%) + Boost pool
    # (9%) shares, plus any unroutable Core halves (no eligible upline). Goes to
    # the platform profit wallet. Omitted only when zero (never, given the flat fee).
    if platform_amount > 0:
        pf_wallet = _pool_address(settings.PLATFORM_FEE_WALLET)
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
        amount=cost,
        status=PackPurchaseStatus.PENDING,
        recipients_json=json.dumps(recipients),
    )
    db.add(record)
    db.commit()

    logger.info(
        "PACK purchase: order=%s buyer=%s pack=%s cost=$%s (base $%s + fee $%s) uplines=%d platform=$%s",
        order_id, buyer.username, payload.pack_name, cost, price, platform_fee,
        len(order), _two_places(platform_amount),
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
    current_user: User = Depends(require_platform_active),
):
    """
    API 2 — record the outcome of the on-chain transfer for a pack purchase.

    On success: marks the purchase active, stores the tx_hash (verified on-chain
    against the recorded recipient split unless settings.VERIFY_ONCHAIN_TX is off). On failure: marks it failed
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

    run_payouts_after_commit = False
    if status_val == "success":
        from app.core.pack_payout import compute_pack_split

        if not payload.tx_hash or not _TXHASH_RE.match(payload.tx_hash):
            raise HTTPException(
                status_code=400, detail="A valid tx_hash (0x + 64 hex) is required on success."
            )
        tx_hash = payload.tx_hash.lower()
        # One payment can only ever fund ONE purchase — reject a replayed hash.
        if _tx_hash_reused(db, tx_hash, pack_id=record.id):
            raise HTTPException(status_code=400, detail="This tx_hash was already used for another purchase.")
        if settings.VERIFY_ONCHAIN_TX:
            _verify_tx_onchain(record, tx_hash)
        record.status = PackPurchaseStatus.SUCCESS
        record.tx_hash = tx_hash
        record.failure_reason = None

        # Reflect ownership so the rest of the app (purchase page "OWNED", the
        # sequential-unlock gate, and Core-eligibility / compression for future
        # on-chain splits) sees this agent as active. There is no internal revenue
        # engine to run on this rail. Guarded against a duplicate tier row in case
        # ownership already exists.
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

        # Now that the on-chain transfer actually succeeded, advance the Core
        # odd/even counter for real (mutate_counter=True) — reproducing the exact
        # same decision that was peeked at pack/purchase and already paid out
        # on-chain (recipients_json). Deferred to here so a failed/abandoned
        # attempt never consumes a real recipient's odd/even alternation.
        record_price = Decimal(str(AGENT_TIER_PRICES[record.agent_tier]))
        compute_pack_split(db, record.buyer, record.agent_tier, record_price, mutate_counter=True)

        # Mirror the on-chain money movement into the internal ledger for
        # REPORTING ONLY (transaction history + dashboard analytics). These rows
        # carry NO wallet balance: the funds live on-chain in users' own wallets,
        # never in internal wallets — so we write Transaction rows directly and
        # never credit/debit a Wallet. pack/status is idempotent (PENDING-guarded),
        # so this mirror runs exactly once per order.
        _mirror_onchain_ledger(db, record)

        # Stream (30%) + Boost (10%) matrix engines: place the buyer in both
        # matrices and queue the level-payout / re-entry / sponsor-share work
        # into the durable backlog. Placement ONLY moves no money, so it stays
        # inside this atomic transaction; the payouts (which can broadcast real
        # USDT) are drained AFTER the commit below. PENDING-guarded, so the
        # placement happens exactly once per order.
        from app.core.matrix_runtime import place_purchase_in_matrices
        place_purchase_in_matrices(db, record.buyer_id, record.agent_tier)
        run_payouts_after_commit = True
    else:
        record.status = PackPurchaseStatus.FAILED
        record.failure_reason = (payload.failure_reason or "Unspecified failure")[:500]

    record.recorded_at = datetime.utcnow()
    db.commit()

    # Stage 2 — payouts. The purchase above is now durably recorded; everything
    # below can broadcast real USDT, so each unit (one backlog row / one
    # repurchase) commits on its own and a failure can never roll back an
    # already-broadcast payout (which a retry would then pay a second time — see
    # models/onchain_settlement.py). Best-effort: anything not finished stays
    # queued in the durable backlog / reserves and is picked up by the next
    # purchase, exactly like the existing bounded-budget deferral.
    if run_payouts_after_commit:
        try:
            from app.core.matrix_runtime import drain_matrix_backlog
            from app.core.repurchase import sweep_auto_repurchases

            drain_matrix_backlog(db, commit_each=True)
            # Auto-repurchase: re-buy any tier whose reserve has reached its
            # threshold, cascading through the uplines those repurchases credit.
            sweep_auto_repurchases(db, commit_each=True)
        except Exception:
            db.rollback()
            logger.exception(
                "PACK status: order=%s recorded, but payout processing failed — "
                "remaining work stays queued for the next purchase.", record.order_id,
            )

    logger.info(
        "PACK status: order=%s buyer_id=%s → %s tx=%s",
        record.order_id, record.buyer_id, record.status.value, record.tx_hash,
    )

    return {
        "purchase_id": record.order_id,
        "status": record.status.value,
        "recorded_at": record.recorded_at.isoformat() + "Z",
    }


# ── Member payout (Stream/Boost/Core earnings -> members' own wallets) ──────
#
# pack/purchase + pack/status move money buyer -> platform (+ uplines) on-chain.
# This pair runs the same MultiSender contract in reverse: platform wallet ->
# every member with a positive withdrawable balance. Admin-only.


@router.post("/payout/create")
def payout_create(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """
    API 1 (member payout) — snapshot every user's current withdrawable balance
    (MAIN wallet earnings + ACCOUNT balance) and return the recipient list for
    the platform wallet to pay out on-chain, via the same MultiSender contract
    used for pack purchases (sendERC20DifferentValue) — just called by the
    platform wallet instead of a buyer.

    Refuses to create a new batch while one is already PENDING, so two
    overlapping snapshots can never debit the same balance twice.
    """
    ensure_platform_active(db)

    existing_pending = (
        db.query(PayoutBatch)
        .filter(PayoutBatch.status == PayoutBatchStatus.PENDING)
        .first()
    )
    if existing_pending:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Batch {existing_pending.batch_id} is still pending — resolve it via "
                "POST /distribution/payout/status before creating a new one."
            ),
        )

    users = db.query(User).order_by(User.id.asc()).all()
    user_ids = [u.id for u in users]
    totals = _wallet_totals(db, user_ids)
    verified_fallback = _verified_addresses(db, user_ids)

    recipients: list[dict] = []
    skipped_count = 0
    skipped_total = Decimal("0")
    for user in users:
        withdrawable = totals[user.id]["main"] + totals[user.id]["account"]
        if withdrawable <= 0:
            continue
        addr = user.wallet_address or verified_fallback.get(user.id)
        if not addr or not _BEP20_RE.match(addr):
            skipped_count += 1
            skipped_total += withdrawable
            continue
        recipients.append({
            "user_id": user.id,
            "username": user.username,
            "wallet_address": addr,
            "amount": _two_places(withdrawable),
        })

    if not recipients:
        raise HTTPException(
            status_code=400,
            detail="Nothing to distribute — no positive withdrawable balance with a valid wallet address.",
        )

    total_amount = sum((Decimal(str(r["amount"])) for r in recipients), Decimal("0"))
    batch_id = f"pob_{uuid.uuid4().hex[:12]}"
    batch = PayoutBatch(
        batch_id=batch_id,
        created_by_id=admin.id,
        total_amount=total_amount,
        status=PayoutBatchStatus.PENDING,
        recipients_json=json.dumps(recipients),
    )
    db.add(batch)
    db.commit()

    logger.info(
        "PAYOUT create: batch=%s admin=%s recipients=%d total=%s skipped=%d ($%s)",
        batch_id, admin.username, len(recipients), total_amount, skipped_count, skipped_total,
    )

    return {
        "batch_id": batch_id,
        "currency": settings.PAYOUT_CURRENCY,
        "network": settings.PAYOUT_NETWORK,
        "token_contract": settings.USDT_CONTRACT,
        "decimals": settings.USDT_DECIMALS,
        "total_amount": _two_places(total_amount),
        "recipients": recipients,
        "skipped_no_address": {
            "count": skipped_count,
            "amount": _two_places(skipped_total),
        },
    }


@router.post("/payout/status")
def payout_status(
    payload: PayoutStatusRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """
    API 2 (member payout) — record the outcome of the on-chain MultiSender
    distribution for a payout batch.

    On success: debits each recipient's withdrawable balance (MAIN wallets,
    lowest tier first, then ACCOUNT — the same drain order `debit_withdrawable`
    uses for a manual withdrawal) by exactly the amount in the batch snapshot,
    so the next wallet-map call won't report that money as still owed. This is
    the step that turns "credited internally" into "actually paid" — idempotent,
    PENDING-guarded, so a batch can only ever be settled once.
    """
    ensure_platform_active(db)

    status_val = (payload.status or "").strip().lower()
    if status_val not in ("success", "failed"):
        raise HTTPException(status_code=400, detail="status must be 'success' or 'failed'.")

    batch = db.query(PayoutBatch).filter_by(batch_id=payload.batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="batch_id not found.")
    if batch.status != PayoutBatchStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Batch already recorded as '{batch.status.value}'.",
        )

    if status_val == "success":
        if not payload.tx_hash or not _TXHASH_RE.match(payload.tx_hash):
            raise HTTPException(
                status_code=400, detail="A valid tx_hash (0x + 64 hex) is required on success."
            )

        tx_hash = payload.tx_hash.lower()
        # Never trust the admin-supplied hash: it must be unused, and the chain
        # must show it really paid every recipient in this batch BEFORE we debit
        # anyone's balance. Failures leave the batch PENDING (nothing debited).
        if _tx_hash_reused(db, tx_hash, batch_id=batch.id):
            raise HTTPException(status_code=400, detail="This tx_hash was already used for another record.")
        if settings.VERIFY_ONCHAIN_TX:
            _verify_recipients_paid(batch.recipients_json, tx_hash)

        try:
            recipients = json.loads(batch.recipients_json or "[]")
        except (ValueError, TypeError):
            recipients = []

        tx_short = tx_hash[:12]
        for r in recipients:
            amount = Decimal(str(r.get("amount") or 0))
            if amount <= 0:
                continue
            debit_withdrawable(
                db, r["user_id"], amount,
                reference_id=batch.batch_id,
                notes=f"On-chain earnings payout — batch {batch.batch_id} (tx {tx_short}…)",
            )

        batch.status = PayoutBatchStatus.SUCCESS
        batch.tx_hash = tx_hash
        batch.failure_reason = None
    else:
        batch.status = PayoutBatchStatus.FAILED
        batch.failure_reason = (payload.failure_reason or "Unspecified failure")[:500]

    batch.recorded_at = datetime.utcnow()
    db.commit()

    logger.info(
        "PAYOUT status: batch=%s admin=%s → %s tx=%s",
        batch.batch_id, admin.username, batch.status.value, batch.tx_hash,
    )

    return {
        "batch_id": batch.batch_id,
        "status": batch.status.value,
        "recorded_at": batch.recorded_at.isoformat() + "Z",
    }
