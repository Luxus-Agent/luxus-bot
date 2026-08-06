import re
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.wallet import Wallet, WalletType
from app.models.wallet_address import WalletAddress
from app.models.transaction import Transaction, TransactionType

REPURCHASE_RATE = Decimal("0.20")     # 20% of gross → repurchase reserve
SOFTWARE_FEE_RATE = Decimal("0.10")   # 10% of gross → platform profit
ACCOUNT_TIER = 0  # Sentinel agent_tier for the platform account balance wallet

_BEP20_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def resolve_payout_address(db: Session, user: User) -> str | None:
    """
    A user's payout address: their registration address (User.wallet_address),
    else their most recently registered *verified* withdrawal address, else
    None. Only returns it if it's a syntactically valid BEP-20 address.

    Shared by Core's on-chain purchase flow (app/api/distribution.py) and
    Stream/Boost's on-chain payout settlement (app/core/matrix_runtime.py) —
    both need the exact same "where do we actually send this user's money"
    lookup, so it lives here rather than being duplicated or reached into as
    another module's private helper.
    """
    addr = user.wallet_address
    if not addr:
        row = (
            db.query(WalletAddress.address)
            .filter(WalletAddress.user_id == user.id, WalletAddress.is_verified.is_(True))
            .order_by(WalletAddress.created_at.desc())
            .first()
        )
        addr = row[0] if row else None
    return addr if addr and _BEP20_RE.match(addr) else None

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


