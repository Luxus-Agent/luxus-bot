from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.wallet import Wallet, WalletType
from app.models.transaction import Transaction, TransactionType

REPURCHASE_RATE = Decimal("0.10")
ACCOUNT_TIER = 0  # Sentinel agent_tier for the platform account balance wallet


def get_or_create_wallet(db: Session, user_id: int, agent_tier: int, wallet_type: WalletType) -> Wallet:
    wallet = (
        db.query(Wallet)
        .filter_by(user_id=user_id, agent_tier=agent_tier, wallet_type=wallet_type)
        .with_for_update()
        .first()
    )
    if not wallet:
        wallet = Wallet(user_id=user_id, agent_tier=agent_tier, wallet_type=wallet_type, balance=0)
        db.add(wallet)
        db.flush()
    return wallet


def credit_wallet(
    db: Session,
    user_id: int,
    agent_tier: int,
    gross_amount: Decimal,
    tx_type: TransactionType,
    reference_id: str | None = None,
    notes: str | None = None,
) -> None:
    """
    Credit gross_amount to a user's wallet for the given agent tier.
    10% is automatically held in the repurchase reserve; 90% goes to the main wallet.
    Both movements are recorded in the transaction ledger.
    """
    four_places = Decimal("0.0001")
    repurchase = (gross_amount * REPURCHASE_RATE).quantize(four_places, rounding=ROUND_HALF_UP)
    main_credit = gross_amount - repurchase

    main_wallet = get_or_create_wallet(db, user_id, agent_tier, WalletType.MAIN)
    main_wallet.balance = Decimal(str(main_wallet.balance)) + main_credit

    repurchase_wallet = get_or_create_wallet(db, user_id, agent_tier, WalletType.REPURCHASE)
    repurchase_wallet.balance = Decimal(str(repurchase_wallet.balance)) + repurchase

    db.add(Transaction(
        user_id=user_id,
        agent_tier=agent_tier,
        transaction_type=tx_type,
        amount=main_credit,
        reference_id=reference_id,
        notes=notes,
    ))
    db.add(Transaction(
        user_id=user_id,
        agent_tier=agent_tier,
        transaction_type=TransactionType.REPURCHASE_HOLD,
        amount=repurchase,
        reference_id=reference_id,
        notes="10% auto-hold",
    ))


def debit_wallet(
    db: Session,
    user_id: int,
    agent_tier: int,
    amount: Decimal,
    reference_id: str | None = None,
    notes: str | None = None,
) -> None:
    """
    Deduct amount from the user's MAIN wallet for the given agent tier.
    Raises HTTP 400 if the balance is insufficient.
    Records a WITHDRAWAL transaction.
    """
    four_places = Decimal("0.0001")
    amount = amount.quantize(four_places, rounding=ROUND_HALF_UP)

    wallet = (
        db.query(Wallet)
        .filter_by(user_id=user_id, agent_tier=agent_tier, wallet_type=WalletType.MAIN)
        .with_for_update()
        .first()
    )

    current_balance = Decimal(str(wallet.balance)) if wallet else Decimal("0")
    if current_balance < amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance. Available: ${current_balance:.4f}, Requested: ${amount:.4f}",
        )

    wallet.balance = current_balance - amount

    db.add(Transaction(
        user_id=user_id,
        agent_tier=agent_tier,
        transaction_type=TransactionType.WITHDRAWAL,
        amount=amount,
        reference_id=reference_id,
        notes=notes or "Withdrawal requested",
    ))


# ── Account balance (deposit wallet) ─────────────────────────────────────────

def get_account_balance(db: Session, user_id: int) -> Decimal:
    """Return the current account balance for a user."""
    wallet = (
        db.query(Wallet)
        .filter_by(user_id=user_id, agent_tier=ACCOUNT_TIER, wallet_type=WalletType.ACCOUNT)
        .first()
    )
    return Decimal(str(wallet.balance)) if wallet else Decimal("0")


def credit_account(
    db: Session,
    user_id: int,
    amount: Decimal,
    tx_type: TransactionType,
    reference_id: str | None = None,
    notes: str | None = None,
) -> None:
    """Credit the user's account balance (no repurchase split — full amount credited)."""
    four_places = Decimal("0.0001")
    amount = amount.quantize(four_places, rounding=ROUND_HALF_UP)

    wallet = get_or_create_wallet(db, user_id, ACCOUNT_TIER, WalletType.ACCOUNT)
    wallet.balance = Decimal(str(wallet.balance)) + amount

    db.add(Transaction(
        user_id=user_id,
        agent_tier=ACCOUNT_TIER,
        transaction_type=tx_type,
        amount=amount,
        reference_id=reference_id,
        notes=notes,
    ))


def debit_account(
    db: Session,
    user_id: int,
    amount: Decimal,
    tx_type: TransactionType,
    reference_id: str | None = None,
    notes: str | None = None,
) -> None:
    """
    Deduct amount from the user's account balance.
    Raises HTTP 400 if balance is insufficient.
    """
    four_places = Decimal("0.0001")
    amount = amount.quantize(four_places, rounding=ROUND_HALF_UP)

    wallet = (
        db.query(Wallet)
        .filter_by(user_id=user_id, agent_tier=ACCOUNT_TIER, wallet_type=WalletType.ACCOUNT)
        .with_for_update()
        .first()
    )
    current_balance = Decimal(str(wallet.balance)) if wallet else Decimal("0")
    if current_balance < amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient account balance. Available: ${current_balance:.2f}, Required: ${amount:.2f}",
        )

    wallet.balance = current_balance - amount

    db.add(Transaction(
        user_id=user_id,
        agent_tier=ACCOUNT_TIER,
        transaction_type=tx_type,
        amount=amount,
        reference_id=reference_id,
        notes=notes,
    ))
