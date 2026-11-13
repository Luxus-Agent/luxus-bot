"""
Synchronous driver for the Stream / Boost matrix engine.

This replaces the removed Celery task chain (workers/tasks.py) with an in-request,
fully synchronous run. On a confirmed purchase it:

  1. places the buyer as a real join in ONLY L1 of the Stream queue (their
     tier) and the Boost queue (global, tier 1 — but sized by the buyer's OWN
     purchased tier via `contribution_tier`, so a Growth-tier joiner funds a
     bigger Boost credit than a Trial-tier joiner in that same shared queue),
     per matrix_engine.place_real_join — a member no longer starts in L2/L3
     simultaneously (client-confirmed correction, 2026-08-06); they GRADUATE
     there only when their own L1/L2 position completes (see step 2),
  2. queues every incremental payout and level-completion sponsor-share this
     triggers into the durable MatrixPendingPayout backlog, then drains up to
     _MAX_STEPS_PER_CALL items from that backlog (oldest first, across ALL
     users/tiers — not just this buyer's own): payouts and sponsor shares
     settle INSTANTLY ON-CHAIN when possible (_settle_or_credit — Stream sends
     70% straight to the recipient's wallet via onchain.
     send_matrix_payout_settlement, 20%/10% still booked internally via
     wallet_ops.mirror_onchain_earning_split; Boost sends 90% for a position
     holder's own payout — the 10% software fee stays internal, via
     wallet_ops.mirror_onchain_boost_split — or the full 100% for its
     sponsor-share bonus, which is never fee-reduced), falling back to
     internal-only crediting (credit_wallet / credit_boost_wallet /
     credit_main_wallet_direct) whenever settlement isn't possible — feature
     disabled, no wallet address on file, or the broadcast failed. GRADUATE
     rows place that same completing head as one brand-new real join in the
     level above (matrix_engine.place_graduation — L3 has no level above, so
     its completions only spawn re-entries). A level's re-entries are NOT
     enqueued here — they drip out inline, one per 3 subsequent real joins,
     straight from matrix_engine._append_to_level itself (client-confirmed
     correction, 2026-08-06 — see that module's docstring), and
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
    PendingGraduation,
    PendingPayout,
    PendingReentry,
    PendingSponsorPayout,
    place_graduation,
    place_real_join,
)
from app.core.onchain import send_matrix_payout_settlement
from app.core.wallet_ops import (
    credit_boost_wallet,
    credit_main_wallet_direct,
    credit_wallet,
    mirror_onchain_boost_split,
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


def _enqueue_graduation(db: Session, g: PendingGraduation) -> None:
    db.add(MatrixPendingPayout(
        kind=PendingKind.GRADUATE,
        matrix_position_id=g.matrix_position_id,
        owner_user_id=g.owner_user_id,
        agent_tier=g.agent_tier,
        system_type=g.system_type,
        level=g.level,
        amount=Decimal("0"),
        contribution_tier=g.contribution_tier,
    ))


def _enqueue_all(
    db: Session,
    payouts: list[PendingPayout],
    sponsors: list[PendingSponsorPayout],
    reentries: list[PendingReentry],
    graduations: list[PendingGraduation],
) -> None:
    # `reentries` is informational-only now (see PendingReentry's docstring —
    # a level's re-entries drip out inline from matrix_engine._append_to_level
    # itself, they're never queued here).
    for p in payouts:
        _enqueue_payout(db, p)
    for sp in sponsors:
        _enqueue_sponsor(db, sp)
    for g in graduations:
        _enqueue_graduation(db, g)


def _settle_or_credit(
    db: Session,
    owner: User,
    agent_tier: int,
    system_type: SystemType,
    gross_amount: Decimal,
    tx_type: TransactionType,
    reference_id: str,
    notes: str,
    boost_fee: bool = False,
    settlement_key: str | None = None,
) -> None:
    """
    Instant on-chain settlement, falling back to internal-only crediting
    exactly as before this feature existed. Shared by both a matrix payout's
    own head credit and its sponsor-share bonus — same rule either way, only
    who `owner` is (and, for Boost, `boost_fee`) differs.

    Attempts to broadcast straight to `owner`'s own wallet: Stream sends only
    its 70% share (20%/10% stay internal, booked via mirror_onchain_earning_split
    — the exact function Core already uses for the same "70% already paid
    on-chain, don't double-credit MAIN" bookkeeping); Boost sends 90% when
    `boost_fee` is set (a position holder's own payout — the 10% software fee
    stays internal, booked via mirror_onchain_boost_split) or the full 100%
    when it isn't (a sponsor-share bonus — paid in addition, never
    fee-reduced). On success the headline ledger row records the FULL gross
    amount (per the existing "Total Earnings shows gross" convention) with
    its own `tx_hash`.

    Falls back to today's fully-internal crediting (credit_wallet /
    credit_boost_wallet / credit_main_wallet_direct, no tx_hash) whenever
    settlement isn't possible: PLATFORM_FEE_SIGNER_PRIVATE_KEY unset (feature
    disabled), the owner has no wallet address on file, or the broadcast
    itself fails — send_matrix_payout_settlement is best-effort and never
    raises, so this fallback is unconditional on tx_hash being falsy, not a
    caught exception.
    """
    address = resolve_payout_address(db, owner)
    tx_hash = None
    if address:
        if system_type == SystemType.BOOST:
            onchain_share = gross_amount * Decimal("0.90") if boost_fee else gross_amount
        else:
            onchain_share = gross_amount * Decimal("0.70")
        # `settlement_key` makes the broadcast idempotent: if this request is
        # retried after a rollback, the original tx hash is reused, never re-sent.
        tx_hash = send_matrix_payout_settlement(onchain_share, address, reference_id, settlement_key)

    if tx_hash:
        if system_type == SystemType.STREAM:
            mirror_onchain_earning_split(db, owner.id, agent_tier, gross_amount)
        elif boost_fee:
            mirror_onchain_boost_split(db, owner.id, agent_tier, gross_amount)
        # Boost sponsor share: nothing further to book internally — 100% just went on-chain.
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
        if boost_fee:
            credit_boost_wallet(
                db=db, user_id=owner.id, agent_tier=agent_tier, gross_amount=gross_amount,
                tx_type=tx_type, reference_id=reference_id, notes=notes,
            )
        else:
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
        boost_fee=row.system_type == SystemType.BOOST,
        settlement_key=f"matrix_row_{row.id}",
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
            settlement_key=f"matrix_row_{row.id}",
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


def _spawn_graduation(db: Session, row: MatrixPendingPayout) -> None:
    """
    Place the completing head as one brand-new real join in the NEXT level up
    (`row.level` is already the destination level — see PendingGraduation).
    Never touches a wallet. Whatever further payouts/sponsors/reentries/
    graduations this itself triggers are re-enqueued, not processed inline.
    """
    p, s, r, g = place_graduation(
        db, row.owner_user_id, row.agent_tier, row.system_type, row.level,
        contribution_tier=row.contribution_tier or row.agent_tier,
    )
    _enqueue_all(db, p, s, r, g)


def _next_backlog_row(db: Session) -> MatrixPendingPayout | None:
    """Oldest pending item, locked so concurrent purchases don't double-process it."""
    return (
        db.query(MatrixPendingPayout)
        .order_by(MatrixPendingPayout.id.asc())
        .with_for_update(skip_locked=True)
        .first()
    )


