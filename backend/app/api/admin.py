"""
Admin API — restricted to users with is_admin=True.

Endpoints:
  GET  /admin/users                     — list all users
  GET  /admin/users/{user_id}/wallets   — wallets for a specific user
  GET  /admin/transactions              — all transactions (latest 500)
  GET  /admin/withdrawals               — all withdrawal requests
  POST /admin/users/{user_id}/freeze    — deactivate a user
  POST /admin/users/{user_id}/unfreeze  — reactivate a user
  POST /admin/wallet/credit             — manually credit a user's wallet
  POST /admin/wallet/debit              — manually debit a user's wallet

Set is_admin=true directly in the DB for the platform root/admin user.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.wallet_ops import credit_wallet, debit_wallet
from app.database import get_db
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.models.wallet import Wallet
from app.models.withdrawal import WithdrawalRequest
from app.schemas.agent import (
    AdminUserOut,
    AdminWalletCreditIn,
    AdminWalletDebitIn,
    TransactionOut,
    WalletOut,
    WithdrawalOut,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Return all registered users with sponsor username resolved."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "is_active": u.is_active,
            "is_admin": u.is_admin,
            "sponsor_id": u.sponsor_id,
            "sponsor_username": u.sponsor.username if u.sponsor else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.get("/users/{user_id}/wallets", response_model=list[WalletOut])
def user_wallets(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Return all wallet balances for a specific user."""
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return db.query(Wallet).filter_by(user_id=user_id).all()


@router.post("/users/{user_id}/freeze", response_model=AdminUserOut)
def freeze_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Deactivate a user account (blocks login and ProActive income routing)."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot freeze your own admin account.")
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.is_active = False
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/unfreeze", response_model=AdminUserOut)
def unfreeze_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Reactivate a previously frozen user account."""
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


# ── Transactions ──────────────────────────────────────────────────────────────

@router.get("/transactions", response_model=list[TransactionOut])
def all_transactions(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Return the latest 500 transactions across all users."""
    return (
        db.query(Transaction)
        .order_by(Transaction.created_at.desc())
        .limit(500)
        .all()
    )


# ── Withdrawals ───────────────────────────────────────────────────────────────

@router.get("/withdrawals", response_model=list[WithdrawalOut])
def all_withdrawals(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Return all withdrawal requests across all users, newest first."""
    return (
        db.query(WithdrawalRequest)
        .order_by(WithdrawalRequest.created_at.desc())
        .limit(500)
        .all()
    )


# ── Wallet operations ─────────────────────────────────────────────────────────

@router.post("/wallet/credit")
def admin_credit_wallet(
    body: AdminWalletCreditIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """
    Manually credit a user's MAIN wallet (with 10% repurchase split applied).
    Records as PROPORTION_PAYOUT for audit traceability.
    """
    user = db.query(User).filter_by(id=body.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    credit_wallet(
        db=db,
        user_id=body.user_id,
        agent_tier=body.agent_tier,
        gross_amount=Decimal(str(body.amount)),
        tx_type=TransactionType.PROPORTION_PAYOUT,
        reference_id=f"admin_credit_{admin.id}",
        notes=body.notes or f"Admin manual credit by #{admin.id}",
    )
    db.commit()

    return {"message": f"${float(body.amount):.4f} credited to user #{body.user_id} tier {body.agent_tier}"}


@router.post("/wallet/debit")
def admin_debit_wallet(
    body: AdminWalletDebitIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """
    Manually debit a user's MAIN wallet.
    Raises 400 if balance is insufficient.
    """
    user = db.query(User).filter_by(id=body.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    debit_wallet(
        db=db,
        user_id=body.user_id,
        agent_tier=body.agent_tier,
        amount=Decimal(str(body.amount)),
        reference_id=f"admin_debit_{admin.id}",
        notes=body.notes or f"Admin manual debit by #{admin.id}",
    )
    db.commit()

    return {"message": f"${float(body.amount):.4f} debited from user #{body.user_id} tier {body.agent_tier}"}
