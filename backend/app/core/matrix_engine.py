"""
3-level independent FIFO Queue Engine — shared by the Stream and Boost Agent
systems.

This implements the client's exact "How matrix (Queue system) work?" spec, not
a shared ancestor tree. Each (agent_tier, system_type) runs THREE SEPARATE
queues — one per level (L1/L2/L3) — and each is a plain FIFO line:

    Position 1 (the head) is paid once the NEXT `threshold` members join that
    SAME level's queue behind them (L1: 3, L2: 9, L3: 27), then pops out. The
    new head is whoever was next in line — "likewise, it goes through."
    ("1st member get payment from their downline 2nd, 3rd and 4th members in
    the queue. Once he/she gets payment he/she will be popped out of the
    queue. And the 2nd member come up to receive his payment...")

A real purchase adds ONE entry to ALL THREE of its tier's level-queues at
once — a member's downline growth counts toward L1, L2, and L3 simultaneously,
which is the "3 x 3" of the spec. The re-entries a level-completion grants,
however, feed back ONLY into that SAME level's own queue — matching the spec's
diagram, where each level's re-entry count is drawn directly under its own
box ("L1 ReBirth", "L2 ReBirth", "L3 ReBirth" are each attached to their own
level, never pooled).

That distinction is also what keeps the system economically bounded: at every
level, reentry_count / threshold is exactly 1/3 (1 of 3, 3 of 9, 9 of 27) — a
contracting geometric series when a level's re-entries only feed themselves
back (each level's total queue size converges to 1.5x its real-purchase count,
see the stability note below). The previous implementation used one shared
ancestor tree where a single new join could simultaneously complete all three
levels for its parent/grandparent/great-grandparent at once, feeding real
re-entries back into a shared structure that could trigger further multi-level
completions — that's exactly critical (1/3 summed across 3 levels = 1), and in
testing produced 2,985+ payouts (still climbing) from a single purchase, from a
Boost pool that had collected only cents. This redesign fixes that at the root
instead of just rate-limiting it — see matrix_runtime.py for the durable
backlog that still bounds per-request latency as defense-in-depth.

Payout amounts (unchanged from the client spec — Agent 1 / $10 base; higher
Stream tiers scale wallet/re-entry $ amounts by tier_multiplier; re-entry COUNT
stays fixed at 1/3/9 across tiers):

  Stream Agent  L1: $2.00 wallet + $1.00 re-entry ×1            (no sponsor share)
                L2: $5.00 wallet + $1.00 re-entries ×3          sponsor $0.90 (10% of $9)
                L3: $13.00 wallet + $1.00 re-entries ×9         sponsor $2.70 (10% of $27)
  Boost Agent   L1: $0.60 wallet + $0.30 re-entry ×1            (no sponsor share)
                L2: $1.50 wallet + $0.30 re-entries ×3          sponsor $0.27 (10% of $2.70)
                L3: $3.60 wallet + $0.30 re-entries ×9          sponsor $0.81 (10% of $8.10)
  (remaining level pool after payout + re-entries + sponsor share → platform profit)

Boost Agent uses a SINGLE global queue set (agent_tier=1 for all tiers). Boost
re-entries are REAL (eligible to be paid themselves later); Stream re-entries
are DUMMY (fill a slot to keep the queue moving, earn nothing, and — per spec —
spawn no further re-entries themselves: "All Re-entries instances should be
placed as dummy ones. It will not receive any income.").

This module is pure/synchronous — it mutates rows and RETURNS the pending
payouts; it does NOT credit wallets (the runtime layer does that, via the
durable backlog — see matrix_runtime.py). Must run inside an active
transaction, does NOT commit.
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.agent import AGENT_TIER_PRICES
from app.models.matrix import MatrixLevelQueue, MatrixQueueSlot, SystemType
from app.models.transaction import Transaction, TransactionType


@dataclass
class LevelConfig:
    threshold: int
    wallet_amount: Decimal
    reentry_amount: Decimal
    reentry_count: int          # Fixed across tiers (Stream + Boost both)
    # Extra 10% paid to the owner's sponsor on level completion (base amount —
    # scaled by tier_multiplier at runtime; Boost is always ×1).
    sponsor_on_completion: Decimal = Decimal("0")


PAYOUT_CONFIG: dict[SystemType, dict[int, LevelConfig]] = {
    SystemType.STREAM: {
        1: LevelConfig(threshold=3, wallet_amount=Decimal("2.00"),
                       reentry_amount=Decimal("1.00"), reentry_count=1),
        2: LevelConfig(threshold=9, wallet_amount=Decimal("5.00"),
                       reentry_amount=Decimal("1.00"), reentry_count=3,
                       sponsor_on_completion=Decimal("0.90")),
        3: LevelConfig(threshold=27, wallet_amount=Decimal("13.00"),
                       reentry_amount=Decimal("1.00"), reentry_count=9,
                       sponsor_on_completion=Decimal("2.70")),
    },
    SystemType.BOOST: {
        1: LevelConfig(threshold=3, wallet_amount=Decimal("0.60"),
                       reentry_amount=Decimal("0.30"), reentry_count=1),
        2: LevelConfig(threshold=9, wallet_amount=Decimal("1.50"),
                       reentry_amount=Decimal("0.30"), reentry_count=3,
                       sponsor_on_completion=Decimal("0.27")),
        3: LevelConfig(threshold=27, wallet_amount=Decimal("3.60"),
                       reentry_amount=Decimal("0.30"), reentry_count=9,
                       sponsor_on_completion=Decimal("0.81")),
    },
}


def tier_multiplier(agent_tier: int) -> Decimal:
    return Decimal(str(AGENT_TIER_PRICES[agent_tier])) / Decimal("10")


@dataclass
class PendingPayout:
    """Triggered when a level's queue head is paid (its threshold reached)."""
    matrix_position_id: int   # MatrixQueueSlot.id of the paid slot (reference only)
    user_id: int
    agent_tier: int
    system_type: SystemType
    level: int
    wallet_amount: Decimal
    reentry_amount: Decimal
    reentry_count: int


