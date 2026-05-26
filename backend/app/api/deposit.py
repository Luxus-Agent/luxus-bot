"""
Deposit & Transfer endpoints.

Deposit flow:
  POST /deposit          → create a pending Deposit + NOWPayments invoice
  GET  /deposit          → list user's deposits
  GET  /deposit/balance  → current account balance

Transfer flow:
  POST /deposit/transfer        → initiate transfer; sends OTP email on first use per recipient
  POST /deposit/transfer/verify → confirm OTP (first-time only) and execute transfer
"""
import random
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.wallet_ops import credit_account, debit_account, get_account_balance, ACCOUNT_TIER
from app.database import get_db
from app.models.deposit import Deposit
from app.models.transfer_verification import TransferVerification
from app.models.transaction import TransactionType
from app.models.user import User
from app.schemas.agent import DepositIn, DepositOut, DepositRefundIn, TransferIn, TransferVerifyIn

router = APIRouter(prefix="/deposit", tags=["deposit"])

TRANSFER_FEE_RATE = Decimal("0.01")   # 1% platform fee
TRANSFER_OTP_EXPIRE_MINUTES = 30


def _generate_otp() -> str:
    return str(random.randint(100000, 999999))


# ── Balance ───────────────────────────────────────────────────────────────────

@router.get("/balance")
def account_balance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current account balance available for purchasing agents."""
    balance = get_account_balance(db, current_user.id)
    return {"account_balance": float(balance)}


# ── Deposit ───────────────────────────────────────────────────────────────────

@router.post("", response_model=dict)
async def create_deposit(
    body: DepositIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a deposit invoice via NOWPayments.
    Returns the invoice_url — redirect the user there to pay with USDT (BEP-20).
    """
    from app.services.nowpayments import create_deposit_invoice

    deposit = Deposit(
        user_id=current_user.id,
        amount_usd=float(body.amount_usd),
        status="pending",
    )
    db.add(deposit)
    db.commit()
    db.refresh(deposit)

    return await create_deposit_invoice(
        db=db,
        deposit_id=deposit.id,
        amount_usd=float(body.amount_usd),
    )


