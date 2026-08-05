"""
Synchronous driver for the Stream / Boost matrix engine.

This replaces the removed Celery task chain (workers/tasks.py) with an in-request,
fully synchronous run. On a confirmed purchase it:

  1. places the buyer as a real join in the Stream queues (their tier) and the
     Boost queues (global, tier 1) — one entry into each of L1/L2/L3 at once,
     per matrix_engine.place_real_join,
  2. queues every incremental payout, level-completion sponsor-share, and
     re-entry-spawn this triggers into the durable MatrixPendingPayout backlog,
     then drains up to _MAX_STEPS_PER_CALL items from that backlog (oldest
     first, across ALL users/tiers — not just this buyer's own): payouts and
     sponsor shares settle INSTANTLY ON-CHAIN when possible (_settle_or_credit
     — Stream sends 70% straight to the recipient's wallet via
     onchain.send_matrix_payout_settlement, 20%/10% still booked internally
     via wallet_ops.mirror_onchain_earning_split; Boost sends the full 100%),
     falling back to internal-only crediting (credit_wallet / credit_main_wallet_direct,
     today's original behavior) whenever settlement isn't possible — feature
     disabled, no wallet address on file, or the broadcast failed. Re-entry
     rows place that level's re-entries back into its own queue (matrix_engine.
     place_level_reentry — Stream re-entries are dummy, Boost's are real), and
  3. leaves anything past the step cap safely queued for the next purchase to
     continue — see MatrixPendingPayout's docstring for why this must be durable.

Why bounded + durable even though matrix_engine.py's per-level queue design is
already self-bounding (see that module's docstring for the stability argument):
this is cheap defense-in-depth. A prior implementation used one shared ancestor
tree where a single new join could complete three levels at once for its
parent/grandparent/great-grandparent, and — because Boost re-entries are real,
per spec — feed real re-entries back into that same shared structure. That was
mathematically critical (not just slow): an isolated replay of real platform
purchases produced 2,985+ payouts (still climbing) from a single triggering
purchase, from a Boost pool that had collected only cents, starting around the
19th real Boost placement platform-wide. The current engine can't reproduce
that (each level's re-entries only feed themselves, a contracting series), but
draining through a persisted, capped queue costs nothing and means a purchase's
response time is bounded regardless, and a payout is never silently lost — it's
either credited or still sitting in the backlog, never both, never neither.

Everything runs inside the caller's transaction — this module flushes but does NOT
commit; the caller owns the commit. Idempotency of the *initial* placement is the
caller's responsibility (the on-chain pack/status handler is PENDING-guarded, so
each purchase places its buyer exactly once); draining the backlog itself is
naturally idempotent since each row is deleted the moment it's credited.
"""
import logging
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.matrix_engine import (
    PendingPayout,
    PendingReentry,
    PendingSponsorPayout,
    place_level_reentry,
    place_real_join,
)
from app.core.onchain import send_matrix_payout_settlement
from app.core.wallet_ops import (
    credit_main_wallet_direct,
    credit_wallet,
    mirror_onchain_earning_split,
    resolve_payout_address,
)
from app.models.matrix import MatrixPendingPayout, PendingKind, SystemType
from app.models.transaction import Transaction, TransactionType
from app.models.user import User

logger = logging.getLogger(__name__)

# Bounded per-purchase-call budget for draining the durable backlog. Organic
# usage stays tiny under the queue-per-level design — this cap exists purely so
# a purchase request can never hang regardless of how deep the backlog gets;
# any excess is simply left for the next purchase to continue draining.
#
# Kept modest (not e.g. 60) because run_purchase_matrices is also called once
# per auto-repurchase inside sweep_auto_repurchases — so a single purchase
# request's total matrix work is (1 + repurchases_this_call) × this budget.
# With repurchase.py's own cap at 8, worst case here is ~9 × 20 = 180 steps,
# not 21 × 60 = 1,260.
_MAX_STEPS_PER_CALL = 20

BOOST_TIER = 1  # Boost is a single global queue, always booked at tier 1.


def _enqueue_payout(db: Session, p: PendingPayout) -> None:
    db.add(MatrixPendingPayout(
        kind=PendingKind.PAYOUT,
        matrix_position_id=p.matrix_position_id,
        owner_user_id=p.user_id,
        agent_tier=p.agent_tier,
        system_type=p.system_type,
        level=p.level,
        amount=p.wallet_amount,
    ))


def _enqueue_sponsor(db: Session, sp: PendingSponsorPayout) -> None:
    db.add(MatrixPendingPayout(
        kind=PendingKind.SPONSOR,
        matrix_position_id=sp.matrix_position_id,
        owner_user_id=sp.owner_user_id,
        agent_tier=sp.agent_tier,
        system_type=sp.system_type,
        level=sp.level,
        amount=sp.amount,
    ))


