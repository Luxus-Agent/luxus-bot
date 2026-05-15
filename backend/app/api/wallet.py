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
from app.models.withdrawal import WithdrawalRequest, WithdrawalStatus
from app.schemas.agent import TransactionOut, WalletOut, WithdrawalIn, WithdrawalOut

router = APIRouter(prefix="/wallet", tags=["wallet"])

WITHDRAWAL_HOLD_HOURS = 24


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


@router.post("/withdraw", response_model=WithdrawalOut)
async def request_withdrawal(
    body: WithdrawalIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Request a USDT (BEP-20) withdrawal from the user's MAIN wallet.
    Funds are deducted immediately and the payout is sent after 24 hours.
    """
    from app.workers.tasks import process_withdrawal

    amount = Decimal(str(body.amount))

    # Check balance before deducting
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

    scheduled_for = datetime.utcnow() + timedelta(hours=WITHDRAWAL_HOLD_HOURS)

    withdrawal = WithdrawalRequest(
        user_id=current_user.id,
        agent_tier=body.agent_tier,
        amount=amount,
        wallet_address=body.wallet_address,
        status=WithdrawalStatus.PENDING,
        scheduled_for=scheduled_for,
    )
    db.add(withdrawal)
    db.flush()  # get withdrawal.id before debit_wallet call

    debit_wallet(
        db=db,
        user_id=current_user.id,
        agent_tier=body.agent_tier,
        amount=amount,
        reference_id=f"withdrawal_{withdrawal.id}",
        notes=f"Withdrawal to {body.wallet_address[:10]}… scheduled for {scheduled_for.strftime('%Y-%m-%d %H:%M')} UTC",
    )

    db.commit()
    db.refresh(withdrawal)

    # Queue the payout to fire after 24h
    process_withdrawal.apply_async(args=[withdrawal.id], countdown=WITHDRAWAL_HOLD_HOURS * 3600)

    # Send confirmation email
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
