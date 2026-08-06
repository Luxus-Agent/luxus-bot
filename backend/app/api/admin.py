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
from app.core.core_preview import get_downline_odd_even, simulate_core_split
from app.core.matrix_engine import PAYOUT_CONFIG, tier_multiplier
from app.core.matrix_flow import get_queue_flow
from app.core.platform_state import ensure_platform_active, get_platform_setting, set_platform_frozen
from app.core.user_lookup import get_user_by_username
from app.core.wallet_ops import (
    ACCOUNT_TIER,
    REPURCHASE_RATE,
    SOFTWARE_FEE_RATE,
    credit_account,
    credit_wallet,
    debit_account,
    debit_wallet,
    get_account_balance,
    get_ledger_earnings,
    resolve_tx_hashes,
)
from app.database import get_db
from app.models.agent import AgentPurchase
from app.models.matrix import MatrixLevelQueue, MatrixQueueSlot, SystemType
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.agent import (
    AdminTransferIn,
    AdminUserOut,
    AdminWalletCreditIn,
    AdminWalletDebitIn,
    PlatformFreezeIn,
    PlatformStatusOut,
    TransactionOut,
    WalletOut,
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
      - wallet_address: registered BEP-20 payout address (used for Core routing +
        on-chain settlement) — NOT `account_balance`, which is the legacy
        deposit-first account wallet and is always $0 on the on-chain-only rail
        (there's no deposit path left to fund it), so it isn't useful to show here
      - revenue_generated: lifetime GROSS income from the ledger (Core/Stream/
        Boost/Sponsor) — same figure as the user's own "Total Earnings"
        (core/wallet_ops.get_ledger_earnings), before the 70/20/10 wallet split
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
        "wallet_address": user.wallet_address,
        "revenue_generated": float(get_ledger_earnings(db, user_id)),
    }


@router.post("/users/{user_id}/freeze", response_model=AdminUserOut)
def freeze_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Deactivate a user account (blocks login and Core income routing)."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot freeze your own admin account.")
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot freeze an admin account.")
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
    platform-profit total is unaffected by the deletion. Any unconsumed
    REPURCHASE reserve balance is booked as platform profit too (per client
    spec: reserve that never reaches its repurchase threshold "will go to the
    platform") — otherwise that held balance would simply vanish along with
    the user's Wallet rows, unaccounted for anywhere.
    """
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own admin account.")

    user = db.query(User).filter_by(id=user_id).with_for_update().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an admin account.")

    # Lazy imports for the dependent models (kept local to this destructive op)
    from app.models.wallet_address import WalletAddress
    from app.models.platform_setting import PlatformSetting
    from app.models.matrix import MatrixPendingPayout, MatrixPosition, MatrixQueueSlot
    from app.models.pack_purchase import PackPurchase
    from app.models.wallet import WalletType

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

        # 3b. Any REPURCHASE reserve this user never accumulated enough to spend
        #     is forfeited to platform profit (client spec: unreached reserve
        #     "will go to the platform") rather than silently disappearing when
        #     their Wallet rows are deleted below.
        forfeited_reserve = (
            db.query(func.coalesce(func.sum(Wallet.balance), 0))
            .filter(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.REPURCHASE)
            .scalar()
        )
        forfeited_reserve = Decimal(str(forfeited_reserve or 0))
        if forfeited_reserve > 0:
            db.add(Transaction(
                user_id=admin.id,
                agent_tier=ACCOUNT_TIER,  # spans whichever tiers held reserve — not tier-specific
                transaction_type=TransactionType.PLATFORM_PROFIT,
                amount=forfeited_reserve,
                notes=f"Forfeited repurchase reserve — @{username} deleted",
            ))

        # 4. Delete all remaining rows owned by this user (children first).
        #    Matrix queue slots are safe to remove outright: matrix_engine's
        #    level-completion walk already treats a missing slot at head_position
        #    as a no-op skip (defensive `if head_slot is None: continue`), so a
        #    deleted user's position is simply skipped when its turn comes,
        #    without disrupting the shared queue for everyone else.
        db.query(MatrixPendingPayout).filter(
            MatrixPendingPayout.owner_user_id == user_id
        ).delete(synchronize_session=False)
        db.query(MatrixQueueSlot).filter(MatrixQueueSlot.user_id == user_id).delete(synchronize_session=False)
        db.query(MatrixPosition).filter(MatrixPosition.user_id == user_id).delete(synchronize_session=False)
        db.query(PackPurchase).filter(PackPurchase.buyer_id == user_id).delete(synchronize_session=False)
        db.query(WalletAddress).filter(WalletAddress.user_id == user_id).delete(synchronize_session=False)
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
    # has no sponsor, and 1% transfer fees). Admin income (the 1% Boost cut) is
    # tracked separately below — it's routed to its own ADMIN_INCOME_WALLET, not
    # pooled with PLATFORM_FEE_WALLET's profit, so it's a distinct figure, not
    # folded into this total.
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
        "admin_income": _sum_all(TransactionType.ADMIN_INCOME),
    }


@router.get("/treasury/onchain-wallets")
def treasury_onchain_wallets(
    _: User = Depends(get_admin_user),
):
    """
    Live on-chain balances (USDT + native BNB gas) for the three platform-
    controlled wallets, read directly from the chain — these addresses have no
    internal DB row, so this is the only way to see what's actually sitting in
    them. Read-only, never moves funds.

    REPURCHASE_RESERVE_WALLET pays its own gas for the auto-repurchase
    settlement broadcast (see core/onchain.send_repurchase_settlement) — its BNB
    balance is the one worth watching so that broadcast doesn't silently start
    failing for lack of gas.

    ADMIN_INCOME_WALLET and REPURCHASE_RESERVE_WALLET both fall back to
    PLATFORM_FEE_WALLET when unset (config.py) — when that happens they'll
    naturally report the same address/balances as Platform Fee; the frontend
    can de-duplicate on `address`.
    """
    from app.config import settings
    from app.core.onchain import get_wallet_onchain_balances

    def _entry(label: str, key: str, address: str) -> dict:
        result = get_wallet_onchain_balances(address)
        return {
            "key": key,
            "label": label,
            "address": result["address"],
            "usdt_balance": float(result["usdt"]) if result["usdt"] is not None else None,
            "bnb_balance": float(result["bnb"]) if result["bnb"] is not None else None,
            "error": result["error"],
        }

    return {
        "wallets": [
            _entry("Platform Fee Wallet", "platform_fee", settings.PLATFORM_FEE_WALLET),
            _entry("Admin Income Wallet", "admin_income", settings.admin_income_wallet),
            _entry("Repurchase Reserve Wallet", "repurchase_reserve", settings.repurchase_reserve_wallet),
        ],
    }


@router.get("/metrics")
def platform_metrics(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """
    Platform-wide revenue-engine + auto-repurchase metrics for the admin overview.

    All figures are summed live from the transaction ledger / wallet balances:

      revenue:
        - core_income / stream_payout / boost_payout / sponsor_share: total
          GROSS commissions earned via each engine (before the platform fee is
          subtracted — per client spec, these ledger figures always show the full
          amount, matching per-user "Total Earnings")
        - total_gross_commissions: sum of the four above
        - total_credited_to_wallets: the exact $ currently sitting across every
          user's internal MAIN wallet (read directly from Wallet balances —
          ground truth, not an estimate). Stream/Boost/sponsor income that
          settled instantly on-chain (see total_settled_onchain below) never
          touches this figure at all; only whatever stayed internal does
          (feature disabled, no wallet address on file, or a broadcast failure
          — matrix_runtime._settle_or_credit's fallback path)
        - total_settled_onchain: total Stream/Boost/sponsor gross that settled
          instantly on-chain straight to the recipient's own wallet
          (Transaction.tx_hash IS NOT NULL — matrix_runtime._settle_or_credit,
          disabled unless PLATFORM_FEE_SIGNER_PRIVATE_KEY is set), at each
          row's own on-chain share (70% Stream, 90% Boost's own payout, 100%
          any sponsor-share bonus — sponsor share is never fee-reduced)
        - software_fees: 10% platform fee collected across every Stream
          payout and Core commission, plus 10% off every Boost payout's own
          wallet_amount (Boost's sponsor-share bonus contributes none — it's
          paid in addition, unreduced)
      repurchase:
        - count / volume: number and $ of auto-repurchases executed (repurchase_buy)
        - platform_fee: flat platform fee collected on those repurchases
        - reserve_held: total 20% reserve currently sitting across all REPURCHASE
          wallets (a platform-held liability awaiting the next auto-repurchase)
    """
    from app.models.wallet import WalletType

    def _sum_all(tx_type: TransactionType) -> float:
        total = (
            db.query(func.coalesce(func.sum(Transaction.amount), 0))
            .filter(Transaction.transaction_type == tx_type)
            .scalar()
        )
        return float(total or 0)

    core = _sum_all(TransactionType.CORE_INCOME)
    stream = _sum_all(TransactionType.STREAM_PAYOUT)
    boost = _sum_all(TransactionType.BOOST_PAYOUT)
    sponsor = _sum_all(TransactionType.SPONSOR_MILESTONE_INCOME)
    total_gross_commissions = round(core + stream + boost + sponsor, 4)

    def _sum_sponsor_like(pattern: str, settled: bool | None = None) -> float:
        q = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.transaction_type == TransactionType.SPONSOR_MILESTONE_INCOME,
            Transaction.reference_id.like(pattern),
        )
        if settled is not None:
            q = q.filter(Transaction.tx_hash.isnot(None) if settled else Transaction.tx_hash.is_(None))
        return float(q.scalar() or 0)

    def _sum_settled(tx_type: TransactionType) -> float:
        total = (
            db.query(func.coalesce(func.sum(Transaction.amount), 0))
            .filter(Transaction.transaction_type == tx_type, Transaction.tx_hash.isnot(None))
            .scalar()
        )
        return float(total or 0)

    # total_credited_to_wallets: exact, live — read directly off Wallet.MAIN
    # balances rather than estimated from gross×rate. Correct regardless of
    # settlement path: rows that settled instantly on-chain (tx_hash IS NOT
    # NULL) never touch MAIN at all; only rows that stayed internal do.
    total_credited_to_wallets = round(float(
        db.query(func.coalesce(func.sum(Wallet.balance), 0))
        .filter(Wallet.wallet_type == WalletType.MAIN)
        .scalar() or 0
    ), 4)

    # total_settled_onchain: Stream sends 70% on-chain (mirrors Core exactly),
    # Boost sends 90% of its OWN payout (10% software fee stays internal —
    # see wallet_ops.credit_boost_wallet / mirror_onchain_boost_split) but the
    # full 100% of any sponsor-share bonus (never fee-reduced) — same rates
    # matrix_runtime._settle_or_credit itself broadcasts. Sponsor share
    # follows its SOURCE system the same way; SPONSOR_MILESTONE_INCOME has no
    # source column, so rows are told apart by the reference_id prefix
    # matrix_runtime._credit_row_sponsor tags them with.
    stream_rate = 1 - float(REPURCHASE_RATE) - float(SOFTWARE_FEE_RATE)
    boost_rate = 1 - float(SOFTWARE_FEE_RATE)
    sponsor_boost_settled = _sum_sponsor_like("sponsor_share_boost_%", settled=True)
    sponsor_stream_settled = _sum_sponsor_like("sponsor_share_stream_%", settled=True)
    total_settled_onchain = round(
        _sum_settled(TransactionType.STREAM_PAYOUT) * stream_rate
        + _sum_settled(TransactionType.BOOST_PAYOUT) * boost_rate
        + sponsor_stream_settled * stream_rate
        + sponsor_boost_settled,
        4,
    )

    repurchase_count = (
        db.query(func.count(Transaction.id))
        .filter(Transaction.transaction_type == TransactionType.REPURCHASE_BUY)
        .scalar()
    ) or 0

    reserve_held = (
        db.query(func.coalesce(func.sum(Wallet.balance), 0))
        .filter(Wallet.wallet_type == WalletType.REPURCHASE)
        .scalar()
    )

    return {
        "revenue": {
            "core_income": core,
            "stream_payout": stream,
            "boost_payout": boost,
            "sponsor_share": sponsor,
            "total_gross_commissions": total_gross_commissions,
            "total_credited_to_wallets": total_credited_to_wallets,
            "total_settled_onchain": total_settled_onchain,
            "software_fees": _sum_all(TransactionType.SOFTWARE_FEE),
        },
        "repurchase": {
            "count": int(repurchase_count),
            "volume": _sum_all(TransactionType.REPURCHASE_BUY),
            "platform_fee": _sum_all(TransactionType.REPURCHASE_GAS),
            "reserve_held": float(reserve_held or 0),
        },
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
    ensure_platform_active(db)

    if body.to_username.lower() == admin.username.lower():
        raise HTTPException(status_code=400, detail="Cannot transfer to your own admin account.")

    recipient = get_user_by_username(db, body.to_username)
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
    tx_hashes = resolve_tx_hashes(db, {t.reference_id for t in txns if t.reference_id})

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
            # Prefer the row's own tx_hash (Stream/Boost/sponsor settled
            # instantly on-chain via matrix_runtime._settle_or_credit) — fall
            # back to the PackPurchase/PayoutBatch resolver for Core / member-
            # payout rows, which settle as part of a shared multisender tx.
            "tx_hash": t.tx_hash or tx_hashes.get(t.reference_id),
        }
        for t in txns
    ]


# ── Wallet operations ─────────────────────────────────────────────────────────

@router.post("/wallet/credit")
def admin_credit_wallet(
    body: AdminWalletCreditIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """
    Manually credit a user's MAIN wallet (with the 70/20/10 split applied).
    Records as ADMIN_CREDIT for audit traceability.
    """
    ensure_platform_active(db)

    user = db.query(User).filter_by(id=body.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    credit_wallet(
        db=db,
        user_id=body.user_id,
        agent_tier=body.agent_tier,
        gross_amount=Decimal(str(body.amount)),
        tx_type=TransactionType.ADMIN_CREDIT,
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
    ensure_platform_active(db)

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


# ── Revenue Engine Visualization (Core / Stream / Boost) ─────────────────────
#
# Read-only endpoints powering the admin "Revenue Engines" dashboard page:
# Stream/Boost queue fill-state + contents, and a Core compression/odd-even
# routing simulator. None of these mutate any persisted state.

@router.get("/matrix/overview")
def matrix_overview(
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """
    Fill-state snapshot of every Stream (per-tier 1-4) and Boost (global,
    tier 1) level-queue — percent-to-next-payout, wallet/re-entry amounts,
    lifetime completions. Missing queues (never touched yet) report as empty.
    """
    rows = db.query(MatrixLevelQueue).all()
    by_key = {(r.agent_tier, r.system_type, r.level): r for r in rows}

    def level_state(system_type: SystemType, tier: int, level: int) -> dict:
        cfg = PAYOUT_CONFIG[system_type][level]
        row = by_key.get((tier, system_type, level))
        head = row.head_position if row else 1
        next_pos = row.next_position if row else 1
        completions = head - 1
        required_total = 1 + cfg.threshold * (completions + 1)
        total_joined = next_pos - 1
        filled = min(cfg.threshold, max(0, cfg.threshold - (required_total - total_joined)))
        multiplier = tier_multiplier(tier)
        return {
            "level": level,
            "threshold": cfg.threshold,
            "filled": filled,
            "percent": round(100 * filled / cfg.threshold, 1),
            "completions": completions,
            "total_joined": total_joined,
            "wallet_amount": float(cfg.wallet_amount * multiplier),
            "reentry_amount": float(cfg.reentry_amount * multiplier),
            "reentry_count": cfg.reentry_count,
            "sponsor_on_completion": float(cfg.sponsor_on_completion * multiplier),
        }

    return {
        "stream": {
            str(tier): [level_state(SystemType.STREAM, tier, lvl) for lvl in (1, 2, 3)]
            for tier in (1, 2, 3, 4)
        },
        "boost": {"1": [level_state(SystemType.BOOST, 1, lvl) for lvl in (1, 2, 3)]},
    }


@router.get("/matrix/queue-slots")
def matrix_queue_slots(
    system_type: str,
    tier: int,
    level: int,
    limit: int = 40,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """
    Ordered queue contents for one (system, tier, level) starting from the
    current head position — the actual member list behind the "queue format"
    visualization (who's occupying each position, which are re-entries).
    """
    try:
        sys_enum = SystemType(system_type.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail="system_type must be 'stream' or 'boost'.")
    if level not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="level must be 1, 2, or 3.")
    if sys_enum == SystemType.BOOST:
        tier = 1  # Boost always runs a single global queue on tier 1.
    limit = max(1, min(limit, 100))

    queue = db.query(MatrixLevelQueue).filter_by(agent_tier=tier, system_type=sys_enum, level=level).first()
    head = queue.head_position if queue else 1
    next_pos = queue.next_position if queue else 1

    slots = (
        db.query(MatrixQueueSlot)
        .filter(
            MatrixQueueSlot.agent_tier == tier,
            MatrixQueueSlot.system_type == sys_enum,
            MatrixQueueSlot.level == level,
            MatrixQueueSlot.position_number >= head,
        )
        .order_by(MatrixQueueSlot.position_number)
        .limit(limit)
        .all()
    )
    user_ids = {s.user_id for s in slots}
    usernames = dict(
        db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()
    ) if user_ids else {}

    return {
        "system_type": sys_enum.value,
        "agent_tier": tier,
        "level": level,
        "threshold": PAYOUT_CONFIG[sys_enum][level].threshold,
        "head_position": head,
        "next_position": next_pos,
        "slots": [
            {
                "position_number": s.position_number,
                "username": usernames.get(s.user_id, f"user{s.user_id}"),
                "is_dummy": s.is_dummy,
                "is_head": s.position_number == head,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in slots
        ],
    }


@router.get("/matrix/queue-flow")
def matrix_queue_flow(
    system_type: str,
    tier: int,
    level: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """
    Full queue-flow diagram data for one (system, tier, level): every position
    from #1 onward, in true arrival order, with each paying position linked to
    the re-entry slot(s) it spawned — the client's "How matrix queue work?"
    single-stack-with-arcs picture, not the level-card summary view.
    """
    try:
        sys_enum = SystemType(system_type.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail="system_type must be 'stream' or 'boost'.")
    if level not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="level must be 1, 2, or 3.")
    if sys_enum == SystemType.BOOST:
        tier = 1  # Boost always runs a single global queue on tier 1.
    return get_queue_flow(db, sys_enum, tier, level)


@router.get("/core/simulate")
def core_simulate(
    username: str,
    tier: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """
    Read-only preview of the Core 60% compression + odd/even split if
    `username` bought `tier` right now (admin can inspect any user).
    """
    if tier not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="tier must be 1-4.")
    buyer = get_user_by_username(db, username)
    if not buyer:
        raise HTTPException(status_code=404, detail="User not found.")
    return simulate_core_split(db, buyer, tier)


@router.get("/core/downline")
def core_downline(
    username: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """
    Read-only: `username`'s direct downline split into a left/odd and right/even
    column by join order (1st, 3rd, 5th... referral on the left; 2nd, 4th... on
    the right) — the Core-agent odd/even table view.
    """
    sponsor = get_user_by_username(db, username)
    if not sponsor:
        raise HTTPException(status_code=404, detail="User not found.")
    return get_downline_odd_even(db, sponsor)
