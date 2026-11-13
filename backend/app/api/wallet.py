import logging
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core import rate_limit
from app.core.core_preview import get_downline_odd_even, simulate_core_split
from app.core.wallet_ops import resolve_tx_hashes
from app.database import get_db
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.models.wallet import Wallet, WalletType
from app.models.wallet_address import WalletAddress
from app.schemas.agent import (
    TransactionOut,
    WalletAddressIn,
    WalletAddressOut,
    WalletAddressVerifyIn,
    WalletOut,
)

router = APIRouter(prefix="/wallet", tags=["wallet"])

ADDRESS_OTP_EXPIRE_MINUTES = 30
# Wrong guesses allowed against one issued address-verification code.
ADDRESS_OTP_MAX_ATTEMPTS = 5


def _generate_otp() -> str:
    # Cryptographically secure 6-digit code (never the `random` module).
    return str(secrets.randbelow(900000) + 100000)


# ── Balances & transactions ───────────────────────────────────────────────────

@router.get("/balances", response_model=list[WalletOut])
def get_balances(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Wallet).filter_by(user_id=current_user.id).all()


@router.get("/transactions", response_model=list[TransactionOut])
def get_transactions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    txns = (
        db.query(Transaction)
        .filter_by(user_id=current_user.id)
        .order_by(Transaction.created_at.desc())
        .limit(200)
        .all()
    )
    tx_hashes = resolve_tx_hashes(db, {t.reference_id for t in txns if t.reference_id})
    results = []
    for t in txns:
        out = TransactionOut.model_validate(t)
        # Prefer the row's own tx_hash (Stream/Boost payouts settled instantly
        # on-chain via matrix_runtime._settle_or_credit) — fall back to the
        # PackPurchase/PayoutBatch resolver for Core / member-payout rows,
        # which settle as part of a shared multisender transaction instead.
        out.tx_hash = t.tx_hash or tx_hashes.get(t.reference_id)
        results.append(out)
    return results


# Earnings the user has *received* (Core/Stream/Boost commissions). On the on-chain
# rail these are recorded as CORE_INCOME transactions paid to the user's own wallet
# on-chain — they are NOT credited to an internal Wallet, so internal wallet
# balances stay $0. The correct "Total Earnings" figure therefore comes from the
# ledger (these rows), not from Wallet balances. Sourced from wallet_ops so the
# definition of "income" stays in one place across the codebase.
from app.core.wallet_ops import LEDGER_INCOME_TYPES as INCOME_TYPES
from app.core.wallet_ops import REPURCHASE_RATE, SOFTWARE_FEE_RATE

# Core commission's on-chain "main" share (70%) is paid directly, buyer → upline,
# at purchase time (see mirror_onchain_earning_split) — so it is Completed the
# instant the CORE_INCOME row is written. Stream's main share is credited to an
# internal MAIN wallet instead (see credit_wallet, 70/20/10) and only becomes
# Completed once an admin payout run actually debits it.
MAIN_SHARE_RATE = Decimal("1") - REPURCHASE_RATE - SOFTWARE_FEE_RATE  # 70%, Stream-only

# Boost skips the repurchase-reserve cut but DOES take the 10% software fee
# on a position holder's own payout (credit_boost_wallet / mirror_onchain_
# boost_split) — so its "MAIN-eligible" share is 90%, not the full 100%.
# Boost's sponsor-share bonus is unaffected (paid in addition, unreduced —
# see BOOST/SPONSOR handling below, which never multiplies by this rate).
BOOST_MAIN_SHARE_RATE = Decimal("1") - SOFTWARE_FEE_RATE  # 90%, Boost's own payout only

# Money that has left the user (real outflows). agent_purchase covers the on-chain
# pack buys; the rest are legacy deposit-first flows kept for historical rows.
EXPENSE_TYPES = [
    TransactionType.AGENT_PURCHASE,
    TransactionType.PURCHASE,
    TransactionType.WITHDRAWAL,
    TransactionType.TRANSFER_OUT,
]