def _enqueue_reentry(db: Session, r: PendingReentry) -> None:
    db.add(MatrixPendingPayout(
        kind=PendingKind.REENTRY,
        matrix_position_id=r.matrix_position_id,
        owner_user_id=r.owner_user_id,
        agent_tier=r.agent_tier,
        system_type=r.system_type,
        level=r.level,
        amount=Decimal("0"),
        reentry_amount=r.reentry_amount,
        reentry_count=r.reentry_count,
    ))


def _enqueue_all(
    db: Session,
    payouts: list[PendingPayout],
    sponsors: list[PendingSponsorPayout],
    reentries: list[PendingReentry],
) -> None:
    for p in payouts:
        _enqueue_payout(db, p)
    for sp in sponsors:
        _enqueue_sponsor(db, sp)
    for r in reentries:
        _enqueue_reentry(db, r)


def _settle_or_credit(
    db: Session,
    owner: User,
    agent_tier: int,
    system_type: SystemType,
    gross_amount: Decimal,
    tx_type: TransactionType,
    reference_id: str,
    notes: str,
) -> None:
    """
    Instant on-chain settlement, falling back to internal-only crediting
    exactly as before this feature existed. Shared by both a matrix payout's
    own head credit and its sponsor-share bonus — same rule either way, only
    who `owner` is differs.

    Attempts to broadcast straight to `owner`'s own wallet: Stream sends only
    its 70% share (20%/10% stay internal, booked via mirror_onchain_earning_split
    — the exact function Core already uses for the same "70% already paid
    on-chain, don't double-credit MAIN" bookkeeping); Boost sends the full
    100% (it has no internal split at all, per the client spec). On success
    the headline ledger row records the FULL gross amount (per the existing
    "Total Earnings shows gross" convention) with its own `tx_hash`.

    Falls back to today's fully-internal crediting (credit_wallet /
    credit_main_wallet_direct, no tx_hash) whenever settlement isn't
    possible: PLATFORM_FEE_SIGNER_PRIVATE_KEY unset (feature disabled), the
    owner has no wallet address on file, or the broadcast itself fails —
    send_matrix_payout_settlement is best-effort and never raises, so this
    fallback is unconditional on tx_hash being falsy, not a caught exception.
    """
    address = resolve_payout_address(db, owner)
    tx_hash = None
    if address:
        onchain_share = gross_amount if system_type == SystemType.BOOST else gross_amount * Decimal("0.70")
        tx_hash = send_matrix_payout_settlement(onchain_share, address, reference_id)

    if tx_hash:
        if system_type == SystemType.STREAM:
            mirror_onchain_earning_split(db, owner.id, agent_tier, gross_amount)
        # Boost: nothing further to book internally — 100% just went on-chain.
        db.add(Transaction(
            user_id=owner.id,
            agent_tier=agent_tier,
            transaction_type=tx_type,
            amount=gross_amount,
            reference_id=reference_id,
            notes=notes,
            tx_hash=tx_hash,
        ))
    elif system_type == SystemType.BOOST:
        credit_main_wallet_direct(
            db=db, user_id=owner.id, agent_tier=agent_tier, amount=gross_amount,
            tx_type=tx_type, reference_id=reference_id, notes=notes,
        )
    else:
        credit_wallet(
            db=db, user_id=owner.id, agent_tier=agent_tier, gross_amount=gross_amount,
            tx_type=tx_type, reference_id=reference_id, notes=notes,
        )


def _credit_row_payout(db: Session, row: MatrixPendingPayout) -> None:
    """
    Settle (or credit internally) one incremental matrix payout for the
    owner. A frozen (is_active=False) or deleted owner is treated like an
    ineligible Core upline: the payout is retained by the platform as
    profit instead of reaching a frozen/removed account.
    """
    tx_type = (
        TransactionType.STREAM_PAYOUT
        if row.system_type == SystemType.STREAM
        else TransactionType.BOOST_PAYOUT
    )
    reference_id = f"matrix_pos_{row.matrix_position_id}_L{row.level}_join"
    owner = db.query(User).filter_by(id=row.owner_user_id).first()
    if owner is None or not owner.is_active:
        db.add(Transaction(
            user_id=row.owner_user_id,
            agent_tier=row.agent_tier,
            transaction_type=TransactionType.PLATFORM_PROFIT,
            amount=Decimal(str(row.amount)),
            reference_id=reference_id,
            notes=f"{row.system_type.value} L{row.level} payout — owner frozen, retained by platform",
        ))
        return

    _settle_or_credit(
        db, owner, row.agent_tier, row.system_type, Decimal(str(row.amount)),
        tx_type, reference_id, f"{row.system_type.value} L{row.level} payout",
    )