def resolve_tx_hashes(db: Session, reference_ids: set[str]) -> dict[str, str]:
    """Map Transaction.reference_id -> on-chain tx_hash, for rows tied to a settled
    PackPurchase (order_id) or PayoutBatch (batch_id). Ledger-only transaction types
    (stream_payout, repurchase_hold, admin_credit, ...) have no reference_id here and
    are simply absent from the result."""
    if not reference_ids:
        return {}
    from app.models.pack_purchase import PackPurchase
    from app.models.payout_batch import PayoutBatch

    hashes: dict[str, str] = {}
    for order_id, tx_hash in (
        db.query(PackPurchase.order_id, PackPurchase.tx_hash)
        .filter(PackPurchase.order_id.in_(reference_ids), PackPurchase.tx_hash.isnot(None))
        .all()
    ):
        hashes[order_id] = tx_hash
    for batch_id, tx_hash in (
        db.query(PayoutBatch.batch_id, PayoutBatch.tx_hash)
        .filter(PayoutBatch.batch_id.in_(reference_ids), PayoutBatch.tx_hash.isnot(None))
        .all()
    ):
        hashes[batch_id] = tx_hash
    return hashes


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
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Apply the 70/20/10 wallet rule to a Core commission (per the client spec —
    "if a user gets income, it should be split as 70/20/10") — WITHOUT crediting
    the 70% main share to an internal wallet, because on this on-chain rail that
    70% was already paid directly, on-chain, from the buyer's own wallet straight
    to this user's wallet at purchase time (see pack_purchase's "upline" recipient
    in app/api/distribution.py). Crediting it again here would double-pay it once
    an automatic/admin payout sweep later drains internal wallet balances.

    From the gross Core share:
      • 10% software fee  → platform (recorded as a SOFTWARE_FEE transaction)
      • 20% repurchase    → held in the user's per-tier REPURCHASE wallet (this
        20% really was paid on-chain to the pooled REPURCHASE_RESERVE_WALLET, not
        to the user directly, so tracking each user's share internally is correct)
      • 70% main          → NOT credited to any wallet (already delivered on-chain)

    The caller writes the CORE_INCOME row for the user's FULL gross commission
    (per client spec — "Total Earnings" must show the amount before the platform
    fee is subtracted) — that ledger row (not a wallet balance) is what
    GET /wallet/earnings sums for "Total Earnings", so the earnings display is
    unaffected by this function not touching Wallet.MAIN.

    Returns (main_credit, repurchase, software_fee).
    """
    four_places = Decimal("0.0001")
    gross = Decimal(str(gross_amount)).quantize(four_places, rounding=ROUND_HALF_UP)
    software_fee = (gross * SOFTWARE_FEE_RATE).quantize(four_places, rounding=ROUND_HALF_UP)
    repurchase = (gross * REPURCHASE_RATE).quantize(four_places, rounding=ROUND_HALF_UP)
    main_credit = gross - software_fee - repurchase

    repurchase_wallet = get_or_create_wallet(db, user_id, agent_tier, WalletType.REPURCHASE)
    repurchase_wallet.balance = Decimal(str(repurchase_wallet.balance)) + repurchase

    # 10% software fee → platform profit (recorded against the earner, as in
    # credit_wallet). Admin profit reporting sums SOFTWARE_FEE regardless of owner.
    db.add(Transaction(
        user_id=user_id,
        agent_tier=agent_tier,
        transaction_type=TransactionType.SOFTWARE_FEE,
        amount=software_fee,
        notes="10% software fee (Core commission)",
    ))

    return main_credit, repurchase, software_fee


def mirror_onchain_boost_split(
    db: Session,
    user_id: int,
    agent_tier: int,
    gross_amount: Decimal,
) -> tuple[Decimal, Decimal]:
    """
    Boost's on-chain equivalent of mirror_onchain_earning_split: the 90% net
    share (gross minus the 10% software fee) was already sent directly
    on-chain to the recipient's own wallet at settlement time
    (matrix_runtime._settle_or_credit), so this only books the 10% software
    fee internally — no repurchase reserve (Boost doesn't feed it, unlike
    Core/Stream) and no main-wallet credit (the 90% already landed on-chain).

    Only applies to a Boost payout's OWN wallet_amount, never its
    sponsor-share bonus — the sponsor share is paid in addition, unreduced
    (see credit_main_wallet_direct's docstring).

    Returns (main_credit, software_fee) for symmetry with the Stream/Core
    version; only software_fee is actually booked here.
    """
    four_places = Decimal("0.0001")
    gross = Decimal(str(gross_amount)).quantize(four_places, rounding=ROUND_HALF_UP)
    software_fee = (gross * SOFTWARE_FEE_RATE).quantize(four_places, rounding=ROUND_HALF_UP)
    main_credit = gross - software_fee

    db.add(Transaction(
        user_id=user_id,
        agent_tier=agent_tier,
        transaction_type=TransactionType.SOFTWARE_FEE,
        amount=software_fee,
        notes="10% software fee (Boost payout)",
    ))

    return main_credit, software_fee


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

    All three movements are recorded in the transaction ledger. The headline
    `tx_type` row records the FULL gross_amount (per client spec — ledger income
    figures like "Total Earnings" must show the amount before the platform fee is
    subtracted), even though only main_credit (70%) actually landed in the MAIN
    wallet — the SOFTWARE_FEE and REPURCHASE_HOLD sibling rows above/below it
    document where the other 30% went.
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
    # Record main wallet credit — headline ledger row shows the FULL gross amount
    # (see docstring); only main_credit (70%) was actually added to Wallet.MAIN.
    db.add(Transaction(
        user_id=user_id,
        agent_tier=agent_tier,
        transaction_type=tx_type,
        amount=gross_amount,
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


def credit_boost_wallet(
    db: Session,
    user_id: int,
    agent_tier: int,
    gross_amount: Decimal,
    tx_type: TransactionType,
    reference_id: str | None = None,
    notes: str | None = None,
) -> None:
    """
    Credit a Boost matrix payout (the position holder's own wallet_amount,
    NOT its sponsor-share bonus) to MAIN with a 10% software-fee deduction —
    no repurchase-reserve cut (client spec: unlike Core/Stream, Boost never
    feeds the repurchase reserve). Distinct from credit_wallet's 70/20/10
    split (Core/Stream) and from credit_main_wallet_direct's 100%-no-split
    (Boost's sponsor-share bonus, paid in addition and never fee-reduced).
    """
    four_places = Decimal("0.0001")
    software_fee = (gross_amount * SOFTWARE_FEE_RATE).quantize(four_places, rounding=ROUND_HALF_UP)
    main_credit = gross_amount - software_fee

    main_wallet = get_or_create_wallet(db, user_id, agent_tier, WalletType.MAIN)
    main_wallet.balance = Decimal(str(main_wallet.balance)) + main_credit

    db.add(Transaction(
        user_id=user_id,
        agent_tier=agent_tier,
        transaction_type=TransactionType.SOFTWARE_FEE,
        amount=software_fee,
        reference_id=reference_id,
        notes="10% platform software fee (Boost payout)",
    ))
    # Headline row shows the FULL gross amount (see credit_wallet's docstring
    # for why) — only main_credit (90%) was actually added to Wallet.MAIN.
    db.add(Transaction(
        user_id=user_id,
        agent_tier=agent_tier,
        transaction_type=tx_type,
        amount=gross_amount,
        reference_id=reference_id,
        notes=notes,
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
    Credit amount directly to MAIN wallet with no repurchase/software-fee
    split — used for Boost-sourced SPONSOR share only (paid in addition to
    the recipient's own income, unreduced — see credit_boost_wallet for the
    position holder's own payout, which DOES take a 10% fee), and for
    refunds where the 20% repurchase was already taken at earn time.
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