@router.get("/earnings")
def earnings_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lifetime earnings + spend, summed live from the transaction ledger — no admin
    approval, and not capped at the 200-row transaction listing.

    "Total Earnings" must be read from here (the ledger), NOT from internal Wallet
    balances: on the on-chain rail commissions are paid to users' own wallets
    on-chain and the internal wallets stay $0, so a wallet-balance figure would
    always read $0 even after real income.

    Also splits that same total into `completed` (money that has actually left
    the platform for the user — Core's 70% on-chain share; any Stream/Boost/
    sponsor share that settled instantly on-chain via matrix_runtime's
    _settle_or_credit (tx_hash IS NOT NULL); plus any UNSETTLED Stream/Boost/
    sponsor share an admin payout has since debited from the MAIN wallet) vs
    `pending` (money still moving through the platform: the repurchase reserve
    building toward the next auto-repurchase, and any unsettled Stream/Boost
    main-wallet share not yet paid out). completed + pending always equals
    total_earned minus the platform's software fee share (never the user's
    money either way).
    """
    income_rows = (
        db.query(Transaction.transaction_type, func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.transaction_type.in_(INCOME_TYPES),
        )
        .group_by(Transaction.transaction_type)
        .all()
    )
    expense_rows = (
        db.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.transaction_type.in_(EXPENSE_TYPES),
        )
        .scalar()
    )

    by_type = {ttype.value: float(round(Decimal(str(amount)), 4)) for ttype, amount in income_rows}
    total_earned = float(round(sum((Decimal(str(a)) for _, a in income_rows), Decimal("0")), 4))
    total_spent = float(round(Decimal(str(expense_rows or 0)), 4))

    gross_core = Decimal(str(by_type.get(TransactionType.CORE_INCOME.value, 0)))

    def _sum(tx_type: TransactionType, ref_like: str | None, settled: bool) -> Decimal:
        q = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.user_id == current_user.id,
            Transaction.transaction_type == tx_type,
            Transaction.tx_hash.isnot(None) if settled else Transaction.tx_hash.is_(None),
        )
        if ref_like:
            q = q.filter(Transaction.reference_id.like(ref_like))
        return Decimal(str(q.scalar() or 0))

    # Sponsor share has no source-system column of its own — rows are told
    # apart by the reference_id prefix matrix_runtime._credit_row_sponsor tags
    # them with. Untagged legacy rows predate the Boost no-split change and
    # were genuinely credited at 70% at the time, so they fall into the
    # Stream-rate bucket too (same reasoning as GET /admin/metrics).
    STREAM, BOOST, SPONSOR = (
        TransactionType.STREAM_PAYOUT, TransactionType.BOOST_PAYOUT,
        TransactionType.SPONSOR_MILESTONE_INCOME,
    )
    stream_settled, stream_unsettled = _sum(STREAM, None, True), _sum(STREAM, None, False)
    boost_settled, boost_unsettled = _sum(BOOST, None, True), _sum(BOOST, None, False)
    sponsor_boost_settled = _sum(SPONSOR, "sponsor_share_boost_%", True)
    sponsor_boost_unsettled = _sum(SPONSOR, "sponsor_share_boost_%", False)
    sponsor_stream_settled = _sum(SPONSOR, None, True) - sponsor_boost_settled
    sponsor_stream_unsettled = _sum(SPONSOR, None, False) - sponsor_boost_unsettled

    reserve_total = (
        db.query(func.coalesce(func.sum(Wallet.balance), 0))
        .filter(Wallet.user_id == current_user.id, Wallet.wallet_type == WalletType.REPURCHASE)
        .scalar()
    )
    main_total = (
        db.query(func.coalesce(func.sum(Wallet.balance), 0))
        .filter(Wallet.user_id == current_user.id, Wallet.wallet_type == WalletType.MAIN)
        .scalar()
    )
    pending_reserve = Decimal(str(reserve_total or 0))
    pending_payout = Decimal(str(main_total or 0))

    completed_core = gross_core * MAIN_SHARE_RATE
    # Settled rows already went straight to the recipient's own wallet — the
    # exact share send_matrix_payout_settlement broadcast (70% Stream, 90%
    # Boost's own payout, 100% any sponsor-share bonus). No inference needed.
    settled_stream_boost = (
        stream_settled * MAIN_SHARE_RATE + boost_settled * BOOST_MAIN_SHARE_RATE
        + sponsor_stream_settled * MAIN_SHARE_RATE + sponsor_boost_settled
    )
    # Unsettled rows were credited to MAIN internally, exactly as before this
    # feature existed; any of that no longer sitting in MAIN has since been
    # paid out by an admin payout run — same inference as before, just scoped
    # to only the unsettled subset (settled rows never touched MAIN at all).
    main_eligible_unsettled = (
        stream_unsettled * MAIN_SHARE_RATE + boost_unsettled * BOOST_MAIN_SHARE_RATE
        + sponsor_stream_unsettled * MAIN_SHARE_RATE + sponsor_boost_unsettled
    )
    paid_out_unsettled = max(main_eligible_unsettled - pending_payout, Decimal("0"))
    completed = completed_core + settled_stream_boost + paid_out_unsettled

    return {
        "total_earned": total_earned,   # lifetime Core/Stream/Boost income (gross)
        "total_spent": total_spent,     # lifetime outflows (agent purchases, etc.)
        "by_type": by_type,             # income broken down by transaction type
        "completed": float(round(completed, 4)),           # already delivered to the user
        "pending_reserve": float(round(pending_reserve, 4)),  # building toward next auto-repurchase
        "pending_payout": float(round(pending_payout, 4)),    # Stream/Boost, awaiting next payout run
    }


@router.get("/income/daily")
def daily_income(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Cumulative income over the user's full history, grouped by IST (Asia/Kolkata)
    calendar day. Each bucket's `amount` is the RUNNING TOTAL earned up to and
    including that day, so the chart climbs from the past to the present and the
    final point equals lifetime earnings (per the client: an accumulative line,
    not a rolling 24h window).

    Only revenue-engine earnings count (deposits/transfers are excluded). To keep
    the payload bounded the series shows at most the last `MAX_DAYS` days; any
    earlier income is folded into the starting cumulative so the first visible
    point already sits at the correct height. Bucket timestamps are the IST
    midnight of each day, emitted as UTC (ISO + 'Z') so the client renders clean
    IST date labels. Empty days carry the previous cumulative forward.
    """
    IST_OFFSET = timedelta(hours=5, minutes=30)
    MAX_DAYS = 90  # cap on the number of daily points returned

    rows = (
        db.query(Transaction)
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.transaction_type.in_(INCOME_TYPES),
        )
        .order_by(Transaction.created_at.asc())
        .all()
    )
    if not rows:
        return {"total": 0.0, "buckets": []}

    # Sum income per IST calendar day.
    per_day: dict = {}
    for tx in rows:
        day = (tx.created_at + IST_OFFSET).date()
        per_day[day] = per_day.get(day, Decimal("0")) + Decimal(str(tx.amount))

    first_day = min(per_day)
    today_ist = (datetime.utcnow() + IST_OFFSET).date()
    window_start = max(first_day, today_ist - timedelta(days=MAX_DAYS - 1))

    # Income that predates the visible window seeds the starting cumulative.
    cumulative = sum(
        (amt for d, amt in per_day.items() if d < window_start), Decimal("0")
    )

    buckets = []
    day = window_start
    while day <= today_ist:
        cumulative += per_day.get(day, Decimal("0"))
        ist_midnight_utc = datetime(day.year, day.month, day.day) - IST_OFFSET
        buckets.append({
            "hour": ist_midnight_utc.isoformat() + "Z",
            "amount": float(round(cumulative, 4)),
        })
        day += timedelta(days=1)

    grand_total = sum(per_day.values(), Decimal("0"))
    return {"total": float(round(grand_total, 4)), "buckets": buckets}