@router.get("/status/{order_id}")
def deposit_status(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the status of a single deposit by order_id.
    Used by the frontend to poll for payment confirmation without fetching the full list.
    """
    deposit = (
        db.query(Deposit)
        .filter_by(order_id=order_id, user_id=current_user.id)
        .first()
    )
    if not deposit:
        raise HTTPException(status_code=404, detail="Deposit not found.")
    return {
        "status":     deposit.status,
        "order_id":   deposit.order_id,
        "amount_usd": float(deposit.amount_usd),
    }


@router.get("", response_model=list[DepositOut])
def list_deposits(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all deposits for the current user."""
    return (
        db.query(Deposit)
        .filter_by(user_id=current_user.id)
        .order_by(Deposit.created_at.desc())
        .limit(100)
        .all()
    )


# ── Refund ────────────────────────────────────────────────────────────────────

@router.post("/refund")
async def refund_deposit(
    body: DepositRefundIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Refund the full unspent account balance back to the user's BEP-20 wallet.
    Requires a non-zero account balance. The user bears all network fees.
    """
    from app.services.nowpayments import send_payout

    balance = get_account_balance(db, current_user.id)
    if balance <= 0:
        raise HTTPException(status_code=400, detail="No account balance to refund.")

    debit_account(
        db=db,
        user_id=current_user.id,
        amount=balance,
        tx_type=TransactionType.TRANSFER_OUT,
        reference_id=f"refund_{current_user.id}",
        notes=f"Deposit refund to {body.wallet_address[:10]}…",
    )
    db.commit()

    try:
        result = await send_payout(
            withdrawal_id=0,
            amount_usd=float(balance),
            wallet_address=body.wallet_address,
        )
    except Exception as exc:
        credit_account(
            db=db,
            user_id=current_user.id,
            amount=balance,
            tx_type=TransactionType.TRANSFER_IN,
            reference_id=f"refund_{current_user.id}_restored",
            notes="Deposit refund failed — balance restored",
        )
        db.commit()
        raise HTTPException(status_code=502, detail=f"Payout failed: {exc}")

    return {
        "message": f"${float(balance):.2f} refund dispatched",
        "wallet_address": body.wallet_address,
        "nowpayments_payout_id": str(result.get("id", "")),
    }


# ── Transfer helpers ──────────────────────────────────────────────────────────

def _execute_transfer(
    db: Session,
    sender: User,
    recipient: User,
    amount: Decimal,
) -> dict:
    """
    Debit sender and credit recipient with 1% platform fee applied.
    sender is debited the full amount; recipient receives 99%.
    """
    four = Decimal("0.0001")
    fee = (amount * TRANSFER_FEE_RATE).quantize(four, rounding=ROUND_HALF_UP)
    recipient_credit = amount - fee

    ref = f"transfer_{sender.id}_to_{recipient.id}_{int(datetime.utcnow().timestamp())}"

    debit_account(
        db=db,
        user_id=sender.id,
        amount=amount,
        tx_type=TransactionType.TRANSFER_OUT,
        reference_id=ref,
        notes=f"Transfer to @{recipient.username} (1% fee: ${float(fee):.4f})",
    )
    credit_account(
        db=db,
        user_id=recipient.id,
        amount=recipient_credit,
        tx_type=TransactionType.TRANSFER_IN,
        reference_id=ref,
        notes=f"Transfer from @{sender.username}",
    )
    db.commit()

    return {
        "message": f"${float(amount):.2f} transferred to @{recipient.username} (fee: ${float(fee):.4f})",
        "amount_sent": float(amount),
        "fee": float(fee),
        "recipient_received": float(recipient_credit),
        "new_balance": float(get_account_balance(db, sender.id)),
    }


# ── Transfer ──────────────────────────────────────────────────────────────────

@router.post("/transfer")
def transfer_balance(
    body: TransferIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Transfer account balance to another user.

    First transfer to a given recipient triggers an email OTP verification.
    Subsequent transfers to the same recipient execute immediately.
    A 1% platform fee is deducted from the sent amount; recipient receives 99%.
    """
    if body.to_username.lower() == current_user.username.lower():
        raise HTTPException(status_code=400, detail="Cannot transfer to yourself.")

    recipient = db.query(User).filter_by(username=body.to_username).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient user not found.")

    amount = Decimal(str(body.amount))

    tv = (
        db.query(TransferVerification)
        .filter_by(sender_id=current_user.id, recipient_id=recipient.id)
        .first()
    )

    if tv and tv.is_verified:
        # Trusted pair — execute immediately
        return _execute_transfer(db, current_user, recipient, amount)

    # First time to this recipient — send OTP
    otp = _generate_otp()
    if not tv:
        tv = TransferVerification(sender_id=current_user.id, recipient_id=recipient.id)
        db.add(tv)
    tv.pending_otp = otp
    tv.otp_expires_at = datetime.utcnow() + timedelta(minutes=TRANSFER_OTP_EXPIRE_MINUTES)
    db.commit()

    from app.services.email_service import send_transfer_verification_email
    background_tasks.add_task(
        send_transfer_verification_email,
        current_user.email,
        otp,
        recipient.username,
        float(amount),
    )

    return {
        "requires_verification": True,
        "message": (
            f"First transfer to @{recipient.username} requires email verification. "
            f"A code has been sent to your email — use POST /deposit/transfer/verify to confirm."
        ),
    }


@router.post("/transfer/verify")
def verify_transfer(
    body: TransferVerifyIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Confirm the OTP for a first-time transfer and execute it.
    After success the (sender, recipient) pair is permanently trusted.
    """
    if body.to_username.lower() == current_user.username.lower():
        raise HTTPException(status_code=400, detail="Cannot transfer to yourself.")

    recipient = db.query(User).filter_by(username=body.to_username).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient user not found.")

    tv = (
        db.query(TransferVerification)
        .filter_by(sender_id=current_user.id, recipient_id=recipient.id)
        .first()
    )

    if not tv or not tv.pending_otp:
        raise HTTPException(
            status_code=400,
            detail="No pending verification for this recipient. Initiate a transfer first.",
        )
    if tv.pending_otp != body.otp:
        raise HTTPException(status_code=400, detail="Invalid verification code.")
    if not tv.otp_expires_at or datetime.utcnow() > tv.otp_expires_at:
        raise HTTPException(status_code=400, detail="Verification code has expired.")

    # Mark pair as permanently trusted
    tv.is_verified = True
    tv.pending_otp = None
    tv.otp_expires_at = None
    db.commit()

    amount = Decimal(str(body.amount))
    return _execute_transfer(db, current_user, recipient, amount)
