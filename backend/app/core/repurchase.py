"""
Auto-repurchase engine (per the client "Repurchase" spec).

Every income credit holds back 20% into the user's per-tier REPURCHASE wallet
(see wallet_ops.credit_wallet / mirror_onchain_earning_split). Once a tier's
reserve reaches that tier's threshold (pack price + a fixed gas allowance), the
platform automatically re-buys the SAME tier on the user's behalf, funded from the
reserve. Repurchase is automatic and unbounded ("done automatically to its
infinity") — a manual purchase happens once, repurchases keep going as long as the
reserve can afford them.

A repurchase "acts like a normal purchase": it re-runs the same revenue
distribution — the Core 60% split up the (compressed) sponsor chain plus the
Stream/Boost matrix placement — so uplines earn and build their OWN reserves,
which can in turn trigger their auto-repurchases (intended compounding, per the
client Q&A). That cascade is handled by `sweep_auto_repurchases`, which keeps
re-buying across all users until no reserve is over threshold.

Thresholds (price + gas), per the client spec:
    Tier 1  $10.25  ($10.00 buy + $0.25 gas)
    Tier 2  $20.50  ($20.00 buy + $0.50 gas)
    Tier 3  $51.25  ($50.00 buy + $1.25 gas)
    Tier 4  $102.50 ($100.00 buy + $2.50 gas)

The gas portion is booked as a platform expense/cut (REPURCHASE_GAS) — the client
confirmed the platform pays the network gas. Boost reserve always accumulates in
the tier-1 bucket (Boost is a single global queue), so Boost-driven repurchases
re-buy Agent 1.

Everything runs inside the caller's transaction (flush, never commit).
"""
import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.pack_payout import compute_pack_split
from app.core.wallet_ops import credit_wallet, get_or_create_wallet
from app.models.agent import AGENT_TIER_PRICES
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.models.wallet import Wallet, WalletType

logger = logging.getLogger(__name__)

# Fixed gas allowance reserved on top of the pack price for each tier's repurchase.
REPURCHASE_GAS_FEE = {
    1: Decimal("0.25"),
    2: Decimal("0.50"),
    3: Decimal("1.25"),
    4: Decimal("2.50"),
}

# Safety cap on the cascade (a repurchase can credit uplines, who may repurchase…).
# Each repurchase consumes price+gas and only redistributes 60% as Core, so reserves
# strictly shrink and the cascade converges; this only guards against an anomaly.
_MAX_REPURCHASE_STEPS = 100_000


def repurchase_threshold(tier: int) -> Decimal:
    """Reserve balance at which tier `tier` auto-repurchases (price + gas)."""
    return Decimal(str(AGENT_TIER_PRICES[tier])) + REPURCHASE_GAS_FEE[tier]


def _platform_user_id(db: Session) -> int | None:
    """Lowest-id admin — owns platform-profit ledger rows. None if no admin yet."""
    row = (
        db.query(User.id)
        .filter(User.is_admin.is_(True))
        .order_by(User.id.asc())
        .first()
    )
    return row[0] if row else None


def _distribute_repurchase(db: Session, buyer: User, tier: int, price: Decimal) -> None:
    """
    Run the same revenue distribution a normal purchase does, but credited
    internally (the repurchase is funded from the platform-held reserve, not the
    buyer's own wallet):

      • Core 60% → two compressed/odd-even 30% halves to eligible uplines, each
        credited via credit_wallet (70/20/10 — so uplines build new reserve), and
      • Stream 30% + Boost 10% → the buyer's matrix placements + payout cascade.

    Unroutable Core halves (no eligible upline) are booked as platform profit.
    """
    split = compute_pack_split(db, buyer, tier, price, mutate_counter=True)

    for upline, amount in split.uplines:
        credit_wallet(
            db=db,
            user_id=upline.id,
            agent_tier=tier,
            gross_amount=amount,
            tx_type=TransactionType.CORE_INCOME,
            reference_id=f"repurchase_u{buyer.id}_t{tier}",
            notes=f"Core commission (auto-repurchase, Agent {tier})",
        )

    if split.platform_amount > 0:
        admin_id = _platform_user_id(db)
        if admin_id is not None:
            db.add(Transaction(
                user_id=admin_id,
                agent_tier=tier,
                transaction_type=TransactionType.PLATFORM_PROFIT,
                amount=split.platform_amount,
                reference_id=f"repurchase_u{buyer.id}_t{tier}",
                notes=f"Core residual — no eligible upline (auto-repurchase, Agent {tier})",
            ))

    # Stream + Boost matrices for the repurchasing buyer (same as a normal purchase).
    from app.core.matrix_runtime import run_purchase_matrices
    run_purchase_matrices(db, buyer.id, tier)