# ── Repurchase reserve (auto-repurchase progress + history) ───────────────────

@router.get("/repurchase")
def repurchase_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Per-tier repurchase reserve and progress toward the next auto-repurchase.

    Each tier holds back 20% of income into its REPURCHASE wallet; when the
    balance reaches the threshold (pack price + platform fee) the platform
    auto-re-buys that tier. Returns one row per tier with the live reserve,
    threshold, and a 0–100% progress figure for the progress bar.
    """
    from app.core.repurchase import REPURCHASE_PLATFORM_FEE, repurchase_threshold
    from app.models.agent import AGENT_TIER_PRICES
    from app.models.wallet import WalletType

    reserves = {
        w.agent_tier: Decimal(str(w.balance))
        for w in db.query(Wallet)
        .filter_by(user_id=current_user.id, wallet_type=WalletType.REPURCHASE)
        .all()
    }

    tiers = []
    for tier, price in AGENT_TIER_PRICES.items():
        reserve = reserves.get(tier, Decimal("0"))
        threshold = repurchase_threshold(tier)
        progress = float(min(reserve / threshold, Decimal("1")) * 100) if threshold > 0 else 0.0
        tiers.append({
            "agent_tier": tier,
            "price": float(price),
            "platform_fee": float(REPURCHASE_PLATFORM_FEE[tier]),
            "threshold": float(threshold),
            "reserve": float(round(reserve, 4)),
            "progress_percent": round(progress, 2),
            "ready": reserve >= threshold,
        })
    return {"tiers": tiers}


@router.get("/repurchase/history")
def repurchase_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """History of automatic repurchases (most recent first)."""
    rows = (
        db.query(Transaction)
        .filter_by(
            user_id=current_user.id,
            transaction_type=TransactionType.REPURCHASE_BUY,
        )
        .order_by(Transaction.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": t.id,
            "agent_tier": t.agent_tier,
            "amount": float(t.amount),
            "notes": t.notes,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]


# ── Wallet address management ─────────────────────────────────────────────────

@router.get("/addresses", response_model=list[WalletAddressOut])
def list_addresses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all verified BEP-20 withdrawal addresses for the current user."""
    return (
        db.query(WalletAddress)
        .filter_by(user_id=current_user.id, is_verified=True)
        .order_by(WalletAddress.created_at.desc())
        .all()
    )