def _credit_row_sponsor(db: Session, row: MatrixPendingPayout) -> None:
    """
    Settle (or credit internally) the 10% level-completion sponsor share to
    the owner's *current* sponsor. The reference_id is tagged with the source
    system (sponsor_share_stream_.../sponsor_share_boost_...) so downstream
    aggregates (GET /admin/metrics, GET /wallet/earnings) can apply the right
    rate without a schema change — pre-existing rows (from before this split
    existed) keep their untagged `sponsor_share_pos_...` format and are
    correctly treated as 70%-split, since that's genuinely how they were
    credited at the time. An inactive/missing sponsor is treated as "no
    sponsor" (consistent with Core routing): the share is retained by the
    platform as profit.
    """
    owner = db.query(User).filter_by(id=row.owner_user_id).first()
    sponsor = (
        db.query(User).filter_by(id=owner.sponsor_id).first()
        if owner and owner.sponsor_id else None
    )
    if sponsor is not None and not sponsor.is_active:
        sponsor = None

    reference_id = f"sponsor_share_{row.system_type.value}_pos_{row.matrix_position_id}_L{row.level}"
    if sponsor is not None:
        _settle_or_credit(
            db, sponsor, row.agent_tier, row.system_type, Decimal(str(row.amount)),
            TransactionType.SPONSOR_MILESTONE_INCOME, reference_id,
            f"{row.system_type.value} L{row.level} sponsor share",
        )
    else:
        db.add(Transaction(
            user_id=row.owner_user_id,
            agent_tier=row.agent_tier,
            transaction_type=TransactionType.PLATFORM_PROFIT,
            amount=Decimal(str(row.amount)),
            reference_id=f"sponsor_orphan_pos_{row.matrix_position_id}_L{row.level}",
            notes=f"{row.system_type.value} L{row.level} sponsor share — no active sponsor, retained by platform",
        ))


def _spawn_reentries(db: Session, row: MatrixPendingPayout) -> None:
    """
    Place a completed level's re-entries back into its own queue — Stream's
    are dummy, Boost's are real (per spec). Never touches a wallet. Whatever
    further payouts/sponsors/reentries this itself triggers are re-enqueued,
    not processed inline, so drain_matrix_backlog stays a flat loop.
    """
    is_stream = row.system_type == SystemType.STREAM
    for _ in range(row.reentry_count or 0):
        if is_stream:
            p, s, r = place_level_reentry(
                db, row.owner_user_id, row.agent_tier, SystemType.STREAM,
                row.level, is_dummy=True,
            )
        else:
            p, s, r = place_level_reentry(
                db, row.owner_user_id, BOOST_TIER, SystemType.BOOST,
                row.level, is_dummy=False,
            )
        _enqueue_all(db, p, s, r)


def _next_backlog_row(db: Session) -> MatrixPendingPayout | None:
    """Oldest pending item, locked so concurrent purchases don't double-process it."""
    return (
        db.query(MatrixPendingPayout)
        .order_by(MatrixPendingPayout.id.asc())
        .with_for_update(skip_locked=True)
        .first()
    )


def drain_matrix_backlog(db: Session, max_steps: int = _MAX_STEPS_PER_CALL) -> int:
    """
    Process up to `max_steps` durable backlog rows (oldest first, across every
    user/tier/system): PAYOUT rows credit one incremental joiner-triggered
    amount, SPONSOR rows credit a level-completion sponsor share, and REENTRY
    rows place a completed level's re-entries back into that SAME level's own
    queue (which themselves get queued, not processed inline, so this stays a
    flat loop bounded by max_steps — not recursion).

    Returns the number of rows processed. Flushes; does NOT commit.
    """
    processed = 0
    while processed < max_steps:
        row = _next_backlog_row(db)
        if row is None:
            break

        if row.kind == PendingKind.PAYOUT:
            _credit_row_payout(db, row)
        elif row.kind == PendingKind.REENTRY:
            _spawn_reentries(db, row)
        else:
            _credit_row_sponsor(db, row)

        db.delete(row)
        db.flush()
        processed += 1

    return processed


def run_purchase_matrices(db: Session, buyer_id: int, agent_tier: int) -> dict:
    """
    Place the buyer as a real join in the Stream + Boost queues, queue whatever
    level completions that immediately triggers, then drain the durable
    backlog (this purchase's own work plus anything left over from earlier
    purchases) up to a bounded step budget. Flushes within the caller's
    transaction; does NOT commit.

    Returns a small summary dict for logging.
    """
    p, s, r = place_real_join(db, buyer_id, agent_tier, SystemType.STREAM)
    _enqueue_all(db, p, s, r)
    p, s, r = place_real_join(db, buyer_id, BOOST_TIER, SystemType.BOOST)
    _enqueue_all(db, p, s, r)
    db.flush()

    processed = drain_matrix_backlog(db)

    backlog_remaining = db.query(func.count(MatrixPendingPayout.id)).scalar() or 0
    if backlog_remaining:
        logger.info(
            "run_purchase_matrices: buyer=%s tier=%s processed=%d, %d backlog item(s) "
            "deferred to the next purchase.",
            buyer_id, agent_tier, processed, backlog_remaining,
        )
    else:
        logger.info(
            "run_purchase_matrices: buyer=%s tier=%s processed=%d, backlog drained.",
            buyer_id, agent_tier, processed,
        )
    return {"processed": processed, "backlog_remaining": backlog_remaining}
