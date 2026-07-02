"""
Synchronous driver for the Stream / Boost matrix engine.

This replaces the removed Celery task chain (workers/tasks.py) with an in-request,
fully synchronous run. On a confirmed purchase it:

  1. places the buyer as a real join in the Stream queues (their tier) and the
     Boost queues (global, tier 1) — one entry into each of L1/L2/L3 at once,
     per matrix_engine.place_real_join,
  2. queues every level-completion payout/sponsor-share this triggers into the
     durable MatrixPendingPayout backlog, then drains up to _MAX_STEPS_PER_CALL
     items from that backlog (oldest first, across ALL users/tiers — not just
     this buyer's own), crediting wallets via credit_wallet and placing the
     re-entries each payout grants back into that SAME level's own queue
     (matrix_engine.place_level_reentry — Stream re-entries are dummy, Boost's
     are real), and
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
    PendingSponsorPayout,
    place_level_reentry,
    place_real_join,
)
from app.core.wallet_ops import credit_wallet
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
        reentry_amount=p.reentry_amount,
        reentry_count=p.reentry_count,
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


def _enqueue_all(db: Session, payouts: list[PendingPayout], sponsors: list[PendingSponsorPayout]) -> None:
    for p in payouts:
        _enqueue_payout(db, p)
    for sp in sponsors:
        _enqueue_sponsor(db, sp)


def _credit_row_payout(db: Session, row: MatrixPendingPayout) -> None:
    """Credit a completed matrix level to the owner's wallet (70/20/10)."""
    tx_type = (
        TransactionType.STREAM_PAYOUT
        if row.system_type == SystemType.STREAM
        else TransactionType.BOOST_PAYOUT
    )
    credit_wallet(
        db=db,
        user_id=row.owner_user_id,
        agent_tier=row.agent_tier,
        gross_amount=Decimal(str(row.amount)),
        tx_type=tx_type,
        reference_id=f"matrix_pos_{row.matrix_position_id}_L{row.level}",
        notes=f"{row.system_type.value} L{row.level} payout",
    )


def _credit_row_sponsor(db: Session, row: MatrixPendingPayout) -> None:
    """
    Credit the 10% level-completion sponsor share to the owner's *current*
    sponsor. An inactive/missing sponsor is treated as "no sponsor" (consistent
    with Core routing): the share is retained by the platform as profit.
    """
    owner = db.query(User).filter_by(id=row.owner_user_id).first()
    sponsor = (
        db.query(User).filter_by(id=owner.sponsor_id).first()
        if owner and owner.sponsor_id else None
    )
    if sponsor is not None and not sponsor.is_active:
        sponsor = None

    if sponsor is not None:
        credit_wallet(
            db=db,
            user_id=sponsor.id,
            agent_tier=row.agent_tier,
            gross_amount=Decimal(str(row.amount)),
            tx_type=TransactionType.SPONSOR_MILESTONE_INCOME,
            reference_id=f"sponsor_share_pos_{row.matrix_position_id}_L{row.level}",
            notes=f"{row.system_type.value} L{row.level} sponsor share",
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
    user/tier/system), crediting payouts and sponsor shares and placing any
    re-entries a payout grants back into that SAME level's own queue (which
    themselves get queued, not processed inline, so this stays a flat loop
    bounded by max_steps — not recursion).

    Returns the number of rows processed. Flushes; does NOT commit.
    """
    processed = 0
    while processed < max_steps:
        row = _next_backlog_row(db)
        if row is None:
            break

        if row.kind == PendingKind.PAYOUT:
            _credit_row_payout(db, row)
            is_stream = row.system_type == SystemType.STREAM
            for _ in range(row.reentry_count or 0):
                if is_stream:
                    p, s = place_level_reentry(
                        db, row.owner_user_id, row.agent_tier, SystemType.STREAM,
                        row.level, is_dummy=True,
                    )
                else:
                    p, s = place_level_reentry(
                        db, row.owner_user_id, BOOST_TIER, SystemType.BOOST,
                        row.level, is_dummy=False,
                    )
                _enqueue_all(db, p, s)
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
    p, s = place_real_join(db, buyer_id, agent_tier, SystemType.STREAM)
    _enqueue_all(db, p, s)
    p, s = place_real_join(db, buyer_id, BOOST_TIER, SystemType.BOOST)
    _enqueue_all(db, p, s)
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
