"""
Deposit & Transfer endpoints.

Deposit flow:
  POST /deposit          → create a pending Deposit + NOWPayments invoice
  GET  /deposit          → list user's deposits
  GET  /deposit/balance  → current account balance

Transfer flow:
  POST /transfer         → send account balance to another user by username
"""
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.wallet_ops import credit_account, debit_account, get_account_balance, ACCOUNT_TIER
from app.database import get_db
from app.models.deposit import Deposit
from app.models.transaction import TransactionType
from app.models.user import User
from app.schemas.agent import DepositIn, DepositOut, DepositRefundIn, TransferIn

router = APIRouter(prefix="/deposit", tags=["deposit"])


@router.get("/balance")
def account_balance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current account balance available for purchasing agents."""
    balance = get_account_balance(db, current_user.id)
    return {"account_balance": float(balance)}


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

    # Deduct balance first (raises 400 if somehow insufficient)
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
        # Refund failed — restore the balance
        from app.core.wallet_ops import credit_account
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


@router.post("/transfer")
def transfer_balance(
    body: TransferIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Transfer account balance from the current user to another user by username.
    Both debit and credit happen atomically.
    """
    if body.to_username.lower() == current_user.username.lower():
        raise HTTPException(status_code=400, detail="Cannot transfer to yourself.")

    recipient = db.query(User).filter_by(username=body.to_username).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient user not found.")

    amount = Decimal(str(body.amount))
    ref = f"transfer_{current_user.id}_to_{recipient.id}"

    # Debit sender — raises 400 if insufficient
    debit_account(
        db=db,
        user_id=current_user.id,
        amount=amount,
        tx_type=TransactionType.TRANSFER_OUT,
        reference_id=ref,
        notes=f"Transfer to @{recipient.username}",
    )

    # Credit recipient
    credit_account(
        db=db,
        user_id=recipient.id,
        amount=amount,
        tx_type=TransactionType.TRANSFER_IN,
        reference_id=ref,
        notes=f"Transfer from @{current_user.username}",
    )

    db.commit()

    return {
        "message": f"${float(amount):.2f} transferred to @{recipient.username}",
        "new_balance": float(get_account_balance(db, current_user.id)),
    }
