import logging
import random
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.models.wallet import Wallet
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


def _generate_otp() -> str:
    return str(random.randint(100000, 999999))


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
    return (
        db.query(Transaction)
        .filter_by(user_id=current_user.id)
        .order_by(Transaction.created_at.desc())
        .limit(200)
        .all()
    )


# Earnings the user has *received* (Core/Stream/Boost commissions). On the on-chain
# rail these are recorded as CORE_INCOME transactions paid to the user's own wallet
# on-chain — they are NOT credited to an internal Wallet, so internal wallet
# balances stay $0. The correct "Total Earnings" figure therefore comes from the
# ledger (these rows), not from Wallet balances. Sourced from wallet_ops so the
# definition of "income" stays in one place across the codebase.
from app.core.wallet_ops import LEDGER_INCOME_TYPES as INCOME_TYPES

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

    return {
        "total_earned": total_earned,   # lifetime Core/Stream/Boost income
        "total_spent": total_spent,     # lifetime outflows (agent purchases, etc.)
        "by_type": by_type,             # income broken down by transaction type
    }


@router.get("/income/daily")
def daily_income(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Income earned in the last 24 hours, bucketed into 12 two-hour slots
    aligned to IST (Asia/Kolkata) even-hour boundaries.
    Only revenue-engine earnings count (deposits/transfers are excluded).
    Bucket timestamps are emitted as UTC (ISO with trailing 'Z'); because the
    buckets are anchored to IST 2-hour marks, the client renders them as clean
    IST labels (00:00, 02:00, ... 22:00) instead of off-by-:30 values.
    """
    IST_OFFSET = timedelta(hours=5, minutes=30)
    BUCKET_HOURS = 2
    BUCKET_COUNT = 12  # 12 × 2h = 24h window

    # Floor "now" (in IST) to the current even 2-hour boundary, then step back
    # so the window covers the last 24 hours ending at the current bucket.
    now_ist = datetime.utcnow() + IST_OFFSET
    current_bucket_ist = now_ist.replace(
        hour=now_ist.hour - (now_ist.hour % BUCKET_HOURS),
        minute=0,
        second=0,
        microsecond=0,
    )
    start_ist = current_bucket_ist - timedelta(hours=BUCKET_HOURS * (BUCKET_COUNT - 1))
    start_utc = start_ist - IST_OFFSET  # back to UTC for comparison with stored timestamps

    rows = (
        db.query(Transaction)
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.transaction_type.in_(INCOME_TYPES),
            Transaction.created_at >= start_utc,
        )
        .all()
    )

    buckets = [
        {
            "hour": (start_utc + timedelta(hours=BUCKET_HOURS * i)).isoformat() + "Z",
            "amount": 0.0,
        }
        for i in range(BUCKET_COUNT)
    ]
    total = Decimal("0")
    for tx in rows:
        idx = int((tx.created_at - start_utc).total_seconds() // (BUCKET_HOURS * 3600))
        if 0 <= idx < BUCKET_COUNT:
            buckets[idx]["amount"] = round(buckets[idx]["amount"] + float(tx.amount), 4)
            total += Decimal(str(tx.amount))

    return {"total": float(round(total, 4)), "buckets": buckets}


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

    wa = (
        db.query(WalletAddress)
        .filter_by(user_id=current_user.id, address=body.address)
        .first()
    )
    if wa and wa.is_verified:
        return {"message": "Address already verified.", "address": body.address}

    otp = _generate_otp()
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
    if wa.pending_otp != body.otp:
        logger.warning(
            "WALLET address_verify failed: invalid OTP user_id=%d address=%s",
            current_user.id, body.address[:10] + "…",
        )
        raise HTTPException(status_code=400, detail="Invalid verification code.")
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
    return {"message": "Address removed."}
