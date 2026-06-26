"""
Synchronous driver for the Stream / Boost matrix engine.

This replaces the removed Celery task chain (workers/tasks.py) with an in-request,
fully synchronous run. On a confirmed purchase it:

  1. places the buyer in the Stream queue (their tier) and the Boost queue (global,
     tier 1),
  2. drains every level-completion payout — crediting the winner's wallet through
     credit_wallet (the 70/20/10 rule) and placing the re-entries each completion
     grants (Stream → DUMMY back into the same tier's Stream queue; Boost → REAL
     into the single Boost queue), cascading until no payouts remain, and
  3. credits each sponsor share (L2/L3) to the owner's active sponsor, or books it
     as platform profit when there is no active sponsor.

Everything runs inside the caller's transaction — this module flushes but does NOT
commit; the caller owns the commit. Idempotency is the caller's responsibility
(the on-chain pack/status handler is PENDING-guarded, so it runs once per order).
"""
import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.matrix_engine import (
    PendingPayout,
    PendingSponsorPayout,
    place_in_matrix,
)
from app.core.wallet_ops import credit_wallet
from app.models.matrix import SystemType
from app.models.transaction import Transaction, TransactionType
from app.models.user import User

logger = logging.getLogger(__name__)

# Safety cap on the synchronous cascade. A single purchase contracts (3 fills →
# 1 re-entry), so real runs are tiny; this only guards against an unexpected loop.
_MAX_PAYOUT_STEPS = 100_000

BOOST_TIER = 1  # Boost is a single global queue, always booked at tier 1.


def _credit_matrix_payout(db: Session, payout: PendingPayout) -> None:
    """Credit a completed matrix level to the owner's wallet (70/20/10)."""
    tx_type = (
        TransactionType.STREAM_PAYOUT
        if payout.system_type == SystemType.STREAM
        else TransactionType.BOOST_PAYOUT
    )
    credit_wallet(
        db=db,
        user_id=payout.user_id,
        agent_tier=payout.agent_tier,
        gross_amount=payout.wallet_amount,
        tx_type=tx_type,
        reference_id=f"matrix_pos_{payout.matrix_position_id}_L{payout.level}",
        notes=f"{payout.system_type.value} L{payout.level} payout",
    )


def _process_sponsor_payout(db: Session, sp: PendingSponsorPayout) -> None:
    """
    Credit the 10% level-completion sponsor share to the owner's sponsor.

    An inactive / missing sponsor is treated as "no sponsor" (consistent with Core
    routing): the share is retained by the platform as profit. The level residual
    already excludes this amount on the assumption a sponsor receives it, so when
    there is no sponsor it MUST be booked as platform profit to keep the books
    balanced.
    """
    owner = db.query(User).filter_by(id=sp.owner_user_id).first()
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
            agent_tier=sp.agent_tier,
            gross_amount=sp.amount,
            tx_type=TransactionType.SPONSOR_MILESTONE_INCOME,
            reference_id=f"sponsor_share_pos_{sp.matrix_position_id}_L{sp.level}",
            notes=f"{sp.system_type.value} L{sp.level} sponsor share",
        )
    else:
        db.add(Transaction(
            user_id=sp.owner_user_id,
            agent_tier=sp.agent_tier,
            transaction_type=TransactionType.PLATFORM_PROFIT,
            amount=Decimal(str(sp.amount)),
            reference_id=f"sponsor_orphan_pos_{sp.matrix_position_id}_L{sp.level}",
            notes=f"{sp.system_type.value} L{sp.level} sponsor share — no active sponsor, retained by platform",
        ))


def _place_reentry(
    db: Session, payout: PendingPayout
) -> tuple[list[PendingPayout], list[PendingSponsorPayout]]:
    """
    Place the re-entries granted by one completed level. Stream → DUMMY back into
    the same tier's Stream queue; Boost → REAL into the single Boost queue.
    Returns any payouts / sponsor shares the placements newly trigger.
    """
    new_payouts: list[PendingPayout] = []
    new_sponsors: list[PendingSponsorPayout] = []
    is_stream = payout.system_type == SystemType.STREAM
    for _ in range(payout.reentry_count):
        if is_stream:
            _, p, s = place_in_matrix(
                db, payout.user_id, payout.agent_tier, SystemType.STREAM, is_dummy=True
            )
        else:
            _, p, s = place_in_matrix(
                db, payout.user_id, BOOST_TIER, SystemType.BOOST, is_dummy=False
            )
        new_payouts.extend(p)
        new_sponsors.extend(s)
    return new_payouts, new_sponsors


def run_purchase_matrices(db: Session, buyer_id: int, agent_tier: int) -> dict:
    """
    Run the Stream + Boost matrix placement and full payout cascade for one
    purchase. Flushes within the caller's transaction; does NOT commit.

    Returns a small summary dict for logging.
    """
    payouts: list[PendingPayout] = []
    sponsors: list[PendingSponsorPayout] = []

    # Initial placements: Stream in the buyer's tier, Boost in the global queue.
    _, p, s = place_in_matrix(db, buyer_id, agent_tier, SystemType.STREAM)
    payouts.extend(p)
    sponsors.extend(s)
    _, p, s = place_in_matrix(db, buyer_id, BOOST_TIER, SystemType.BOOST)
    payouts.extend(p)
    sponsors.extend(s)

    # Drain level-completion payouts, cascading through the re-entries they grant.
    paid = 0
    steps = 0
    while payouts:
        steps += 1
        if steps > _MAX_PAYOUT_STEPS:
            logger.error(
                "run_purchase_matrices: payout cascade exceeded %d steps for buyer=%s tier=%s — "
                "stopping (possible loop); %d payouts left unprocessed.",
                _MAX_PAYOUT_STEPS, buyer_id, agent_tier, len(payouts),
            )
            break
        payout = payouts.pop(0)
        _credit_matrix_payout(db, payout)
        paid += 1
        new_payouts, new_sponsors = _place_reentry(db, payout)
        payouts.extend(new_payouts)
        sponsors.extend(new_sponsors)

    # Sponsor shares (collected across the whole cascade) are paid last.
    for sp in sponsors:
        _process_sponsor_payout(db, sp)

    db.flush()
    summary = {"payouts": paid, "sponsor_shares": len(sponsors)}
    logger.info(
        "run_purchase_matrices: buyer=%s tier=%s → %d level payouts, %d sponsor shares",
        buyer_id, agent_tier, paid, len(sponsors),
    )
    return summary