@dataclass
class PendingSponsorPayout:
    """Triggered when a level completes and its owner's sponsor is owed 10%."""
    matrix_position_id: int
    owner_user_id: int   # The paid slot's owner (their sponsor gets paid)
    agent_tier: int
    system_type: SystemType
    level: int
    amount: Decimal      # Amount to credit to owner's sponsor


def _get_or_create_queue(
    db: Session, agent_tier: int, system_type: SystemType, level: int
) -> MatrixLevelQueue:
    q = (
        db.query(MatrixLevelQueue)
        .filter_by(agent_tier=agent_tier, system_type=system_type, level=level)
        .with_for_update()
        .first()
    )
    if not q:
        q = MatrixLevelQueue(
            agent_tier=agent_tier, system_type=system_type, level=level,
            head_position=1, next_position=1,
        )
        db.add(q)
        db.flush()
    return q


def _append_to_level(
    db: Session, user_id: int, agent_tier: int, system_type: SystemType,
    level: int, is_dummy: bool,
) -> tuple[list[PendingPayout], list[PendingSponsorPayout]]:
    """
    Append one slot to (agent_tier, system_type, level)'s own queue, then drain
    any completions this triggers (normally 0 or 1; looped for correctness in
    case of any bulk/edge-case gap). Returns (payouts, sponsor_payouts).

    Completion check: per the spec's own worked example ("1st member gets
    payment from 2nd,3rd,4th... popped... 2nd member: 5th,6th,7th will pay"),
    each successive head needs `threshold` BRAND NEW joins counted from when it
    became head — NOT merely "however many people happen to already be sitting
    in the queue". Position 3/4 already existed by the time position 1 was
    paid; they do NOT also count toward position 2's threshold. So completion
    #k (0-indexed by head_position - 1) requires the cumulative join count to
    reach `1 + threshold * (k + 1)` — this is what
    `total_joined >= 1 + threshold * completions_so_far` checks below. A naive
    `next_position - head_position >= threshold` check double-counts already-
    queued members across consecutive completions and runs away.
    """
    q = _get_or_create_queue(db, agent_tier, system_type, level)
    pos_num = q.next_position
    q.next_position += 1
    db.add(MatrixQueueSlot(
        agent_tier=agent_tier, system_type=system_type, level=level,
        position_number=pos_num, user_id=user_id, is_dummy=is_dummy,
    ))
    db.flush()

    cfg = PAYOUT_CONFIG[system_type][level]
    multiplier = tier_multiplier(agent_tier)
    payouts: list[PendingPayout] = []
    sponsors: list[PendingSponsorPayout] = []

    while True:
        total_joined = q.next_position - 1
        completions_so_far = q.head_position - 1
        required_total = 1 + cfg.threshold * (completions_so_far + 1)
        if total_joined < required_total:
            break
        head_slot = (
            db.query(MatrixQueueSlot)
            .filter_by(agent_tier=agent_tier, system_type=system_type, level=level,
                       position_number=q.head_position)
            .with_for_update()
            .first()
        )
        q.head_position += 1
        db.flush()
        if head_slot is None:
            continue  # defensive: should never happen, positions are contiguous

        # Dummy positions (Stream re-entries) fill slots for others but don't
        # earn wallet payouts or spawn further re-entries themselves.
        if head_slot.is_dummy:
            continue

        payouts.append(PendingPayout(
            matrix_position_id=head_slot.id,
            user_id=head_slot.user_id,
            agent_tier=agent_tier,
            system_type=system_type,
            level=level,
            wallet_amount=cfg.wallet_amount * multiplier,
            reentry_amount=cfg.reentry_amount * multiplier,
            reentry_count=cfg.reentry_count,
        ))

        # Realized platform profit = the level's leftover pool after the
        # wallet payout, re-entries, and sponsor share. reentry_amount is
        # each member's per-level contribution, so level gross =
        # threshold × reentry_amount.
        residual = (
            cfg.threshold * cfg.reentry_amount
            - cfg.wallet_amount
            - cfg.reentry_count * cfg.reentry_amount
            - cfg.sponsor_on_completion
        ) * multiplier
        if residual > 0:
            db.add(Transaction(
                user_id=head_slot.user_id,
                agent_tier=agent_tier,
                transaction_type=TransactionType.PLATFORM_PROFIT,
                amount=residual,
                reference_id=f"residual_{system_type.value}_t{agent_tier}_slot{head_slot.id}_L{level}",
                notes=f"{system_type.value} L{level} level residual → platform",
            ))

        # L2/L3: 10% extra to owner's sponsor on level completion (paid from
        # the pool, not deducted from the owner's wallet).
        if cfg.sponsor_on_completion > 0:
            sponsors.append(PendingSponsorPayout(
                matrix_position_id=head_slot.id,
                owner_user_id=head_slot.user_id,
                agent_tier=agent_tier,
                system_type=system_type,
                level=level,
                amount=cfg.sponsor_on_completion * multiplier,
            ))

    return payouts, sponsors


def place_real_join(
    db: Session, user_id: int, agent_tier: int, system_type: SystemType,
) -> tuple[list[PendingPayout], list[PendingSponsorPayout]]:
    """
    A real purchase's placement: adds one entry to ALL THREE level-queues
    (L1/L2/L3) for this tier+system at once — a member's downline growth
    counts toward every level simultaneously. Returns (payouts, sponsors).
    """
    payouts: list[PendingPayout] = []
    sponsors: list[PendingSponsorPayout] = []
    for level in (1, 2, 3):
        p, s = _append_to_level(db, user_id, agent_tier, system_type, level, is_dummy=False)
        payouts.extend(p)
        sponsors.extend(s)
    return payouts, sponsors


def place_level_reentry(
    db: Session, user_id: int, agent_tier: int, system_type: SystemType,
    level: int, is_dummy: bool,
) -> tuple[list[PendingPayout], list[PendingSponsorPayout]]:
    """
    A re-entry granted by a level completion: feeds back into ONLY that same
    level's own queue — the key difference from a real join, and what keeps
    the whole system bounded (see module docstring).
    """
    return _append_to_level(db, user_id, agent_tier, system_type, level, is_dummy)
