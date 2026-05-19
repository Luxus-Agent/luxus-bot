import random
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.wallet_ops import debit_wallet
from app.database import get_db
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet, WalletType
from app.models.wallet_address import WalletAddress
from app.models.withdrawal import WithdrawalRequest, WithdrawalStatus
from app.schemas.agent import (
    TransactionOut,
    WalletAddressIn,
    WalletAddressOut,
    WalletAddressVerifyIn,
    WalletOut,
    WithdrawalIn,
    WithdrawalOut,
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
        raise HTTPException(status_code=400, detail="Invalid verification code.")
    if not wa.otp_expires_at or datetime.utcnow() > wa.otp_expires_at:
        raise HTTPException(status_code=400, detail="Verification code has expired.")

    wa.is_verified = True
    wa.pending_otp = None
    wa.otp_expires_at = None
    db.commit()
    db.refresh(wa)

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
    db.delete(wa)
    db.commit()
    return {"message": "Address removed."}


# ── Withdrawal ────────────────────────────────────────────────────────────────

@router.post("/withdraw", response_model=WithdrawalOut)
async def request_withdrawal(
    body: WithdrawalIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Request a USDT (BEP-20) withdrawal from the user's MAIN wallet.
    The wallet_address must be pre-registered and email-verified via POST /wallet/address.
    Funds are deducted immediately and the payout is dispatched instantly via NOWPayments.
    """
    from app.workers.tasks import process_withdrawal

    # Require the address to be pre-verified
    verified_address = (
        db.query(WalletAddress)
        .filter_by(user_id=current_user.id, address=body.wallet_address, is_verified=True)
        .first()
    )
    if not verified_address:
        raise HTTPException(
            status_code=400,
            detail=(
                "Withdrawal address not verified. "
                "Register and verify it first via POST /wallet/address then POST /wallet/address/verify."
            ),
        )

    amount = Decimal(str(body.amount))

    wallet = (
        db.query(Wallet)
        .filter_by(
            user_id=current_user.id,
            agent_tier=body.agent_tier,
            wallet_type=WalletType.MAIN,
        )
        .first()
    )
    current_balance = Decimal(str(wallet.balance)) if wallet else Decimal("0")
    if current_balance < amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance. Available: ${current_balance:.4f}, Requested: ${amount:.4f}",
        )

    scheduled_for = datetime.utcnow()

    withdrawal = WithdrawalRequest(
        user_id=current_user.id,
        agent_tier=body.agent_tier,
        amount=amount,
        wallet_address=body.wallet_address,
        status=WithdrawalStatus.PENDING,
        scheduled_for=scheduled_for,
    )
    db.add(withdrawal)
    db.flush()

    debit_wallet(
        db=db,
        user_id=current_user.id,
        agent_tier=body.agent_tier,
        amount=amount,
        reference_id=f"withdrawal_{withdrawal.id}",
        notes=f"Withdrawal to {body.wallet_address[:10]}… processing now",
    )

    db.commit()
    db.refresh(withdrawal)

    process_withdrawal.delay(withdrawal.id)

    from app.services.email_service import send_withdrawal_requested_email
    background_tasks.add_task(
        send_withdrawal_requested_email,
        current_user.email,
        current_user.username,
        float(amount),
        body.wallet_address,
        scheduled_for.strftime("%Y-%m-%d %H:%M"),
    )

    return withdrawal


@router.get("/withdrawals", response_model=list[WithdrawalOut])
def get_withdrawals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(WithdrawalRequest)
        .filter_by(user_id=current_user.id)
        .order_by(WithdrawalRequest.created_at.desc())
        .limit(100)
        .all()
    )
