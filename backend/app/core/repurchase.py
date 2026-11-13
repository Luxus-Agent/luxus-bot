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

Two modes. Default (commit_each=False): everything runs inside the caller's
transaction (flush, never commit) and the settlement broadcast is made inline.
Money-safe mode (commit_each=True, what pack/status uses): each repurchase's
DATABASE work (reserve consumption, ledger, Core credits, matrix placement) is
committed FIRST, and only then is the on-chain settlement broadcast — so a
failure can never leave a broadcast whose accounting was rolled back (which a
retry would pay again). The failure direction becomes "booked but not yet
consolidated on-chain" (nothing lost, reconcilable), never a double payment.
The caller must have committed its own work before calling in this mode.
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


def _distribute_repurchase(
    db: Session, buyer: User, tier: int, price: Decimal, place_only: bool = False,
) -> None:
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
    # place_only: queue the placement but leave draining (which can broadcast
    # on-chain) to the caller, after this repurchase's DB work is committed.
    from app.core.matrix_runtime import place_purchase_in_matrices, run_purchase_matrices
    if place_only:
        place_purchase_in_matrices(db, buyer.id, tier)
    else:
        run_purchase_matrices(db, buyer.id, tier)


def _do_one_repurchase(db: Session, user: User, tier: int, deferred: list | None = None) -> bool:
    """
    Consume one tier-`tier` reserve threshold for `user` and re-buy that tier.
    Returns True if a repurchase happened, False if the reserve was insufficient.

    `deferred` (money-safe mode): when a list is passed, the on-chain settlement
    is NOT broadcast here — a (threshold, tier, ref, buy_row, gas_row) tuple is
    appended instead, for the caller to settle after committing, and the matrix
    placement is queued without draining.
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
    tx_hash = None if deferred is not None else send_repurchase_settlement(threshold, tier, ref)
    tx_note = f" (on-chain tx {tx_hash[:12]}…)" if tx_hash else ""

    buy_row = Transaction(
        user_id=user.id,
        agent_tier=tier,
        transaction_type=TransactionType.REPURCHASE_BUY,
        amount=price,
        reference_id=ref,
        notes=f"Auto-repurchase Agent {tier} (${price}){tx_note}",
    )
    gas_row = Transaction(
        user_id=user.id,
        agent_tier=tier,
        transaction_type=TransactionType.REPURCHASE_GAS,
        amount=platform_fee,
        reference_id=ref,
        notes=f"Auto-repurchase platform fee (Agent {tier}){tx_note}",
    )
    db.add(buy_row)
    db.add(gas_row)

    # Distribute exactly like a normal purchase (uplines earn + build reserve).
    _distribute_repurchase(db, user, tier, price, place_only=deferred is not None)

    db.flush()
    if deferred is not None:
        deferred.append((threshold, tier, ref, buy_row, gas_row))
    logger.info(
        "AUTO-REPURCHASE: user=%s tier=%s price=$%s platform_fee=$%s reserve_left=$%s",
        user.username, tier, price, platform_fee, reserve.balance,
    )
    return True


def _settle_deferred(db: Session, deferred: list) -> None:
    """Broadcast the on-chain settlement for repurchases whose DB work is already
    committed, then annotate their ledger rows with the tx hash. Best-effort."""
    for threshold, tier, ref, buy_row, gas_row in deferred:
        # buy_row.id is unique per repurchase -> a safe idempotency key.
        tx_hash = send_repurchase_settlement(threshold, tier, ref, f"repurchase_buy_{buy_row.id}")
        if tx_hash:
            note = f" (on-chain tx {tx_hash[:12]}…)"
            buy_row.notes = (buy_row.notes or "") + note
            gas_row.notes = (gas_row.notes or "") + note
            db.commit()
    deferred.clear()


def sweep_auto_repurchases(db: Session, commit_each: bool = False) -> int:
    """
    Process pending auto-repurchases across all users until no per-tier reserve
    is at/over its threshold, OR until _MAX_REPURCHASE_STEPS repurchases have run
    in this call — whichever comes first. Re-buys cascade (an upline's freshly
    credited reserve can itself cross a threshold), so this re-scans after each
    round. Any reserve still over threshold when the cap is hit is left exactly
    as-is (nothing is lost) and gets picked up by the next purchase's sweep call.

    Default: runs inside the caller's transaction (flush only, never commit).
    commit_each=True: money-safe mode (see module docstring) — commits each
    repurchase's DB work, then settles it on-chain, then drains the matrix
    backlog row by row; a failure rolls back only the unit in flight and stops
    the sweep. Returns the number of repurchases executed in this call.
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
            deferred: list | None = [] if commit_each else None
            try:
                did = _do_one_repurchase(db, user, tier, deferred)
                if commit_each:
                    db.commit()
            except Exception:
                if not commit_each:
                    raise
                db.rollback()
                logger.exception(
                    "sweep_auto_repurchases: repurchase user=%s tier=%s failed — rolled back, stopping sweep.",
                    w.user_id, tier,
                )
                return total
            if did:
                if commit_each:
                    from app.core.matrix_runtime import drain_matrix_backlog
                    _settle_deferred(db, deferred)
                    drain_matrix_backlog(db, commit_each=True)
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