def _do_one_repurchase(db: Session, user: User, tier: int) -> bool:
    """
    Consume one tier-`tier` reserve threshold for `user` and re-buy that tier.
    Returns True if a repurchase happened, False if the reserve was insufficient.
    """
    price = Decimal(str(AGENT_TIER_PRICES[tier]))
    gas = REPURCHASE_GAS_FEE[tier]
    threshold = price + gas

    reserve = (
        db.query(Wallet)
        .filter_by(user_id=user.id, agent_tier=tier, wallet_type=WalletType.REPURCHASE)
        .with_for_update()
        .first()
    )
    balance = Decimal(str(reserve.balance)) if reserve else Decimal("0")
    if balance < threshold:
        return False

    # Consume the reserve: price (the re-buy) + gas (platform pays the network fee).
    reserve.balance = balance - threshold
    ref = f"repurchase_u{user.id}_t{tier}"

    db.add(Transaction(
        user_id=user.id,
        agent_tier=tier,
        transaction_type=TransactionType.REPURCHASE_BUY,
        amount=price,
        reference_id=ref,
        notes=f"Auto-repurchase Agent {tier} (${price})",
    ))
    db.add(Transaction(
        user_id=user.id,
        agent_tier=tier,
        transaction_type=TransactionType.REPURCHASE_GAS,
        amount=gas,
        reference_id=ref,
        notes=f"Auto-repurchase gas fee (Agent {tier})",
    ))

    # Distribute exactly like a normal purchase (uplines earn + build reserve).
    _distribute_repurchase(db, user, tier, price)

    db.flush()
    logger.info(
        "AUTO-REPURCHASE: user=%s tier=%s price=$%s gas=$%s reserve_left=$%s",
        user.username, tier, price, gas, reserve.balance,
    )
    return True


def sweep_auto_repurchases(db: Session) -> int:
    """
    Process every pending auto-repurchase across all users until no per-tier
    reserve is at/over its threshold. Re-buys cascade (an upline's freshly credited
    reserve can itself cross a threshold), so this re-scans after each round.

    Runs inside the caller's transaction (flush only, never commit). Returns the
    number of repurchases executed.
    """
    total = 0
    steps = 0
    while True:
        reserves = (
            db.query(Wallet)
            .filter_by(wallet_type=WalletType.REPURCHASE)
            .all()
        )
        progressed = False
        for w in reserves:
            tier = w.agent_tier
            if tier not in AGENT_TIER_PRICES:
                continue
            if Decimal(str(w.balance)) < repurchase_threshold(tier):
                continue
            user = db.query(User).filter_by(id=w.user_id).first()
            # Reserve of a frozen/inactive user is held (client spec) — skip it.
            if user is None or not user.is_active:
                continue
            if _do_one_repurchase(db, user, tier):
                total += 1
                progressed = True
                steps += 1
                if steps >= _MAX_REPURCHASE_STEPS:
                    logger.error(
                        "sweep_auto_repurchases: hit %d-step cap — stopping (possible loop).",
                        _MAX_REPURCHASE_STEPS,
                    )
                    return total
        if not progressed:
            break
    if total:
        logger.info("sweep_auto_repurchases: executed %d repurchase(s).", total)
    return total
