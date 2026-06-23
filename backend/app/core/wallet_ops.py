from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.wallet import Wallet, WalletType
from app.models.transaction import Transaction, TransactionType

REPURCHASE_RATE = Decimal("0.20")     # 20% of gross → repurchase reserve
SOFTWARE_FEE_RATE = Decimal("0.10")   # 10% of gross → platform profit
ACCOUNT_TIER = 0  # Sentinel agent_tier for the platform account balance wallet

# Income the user has *received* (Core/Stream/Boost commissions). On the on-chain
# rail these are recorded as CORE_INCOME transactions paid to the user's own wallet
# on-chain and are NEVER credited to an internal Wallet — so MAIN-wallet balances
# stay $0 and the real earnings figure must be summed from the ledger.
LEDGER_INCOME_TYPES = (
    TransactionType.CORE_INCOME,
    TransactionType.STREAM_PAYOUT,
    TransactionType.BOOST_PAYOUT,
    TransactionType.SPONSOR_MILESTONE_INCOME,
)


def get_ledger_earnings(db: Session, user_id: int) -> Decimal:
    """Lifetime income the user has received, summed from the transaction ledger.
    Use this (not MAIN-wallet balances) for any "total earnings" figure on the
    on-chain rail."""
    total = (
        db.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type.in_(LEDGER_INCOME_TYPES),
        )
        .scalar()
    )
    return Decimal(str(total or 0))