@router.post("/address", response_model=dict)
async def register_address(
    body: WalletAddressIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Register a BEP-20 withdrawal address. Sends an email OTP to verify ownership.
    Use POST /wallet/address/verify to confirm the code.
    """
    from app.services.email_service import send_address_verification_email

    rate_limit.enforce("address_otp", str(current_user.id), 5, 3600)
    wa = (
        db.query(WalletAddress)
        .filter_by(user_id=current_user.id, address=body.address)
        .first()
    )
    if wa and wa.is_verified:
        return {"message": "Address already verified.", "address": body.address}

    otp = _generate_otp()
    rate_limit.otp_reset(f"addr:{current_user.id}:{body.address.lower()}")
    if not wa:
        wa = WalletAddress(
            user_id=current_user.id,
            address=body.address,
            label=body.label,
        )
        db.add(wa)
    else:
        wa.label = body.label or wa.label

    wa.pending_otp = otp
    wa.otp_expires_at = datetime.utcnow() + timedelta(minutes=ADDRESS_OTP_EXPIRE_MINUTES)
    db.commit()

    background_tasks.add_task(
        send_address_verification_email,
        current_user.email,
        otp,
        body.address,
    )

    logger.info(
        "WALLET otp_sent: type=address_verification user_id=%d username=%s address=%s",
        current_user.id, current_user.username, body.address[:10] + "…",
    )
    return {
        "message": "Verification code sent to your email. Use POST /wallet/address/verify to confirm.",
        "address": body.address,
    }


@router.post("/address/verify", response_model=WalletAddressOut)
def verify_address(
    body: WalletAddressVerifyIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Confirm the OTP and mark the BEP-20 address as verified."""
    wa = (
        db.query(WalletAddress)
        .filter_by(user_id=current_user.id, address=body.address)
        .first()
    )
    if not wa or not wa.pending_otp:
        raise HTTPException(
            status_code=400,
            detail="No pending verification for this address. Register it first via POST /wallet/address.",
        )
    otp_key = f"addr:{current_user.id}:{body.address.lower()}"
    if not secrets.compare_digest(wa.pending_otp, (body.otp or "").strip()):
        logger.warning(
            "WALLET address_verify failed: invalid OTP user_id=%d address=%s",
            current_user.id, body.address[:10] + "…",
        )
        if rate_limit.otp_failed(otp_key, ADDRESS_OTP_MAX_ATTEMPTS):
            wa.pending_otp = None
            wa.otp_expires_at = None
            db.commit()
            raise HTTPException(
                status_code=429,
                detail="Too many incorrect attempts. Please request a new verification code.",
            )
        raise HTTPException(status_code=400, detail="Invalid verification code.")
    rate_limit.otp_reset(otp_key)
    if not wa.otp_expires_at or datetime.utcnow() > wa.otp_expires_at:
        logger.warning(
            "WALLET address_verify failed: expired OTP user_id=%d address=%s",
            current_user.id, body.address[:10] + "…",
        )
        raise HTTPException(status_code=400, detail="Verification code has expired.")

    wa.is_verified = True
    wa.pending_otp = None
    wa.otp_expires_at = None
    db.commit()
    db.refresh(wa)

    logger.info(
        "WALLET address_verified: user_id=%d username=%s address=%s",
        current_user.id, current_user.username, body.address[:10] + "…",
    )
    return wa


@router.delete("/address/{address_id}", response_model=dict)
def delete_address(
    address_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a registered withdrawal address."""
    wa = db.query(WalletAddress).filter_by(id=address_id, user_id=current_user.id).first()
    if not wa:
        raise HTTPException(status_code=404, detail="Address not found.")
    logger.info(
        "WALLET address_deleted: user_id=%d username=%s address_id=%d address=%s",
        current_user.id, current_user.username, address_id, wa.address[:10] + "…",
    )
    db.delete(wa)
    db.commit()
    return {"deleted": True}


# ── Core routing preview ──────────────────────────────────────────────────────

@router.get("/core-preview")
def core_preview(
    tier: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Read-only preview of where the CURRENT user's own Core 60% would route if
    they bought `tier` right now — same simulation the admin "Revenue Engines"
    page uses, scoped to the logged-in user (no username lookup, no admin
    privilege needed). Only peeks at the per-tier core_route_count; never persists.
    """
    if tier not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="tier must be 1-4.")
    return simulate_core_split(db, current_user, tier)


@router.get("/core-downline")
def core_downline(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Read-only: the CURRENT user's own direct downline split into a left/odd and
    right/even column by join order — same view as the admin "Revenue Engines"
    page's Downline Odd/Even Table, scoped to the logged-in user (no username
    lookup, no admin privilege needed).
    """
    return get_downline_odd_even(db, current_user)