def drain_matrix_backlog(db: Session, max_steps: int = _MAX_STEPS_PER_CALL, commit_each: bool = False) -> int:
    """
    Process up to `max_steps` durable backlog rows (oldest first, across every
    user/tier/system): PAYOUT rows credit one incremental joiner-triggered
    amount, SPONSOR rows credit a level-completion sponsor share, and
    GRADUATE rows place the completing head as one brand-new real join in the
    NEXT level up (which itself gets queued, not processed inline, so this
    stays a flat loop bounded by max_steps — not recursion). A level's
    re-entries never appear here — they drip out inline from matrix_engine.
    _append_to_level itself (see PendingKind.REENTRY's docstring).

    `commit_each=True` commits after EVERY row, so the on-chain broadcast a row
    may make is committed together with its ledger rows and the row's deletion.
    A later failure can then never roll back an already-broadcast payout and
    leave its backlog row behind to be paid a second time. If one row fails it
    is rolled back on its own (its broadcast, if any, is reused on the next
    attempt via the settlement key) and draining stops, leaving the rest queued.
    Returns the number of rows processed. With commit_each=False it only
    flushes (caller owns the commit) and exceptions propagate.
    """
    processed = 0
    while processed < max_steps:
        row = _next_backlog_row(db)
        if row is None:
            break

        try:
            if row.kind == PendingKind.PAYOUT:
                _credit_row_payout(db, row)
            elif row.kind == PendingKind.GRADUATE:
                _spawn_graduation(db, row)
            else:
                _credit_row_sponsor(db, row)

            db.delete(row)
            db.flush()
            if commit_each:
                db.commit()
        except Exception:
            if not commit_each:
                raise
            db.rollback()
            logger.exception(
                "drain_matrix_backlog: row %s failed — rolled back, left queued for the next purchase.",
                getattr(row, "id", "?"),
            )
            break
        processed += 1

    return processed


def place_purchase_in_matrices(db: Session, buyer_id: int, agent_tier: int) -> None:
    """
    Place the buyer as a real join in the Stream + Boost queues and queue
    whatever level completions that immediately triggers into the durable
    backlog. Moves NO money (no broadcast, no wallet credit) — it only writes
    queue/backlog rows, so it is safe to run inside the purchase's own atomic
    transaction. Flushes; does NOT commit.
    """
    p, s, r, g = place_real_join(db, buyer_id, agent_tier, SystemType.STREAM)
    _enqueue_all(db, p, s, r, g)
    # Boost's queue is still one shared global line (BOOST_TIER), but this
    # buyer's own purchased tier sizes what THEIR join contributes to it —
    # see matrix_engine._append_to_level's docstring.
    p, s, r, g = place_real_join(db, buyer_id, BOOST_TIER, SystemType.BOOST, contribution_tier=agent_tier)
    _enqueue_all(db, p, s, r, g)
    db.flush()


def run_purchase_matrices(db: Session, buyer_id: int, agent_tier: int, commit_each: bool = False) -> dict:
    """
    Place the buyer (place_purchase_in_matrices), then drain the durable backlog
    (this purchase's own work plus anything left over from earlier purchases)
    up to a bounded step budget. With the default commit_each=False this is the
    single-transaction path: everything flushes and the CALLER owns the commit.

    Anything that can broadcast on-chain should NOT use it. The money-safe
    production path is: place_purchase_in_matrices() inside the purchase's own
    transaction, commit, then drain_matrix_backlog(commit_each=True) — see
    distribution.pack_status and repurchase.sweep_auto_repurchases.
    Returns a small summary dict for logging.
    """
    place_purchase_in_matrices(db, buyer_id, agent_tier)

    processed = drain_matrix_backlog(db, commit_each=commit_each)

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
