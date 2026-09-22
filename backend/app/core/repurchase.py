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

Thresholds (price + platform fee), per the client spec:
    Tier 1  $11   ($10.00 buy + $1 platform fee)
    Tier 2  $22   ($20.00 buy + $2 platform fee)
    Tier 3  $55   ($50.00 buy + $5 platform fee)
    Tier 4  $111  ($100.00 buy + $11 platform fee)

The platform-fee portion is booked as platform profit (REPURCHASE_GAS ledger row) —
the same flat fee charged on a manual purchase, applied to repurchase too ("the
extra amount will go to our platform profit wallet … this includes for repurchase
also"). Boost reserve always accumulates in the tier-1 bucket (Boost is a single
global queue), so Boost-driven repurchases re-buy Agent 1.

`sweep_auto_repurchases` is capped per call (_MAX_REPURCHASE_STEPS) rather than
truly unbounded within one request — each repurchase is itself a real purchase
that runs the full Stream/Boost matrix engine, so an unbounded sweep can make a
single HTTP request run for a very long time once enough reserves are queued up.
The cascade as a whole is still unbounded across TIME ("to its infinity", per
spec) — any reserve left over when the cap is hit is untouched and picked up by
the next purchase's sweep call, so nothing is delayed forever, just spread out.

Everything runs inside the caller's transaction (flush, never commit).
"""
import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.onchain import send_repurchase_settlement
from app.core.pack_payout import compute_pack_split
from app.core.wallet_ops import credit_wallet, get_or_create_wallet
from app.models.agent import AGENT_TIER_PLATFORM_FEE, AGENT_TIER_PRICES
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.models.wallet import Wallet, WalletType

logger = logging.getLogger(__name__)

# Flat platform fee reserved on top of the pack price for each tier's repurchase
# (matches AGENT_TIER_PLATFORM_FEE — the same fee charged on a manual purchase).
# The reserve must reach price + this fee before the tier auto-repurchases.
REPURCHASE_PLATFORM_FEE = {
    tier: Decimal(str(fee)) for tier, fee in AGENT_TIER_PLATFORM_FEE.items()
}

# Per-call cap on how many repurchases one sweep_auto_repurchases() call will
# execute. The reserve math itself always converges (each repurchase consumes
# price+fee and only redistributes 60% as Core, so reserves strictly shrink) —
# but every repurchase is also a real purchase, so it calls run_purchase_matrices
# (matrix_runtime._MAX_STEPS_PER_CALL of work each). Total matrix work for one
# purchase request is (1 + repurchases_this_call) × that budget, so this cap
# and matrix_runtime's multiply together — kept low so the product stays a few
# hundred steps, not thousands. Anything left over when the cap is hit is NOT
# lost — reserves stay in the Wallet table exactly as-is and get re-scanned by
# the very next purchase's sweep call (same "defer, don't drop" pattern as the
# matrix backlog).
_MAX_REPURCHASE_STEPS = 8


def repurchase_threshold(tier: int) -> Decimal:
    """Reserve balance at which tier `tier` auto-repurchases (price + platform fee)."""
    return Decimal(str(AGENT_TIER_PRICES[tier])) + REPURCHASE_PLATFORM_FEE[tier]


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
    platform_fee = REPURCHASE_PLATFORM_FEE[tier]
    threshold = price + platform_fee

    reserve = (
        db.query(Wallet)
        .filter_by(user_id=user.id, agent_tier=tier, wallet_type=WalletType.REPURCHASE)
        .with_for_update()
        .first()
    )
    balance = Decimal(str(reserve.balance)) if reserve else Decimal("0")
    if balance < threshold:
        return False

    # Consume the reserve: price (the re-buy) + platform fee (→ platform profit).
    reserve.balance = balance - threshold
    ref = f"repurchase_u{user.id}_t{tier}"

    # Settle on-chain: move the consumed reserve (price + fee) from the reserve
    # signer wallet to PLATFORM_FEE_WALLET, so it's actually available for the
    # member-payout rail later. Best-effort — returns None (disabled or failed)
    # without raising; the internal accounting above and below always applies
    # regardless, matching today's behavior when this isn't configured.
    tx_hash = send_repurchase_settlement(threshold, tier, ref)
    tx_note = f" (on-chain tx {tx_hash[:12]}…)" if tx_hash else ""

    db.add(Transaction(
        user_id=user.id,
        agent_tier=tier,
        transaction_type=TransactionType.REPURCHASE_BUY,
        amount=price,
        reference_id=ref,
        notes=f"Auto-repurchase Agent {tier} (${price}){tx_note}",
    ))
    db.add(Transaction(
        user_id=user.id,
        agent_tier=tier,
        transaction_type=TransactionType.REPURCHASE_GAS,
        amount=platform_fee,
        reference_id=ref,
        notes=f"Auto-repurchase platform fee (Agent {tier}){tx_note}",
    ))

    # Distribute exactly like a normal purchase (uplines earn + build reserve).
    _distribute_repurchase(db, user, tier, price)

    db.flush()
    logger.info(
        "AUTO-REPURCHASE: user=%s tier=%s price=$%s platform_fee=$%s reserve_left=$%s",
        user.username, tier, price, platform_fee, reserve.balance,
    )
    return True


def sweep_auto_repurchases(db: Session) -> int:
    """
    Process pending auto-repurchases across all users until no per-tier reserve
    is at/over its threshold, OR until _MAX_REPURCHASE_STEPS repurchases have run
    in this call — whichever comes first. Re-buys cascade (an upline's freshly
    credited reserve can itself cross a threshold), so this re-scans after each
    round. Any reserve still over threshold when the cap is hit is left exactly
    as-is (nothing is lost) and gets picked up by the next purchase's sweep call.

    Runs inside the caller's transaction (flush only, never commit). Returns the
    number of repurchases executed in this call.
    """
    # Every tier's threshold is >= the smallest (tier 1, $11), so a wallet below
    # that can never be over ANY tier's threshold — cheap pre-filter that keeps
    # this from re-scanning every reserve wallet in the system on every round
    # (this loop can run up to _MAX_REPURCHASE_STEPS times per call; without the
    # filter that's O(total reserve wallets × steps), which gets slower and
    # slower as the platform grows regardless of how few reserves are actually
    # near threshold).
    min_threshold = min(repurchase_threshold(t) for t in AGENT_TIER_PRICES)

    total = 0
    steps = 0
    while True:
        reserves = (
            db.query(Wallet)
            .filter_by(wallet_type=WalletType.REPURCHASE)
            .filter(Wallet.balance >= min_threshold)
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
