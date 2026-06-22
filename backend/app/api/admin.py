"""
Admin API — restricted to users with is_admin=True.

Endpoints:
  GET  /admin/users                     — list all users
  GET  /admin/users/{user_id}/wallets   — wallets for a specific user
  GET  /admin/transactions              — all transactions (latest 500)
  GET  /admin/withdrawals               — all withdrawal requests
  POST /admin/users/{user_id}/freeze    — deactivate a user
  POST /admin/users/{user_id}/unfreeze  — reactivate a user
  DELETE /admin/users/{user_id}         — permanently delete a user + all their records
  POST /admin/wallet/credit             — manually credit a user's wallet
  POST /admin/wallet/debit              — manually debit a user's wallet

Set is_admin=true directly in the DB for the platform root/admin user.
"""
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.api.deps import get_current_user
from app.core.platform_state import get_platform_setting, set_platform_frozen
from app.core.wallet_ops import (
    ACCOUNT_TIER,
    credit_account,
    credit_wallet,
    debit_account,
    debit_wallet,
    get_account_balance,
    get_total_earnings,
)
from app.database import get_db
from app.models.agent import AgentPurchase
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.models.wallet import Wallet
from app.models.withdrawal import WithdrawalRequest
from app.schemas.agent import (
    AdminTransferIn,
    AdminUserOut,
    AdminWalletCreditIn,
    AdminWalletDebitIn,
    PlatformFreezeIn,
    PlatformStatusOut,
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


@router.get("/users/{user_id}/summary")
def user_summary(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """
    Compact per-user snapshot for the admin user-management dropdown:
      - agents_count: how many agent tiers the user has bought
      - account_balance: spendable account balance
      - revenue_generated: total earnings across all MAIN wallets
    """
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    agents_count = (
        db.query(func.count(AgentPurchase.id))
        .filter(AgentPurchase.user_id == user_id)
        .scalar()
    ) or 0

    return {
        "agents_count": int(agents_count),
        "account_balance": float(get_account_balance(db, user_id)),
        "revenue_generated": float(get_total_earnings(db, user_id)),
    }


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


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """
    Permanently delete a user and all of their records (wallets, transactions,
    purchases, matrix positions, withdrawals, deposits, addresses).

    This is a HARD delete — it removes the user's financial history. Guards:
      • cannot delete your own admin account
      • cannot delete another admin account
    Any downline users are re-parented to the deleted user's sponsor so the
    sponsor tree stays connected.

    Realized platform profit is PRESERVED: the user's SOFTWARE_FEE and
    PLATFORM_PROFIT rows are re-attributed to the admin (not deleted), so the
    platform-profit total is unaffected by the deletion.
    """
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own admin account.")

    user = db.query(User).filter_by(id=user_id).with_for_update().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an admin account.")

    # Lazy imports for the dependent models (kept local to this destructive op)
    from app.models.matrix import MatrixPosition
    from app.models.deposit import Deposit
    from app.models.wallet_address import WalletAddress
    from app.models.transfer_verification import TransferVerification
    from app.models.platform_setting import PlatformSetting

    username = user.username

    try:
        # 1. Re-parent downlines to this user's sponsor (keeps the tree connected)
        db.query(User).filter(User.sponsor_id == user_id).update(
            {User.sponsor_id: user.sponsor_id, User.sponsor_position: None},
            synchronize_session=False,
        )

        # 2. Null out audit references that point at this user
        db.query(PlatformSetting).filter(PlatformSetting.frozen_by == user_id).update(
            {PlatformSetting.frozen_by: None}, synchronize_session=False
        )

        # 3. PRESERVE realized platform profit — the platform already earned these,
        #    so deleting the user must NOT reduce the profit total. Re-attribute the
        #    SOFTWARE_FEE and PLATFORM_PROFIT rows to the admin (kept, still counted),
        #    then delete the user's remaining (user-specific) transactions.
        db.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type.in_(
                [TransactionType.SOFTWARE_FEE, TransactionType.PLATFORM_PROFIT]
            ),
        ).update({Transaction.user_id: admin.id}, synchronize_session=False)

        # 4. Delete all remaining rows owned by this user (children first)
        db.query(TransferVerification).filter(
            (TransferVerification.sender_id == user_id)
            | (TransferVerification.recipient_id == user_id)
        ).delete(synchronize_session=False)
        db.query(WalletAddress).filter(WalletAddress.user_id == user_id).delete(synchronize_session=False)
        db.query(Deposit).filter(Deposit.user_id == user_id).delete(synchronize_session=False)
        db.query(WithdrawalRequest).filter(WithdrawalRequest.user_id == user_id).delete(synchronize_session=False)
        db.query(MatrixPosition).filter(MatrixPosition.user_id == user_id).delete(synchronize_session=False)
        db.query(Transaction).filter(Transaction.user_id == user_id).delete(synchronize_session=False)
        db.query(Wallet).filter(Wallet.user_id == user_id).delete(synchronize_session=False)
        db.query(AgentPurchase).filter(AgentPurchase.user_id == user_id).delete(synchronize_session=False)

        # 5. Finally, the user
        db.delete(user)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("delete_user failed for user_id=%s", user_id)
        raise HTTPException(status_code=500, detail="Failed to delete user — no changes were made.")

    logger.info("ADMIN deleted user id=%s username=%s", user_id, username)
    return {"deleted": True, "user_id": user_id, "username": username}


# ── Platform freeze (global kill switch) ───────────────────────────────────────

@router.get("/platform/status", response_model=PlatformStatusOut)
def platform_freeze_status(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Return the current global freeze state (admin view, with audit details)."""
    return get_platform_setting(db)


@router.post("/platform/freeze", response_model=PlatformStatusOut)
def freeze_platform(
    body: PlatformFreezeIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """
    Engage the global kill switch. While frozen, all regular-user money-movement
    flows (deposit, withdraw, transfer, agent purchase) are blocked with HTTP 423.
    Admin accounts are unaffected. Only an admin can lift the freeze.
    """
    setting = set_platform_frozen(db, frozen=True, admin_id=admin.id, reason=body.reason)
    logger.warning(
        "PLATFORM frozen: by admin_id=%d username=%s reason=%s",
        admin.id, admin.username, body.reason or "(none)",
    )
    return setting


@router.post("/platform/unfreeze", response_model=PlatformStatusOut)
def unfreeze_platform(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Release the global kill switch — user flows resume immediately."""
    setting = set_platform_frozen(db, frozen=False, admin_id=admin.id)
    logger.warning(
        "PLATFORM unfrozen: by admin_id=%d username=%s", admin.id, admin.username,
    )
    return setting


# ── Treasury (admin transfer) ────────────────────────────────────────────────────
#
# Admin-only flow, fully separate from the user deposit/transfer/withdraw
# endpoints. The admin sends treasury balance (their own account balance) to any
# user by username. No fees, no OTP — credited in full instantly.

@router.get("/treasury/balance")
def treasury_balance(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Return the admin's own account balance (the treasury pool)."""
    return {"account_balance": float(get_account_balance(db, admin.id))}


@router.get("/treasury/summary")
def treasury_summary(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """
    Treasury overview for the admin:
      - account_balance: current spendable treasury balance (admin's account wallet)
      - total_generated: lifetime funds minted via Generate
      - total_sent: lifetime funds sent to users via the treasury Transfer
      - total_invested: platform-wide total spent by all users buying agent tiers
        (this is what drives the revenue engine)
      - total_deposited: platform-wide total deposited into account balances
    """
    def _sum(tx_type: TransactionType) -> float:
        total = (
            db.query(func.coalesce(func.sum(Transaction.amount), 0))
            .filter(Transaction.user_id == admin.id, Transaction.transaction_type == tx_type)
            .scalar()
        )
        return float(total or 0)

    def _sum_all(tx_type: TransactionType) -> float:
        total = (
            db.query(func.coalesce(func.sum(Transaction.amount), 0))
            .filter(Transaction.transaction_type == tx_type)
            .scalar()
        )
        return float(total or 0)

    # Realized platform profit = software fees (10% of every payout) + all other
    # explicitly-ledgered profit (matrix-level residuals, core-retained when a buyer
    # has no sponsor, and 1% transfer fees).
    platform_profit = (
        _sum_all(TransactionType.SOFTWARE_FEE)
        + _sum_all(TransactionType.PLATFORM_PROFIT)
    )

    return {
        "account_balance": float(get_account_balance(db, admin.id)),
        "total_generated": _sum(TransactionType.ADMIN_GENERATE),
        "total_sent": _sum(TransactionType.TRANSFER_OUT),
        "total_invested": _sum_all(TransactionType.AGENT_PURCHASE),
        "total_deposited": _sum_all(TransactionType.DEPOSIT),
        "platform_profit": platform_profit,
    }


@router.post("/transfer")
def treasury_transfer(
    body: AdminTransferIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """
    Send funds from the admin's treasury (account balance) to a user's account
    balance, identified by username. No fee, no OTP — credited in full instantly.
    """
    if body.to_username.lower() == admin.username.lower():
        raise HTTPException(status_code=400, detail="Cannot transfer to your own admin account.")

    recipient = db.query(User).filter_by(username=body.to_username).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient user not found.")

    amount = Decimal(str(body.amount))
    ref = f"admin_transfer_{admin.id}_to_{recipient.id}"

    # Debit the admin's treasury (raises 400 if insufficient) then credit the user in full.
    debit_account(
        db=db,
        user_id=admin.id,
        amount=amount,
        tx_type=TransactionType.TRANSFER_OUT,
        reference_id=ref,
        notes=f"Admin transfer to @{recipient.username}",
    )
    credit_account(
        db=db,
        user_id=recipient.id,
        amount=amount,
        tx_type=TransactionType.TRANSFER_IN,
        reference_id=ref,
        notes=f"Received from platform admin",
    )
    db.commit()

    logger.warning(
        "TREASURY transfer: admin_id=%d -> recipient_id=%d (@%s) amount=$%.2f",
        admin.id, recipient.id, recipient.username, float(amount),
    )
    return {
        "message": f"${float(amount):.2f} sent to @{recipient.username}",
        "amount": float(amount),
        "recipient_username": recipient.username,
        "account_balance": float(get_account_balance(db, admin.id)),
    }


@router.get("/treasury/activity", response_model=list[TransactionOut])
def treasury_activity(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Recent treasury actions (generated funds + transfers sent) by this admin."""
    return (
        db.query(Transaction)
        .filter(
            Transaction.user_id == admin.id,
            Transaction.transaction_type.in_(
                [TransactionType.ADMIN_GENERATE, TransactionType.TRANSFER_OUT]
            ),
        )
        .order_by(Transaction.created_at.desc())
        .limit(50)
        .all()
    )


# ── Transactions ──────────────────────────────────────────────────────────────

@router.get("/transactions")
def all_transactions(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """
    Return the latest 500 transactions across all users, each with the owning
    user's username resolved (so the admin sees who, not just a user id).
    """
    txns = (
        db.query(Transaction)
        .order_by(Transaction.created_at.desc())
        .limit(500)
        .all()
    )
    user_ids = {t.user_id for t in txns}
    usernames = dict(
        db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()
    ) if user_ids else {}

    return [
        {
            "id": t.id,
            "user_id": t.user_id,
            "username": usernames.get(t.user_id),
            "agent_tier": t.agent_tier,
            "transaction_type": t.transaction_type.value,
            "amount": float(t.amount),
            "notes": t.notes,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in txns
    ]


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