def mirror_onchain_earning_split(
    db: Session,
    user_id: int,
    agent_tier: int,
    gross_amount: Decimal,
) -> tuple[Decimal, Decimal]:
    """
    VIRTUAL internal tracking for an on-chain commission.

    The commission was paid to the user's own wallet ON-CHAIN — no real money
    flows through internal wallets. For display only, we mirror the earning into
    the internal per-tier wallets as an 80% main / 20% repurchase-reserve split so
    the per-tier balances and the "Repurchase Reserve" populate in the UI. These
    balances are display/bookkeeping figures, NOT movable funds (the spendable
    money lives on-chain). No Transaction rows are written here — the reporting
    CORE_INCOME row is written by the caller; this only adjusts wallet balances.

    Returns (main_credit, repurchase) for logging.
    """
    four_places = Decimal("0.0001")
    gross = Decimal(str(gross_amount)).quantize(four_places, rounding=ROUND_HALF_UP)
    repurchase = (gross * REPURCHASE_RATE).quantize(four_places, rounding=ROUND_HALF_UP)
    main_credit = gross - repurchase

    main_wallet = get_or_create_wallet(db, user_id, agent_tier, WalletType.MAIN)
    main_wallet.balance = Decimal(str(main_wallet.balance)) + main_credit

    repurchase_wallet = get_or_create_wallet(db, user_id, agent_tier, WalletType.REPURCHASE)
    repurchase_wallet.balance = Decimal(str(repurchase_wallet.balance)) + repurchase

    return main_credit, repurchase


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

    Two deductions apply (per client spec) — BOTH computed off the
    gross amount (not stacked sequentially):
      1. Software fee (10% of gross)       → platform profit, not distributed
      2. Repurchase reserve (20% of gross) → held in repurchase wallet

    Net math on gross_amount:
      software_fee = gross × 10%   (goes to platform)
      repurchase   = gross × 20%   (held in repurchase wallet)
      main_credit  = gross × 70%   (withdrawable)

    All three movements are recorded in the transaction ledger.
    """
    four_places = Decimal("0.0001")

    # Both deductions are computed off the GROSS amount (two separate
    # sections per client spec). Software fee → platform; repurchase → reserve.
    software_fee = (gross_amount * SOFTWARE_FEE_RATE).quantize(four_places, rounding=ROUND_HALF_UP)
    repurchase = (gross_amount * REPURCHASE_RATE).quantize(four_places, rounding=ROUND_HALF_UP)
    main_credit = gross_amount - software_fee - repurchase

    main_wallet = get_or_create_wallet(db, user_id, agent_tier, WalletType.MAIN)
    main_wallet.balance = Decimal(str(main_wallet.balance)) + main_credit

    repurchase_wallet = get_or_create_wallet(db, user_id, agent_tier, WalletType.REPURCHASE)
    repurchase_wallet.balance = Decimal(str(repurchase_wallet.balance)) + repurchase

    # Record software fee deduction
    db.add(Transaction(
        user_id=user_id,
        agent_tier=agent_tier,
        transaction_type=TransactionType.SOFTWARE_FEE,
        amount=software_fee,
        reference_id=reference_id,
        notes="10% platform software fee",
    ))
    # Record main wallet credit
    db.add(Transaction(
        user_id=user_id,
        agent_tier=agent_tier,
        transaction_type=tx_type,
        amount=main_credit,
        reference_id=reference_id,
        notes=notes,
    ))
    # Record repurchase hold
    db.add(Transaction(
        user_id=user_id,
        agent_tier=agent_tier,
        transaction_type=TransactionType.REPURCHASE_HOLD,
        amount=repurchase,
        reference_id=reference_id,
        notes="20% repurchase reserve",
    ))


def credit_main_wallet_direct(
    db: Session,
    user_id: int,
    agent_tier: int,
    amount: Decimal,
    tx_type: TransactionType,
    reference_id: str | None = None,
    notes: str | None = None,
) -> None:
    """
    Credit amount directly to MAIN wallet with no repurchase split.
    Used for refunds where the 20% repurchase was already taken at earn time.
    """
    four_places = Decimal("0.0001")
    amount = amount.quantize(four_places, rounding=ROUND_HALF_UP)

    wallet = get_or_create_wallet(db, user_id, agent_tier, WalletType.MAIN)
    wallet.balance = Decimal(str(wallet.balance)) + amount

    db.add(Transaction(
        user_id=user_id,
        agent_tier=agent_tier,
        transaction_type=tx_type,
        amount=amount,
        reference_id=reference_id,
        notes=notes,
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


def get_total_earnings(db: Session, user_id: int) -> Decimal:
    """Sum of all MAIN wallet balances (the user's earnings)."""
    wallets = (
        db.query(Wallet)
        .filter_by(user_id=user_id, wallet_type=WalletType.MAIN)
        .all()
    )
    return sum((Decimal(str(w.balance)) for w in wallets), Decimal("0"))


def get_withdrawable_balance(db: Session, user_id: int) -> Decimal:
    """
    Total amount a user can withdraw = unspent account balance + all earnings
    (every MAIN wallet). This is the single combined pool shown on the Withdraw page.
    """
    return get_account_balance(db, user_id) + get_total_earnings(db, user_id)


def debit_withdrawable(
    db: Session,
    user_id: int,
    amount: Decimal,
    reference_id: str | None = None,
    notes: str | None = None,
) -> None:
    """
    Deduct `amount` from the user's combined withdrawable balance: drains MAIN
    wallet earnings first (lowest tier first), then the account balance.
    Raises HTTP 400 if the combined balance is insufficient.
    Records a single WITHDRAWAL transaction (agent_tier=0 = combined).
    """
    four_places = Decimal("0.0001")
    amount = amount.quantize(four_places, rounding=ROUND_HALF_UP)

    main_wallets = (
        db.query(Wallet)
        .filter_by(user_id=user_id, wallet_type=WalletType.MAIN)
        .with_for_update()
        .all()
    )
    account_wallet = (
        db.query(Wallet)
        .filter_by(user_id=user_id, agent_tier=ACCOUNT_TIER, wallet_type=WalletType.ACCOUNT)
        .with_for_update()
        .first()
    )

    main_total = sum((Decimal(str(w.balance)) for w in main_wallets), Decimal("0"))
    account_bal = Decimal(str(account_wallet.balance)) if account_wallet else Decimal("0")
    total = main_total + account_bal
    if total < amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance. Available: ${total:.4f}, Requested: ${amount:.4f}",
        )

    remaining = amount
    # 1. Drain earnings (MAIN wallets), lowest tier first
    for wallet in sorted(main_wallets, key=lambda w: w.agent_tier):
        if remaining <= 0:
            break
        bal = Decimal(str(wallet.balance))
        take = min(bal, remaining)
        wallet.balance = bal - take
        remaining -= take
    # 2. Then the account balance
    if remaining > 0 and account_wallet is not None:
        account_wallet.balance = Decimal(str(account_wallet.balance)) - remaining
        remaining = Decimal("0")

    db.add(Transaction(
        user_id=user_id,
        agent_tier=ACCOUNT_TIER,
        transaction_type=TransactionType.WITHDRAWAL,
        amount=amount,
        reference_id=reference_id,
        notes=notes or "Withdrawal from combined balance",
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
