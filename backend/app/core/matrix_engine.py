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

Per-joiner incremental payouts (client-confirmed correction — NOT a lump sum at
threshold): a level's `wallet_amount` is not credited in one shot when the head
is paid. It's delivered as `payout_join_count` separate credits — one the
INSTANT each contributing brand-new joiner arrives — where `payout_join_count
= wallet_amount / reentry_amount` (a fixed integer per level: 2/5/13 for
Stream L1/L2/L3, 2/5/12 for Boost L1/L2/L3). E.g. Stream L1 (threshold 3,
payout_join_count 2): the 1st new joiner's arrival credits $1 to the head
immediately, the 2nd joiner's arrival credits another $1 immediately, and the
3rd (threshold-completing) joiner's arrival pays nothing itself — it pops the
head and creates its 1 re-entry instead. The head's succession is still purely
FIFO: whoever was next in queue position becomes the new head, not whichever
joiner happened to arrive last. Level completion — the head pop, re-entry
creation, sponsor share, and platform residual — still triggers at exactly the
same brand-new-join count as before (`required_total`); only the *wallet_amount
portion* moved from "one credit at completion" to "N credits, one per
contributing joiner, before completion." Re-entry creation itself stays a
single batch at completion (not incremental) — spreading it out was not part
of the client's ask, and batching preserves the self-bounding argument above.

`payout_join_count` only counts REAL joins — a re-entry filling a queue slot
NEVER itself triggers a payout (it didn't bring in a real dollar; crediting the
head for one would manufacture money from nothing) and is invisible to the
counter entirely, tracked via `MatrixLevelQueue.real_joins_since_head` (see
that column's docstring). This matters starting from a queue's SECOND head
onward: that head's first queued slot is always its predecessor's re-entry
(created immediately on completion, before any other purchase can reach this
level's locked queue row), so counting raw queue positions instead of real
joins would under-pay every subsequent head by `reentry_count` real joins.

Boost payouts (and Boost's L2/L3 sponsor-share bonus) skip the 70/20/10 wallet
split entirely (client-confirmed correction) — the full amount goes straight
to the recipient's MAIN wallet, no software fee, no repurchase reserve. Only
Stream keeps the 70/20/10 split. This module doesn't apply either split itself
(see the module-level note below); it only decides the amounts.

This module is pure/synchronous — it mutates rows and RETURNS the pending
payouts/sponsor-shares/re-entries; it does NOT credit wallets (the runtime
layer does that, via the durable backlog — see matrix_runtime.py, which is
also where the Stream-vs-Boost 70/20/10-vs-100% split is actually applied).
Must run inside an active transaction, does NOT commit.
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
    # Number of brand-new joiners whose individual arrival each pays out
    # reentry_amount immediately — wallet_amount / reentry_amount, always an
    # exact integer. Always < threshold (the remaining joiners between this
    # and threshold fund the re-entries + sponsor share + platform residual,
    # none of which pay the joiner themselves).
    payout_join_count: int
    # Extra 10% paid to the owner's sponsor on level completion (base amount —
    # scaled by tier_multiplier at runtime; Boost is always ×1).
    sponsor_on_completion: Decimal = Decimal("0")


PAYOUT_CONFIG: dict[SystemType, dict[int, LevelConfig]] = {
    SystemType.STREAM: {
        1: LevelConfig(threshold=3, wallet_amount=Decimal("2.00"),
                       reentry_amount=Decimal("1.00"), reentry_count=1,
                       payout_join_count=2),
        2: LevelConfig(threshold=9, wallet_amount=Decimal("5.00"),
                       reentry_amount=Decimal("1.00"), reentry_count=3,
                       payout_join_count=5,
                       sponsor_on_completion=Decimal("0.90")),
        3: LevelConfig(threshold=27, wallet_amount=Decimal("13.00"),
                       reentry_amount=Decimal("1.00"), reentry_count=9,
                       payout_join_count=13,
                       sponsor_on_completion=Decimal("2.70")),
    },
    SystemType.BOOST: {
        1: LevelConfig(threshold=3, wallet_amount=Decimal("0.60"),
                       reentry_amount=Decimal("0.30"), reentry_count=1,
                       payout_join_count=2),
        2: LevelConfig(threshold=9, wallet_amount=Decimal("1.50"),
                       reentry_amount=Decimal("0.30"), reentry_count=3,
                       payout_join_count=5,
                       sponsor_on_completion=Decimal("0.27")),
        3: LevelConfig(threshold=27, wallet_amount=Decimal("3.60"),
                       reentry_amount=Decimal("0.30"), reentry_count=9,
                       payout_join_count=12,
                       sponsor_on_completion=Decimal("0.81")),
    },
}


def tier_multiplier(agent_tier: int) -> Decimal:
    return Decimal(str(AGENT_TIER_PRICES[agent_tier])) / Decimal("10")


@dataclass
class PendingPayout:
    """
    One INCREMENTAL payout: triggered the instant a single contributing joiner
    arrives (not at level completion — see module docstring). `matrix_position_id`
    is that JOINER's own MatrixQueueSlot.id (not the head's), so every increment
    gets a distinct reference at credit time; `user_id` is the current HEAD who
    actually receives the credit.
    """
    matrix_position_id: int   # the joining slot that triggered this increment
    user_id: int              # the current head — who gets credited
    agent_tier: int
    system_type: SystemType
    level: int
    wallet_amount: Decimal    # this increment's amount (reentry_amount * multiplier)


@dataclass
class PendingSponsorPayout:
    """Triggered when a level completes and its owner's sponsor is owed 10%."""
    matrix_position_id: int
    owner_user_id: int   # The paid slot's owner (their sponsor gets paid)
    agent_tier: int
    system_type: SystemType
    level: int
    amount: Decimal      # Amount to credit to owner's sponsor


@dataclass
class PendingReentry:
    """
    Triggered when a level completes: spawn its `reentry_count` re-entries for
    the just-paid head. Never credits a wallet — purely a queue-placement event.
    """
    matrix_position_id: int   # the completed head's slot id (reference only)
    owner_user_id: int        # who re-enters (the just-paid head)
    agent_tier: int
    system_type: SystemType
    level: int
    reentry_amount: Decimal
    reentry_count: int


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
    level: int, is_dummy: bool, is_reentry: bool = False,
) -> tuple[list[PendingPayout], list[PendingSponsorPayout], list[PendingReentry]]:
    """
    Append one slot to (agent_tier, system_type, level)'s own queue. Returns
    (payouts, sponsor_payouts, reentries).

    Two independent things can happen for a single appended slot — never both,
    since payout_join_count < threshold always (see LevelConfig):

    1. INCREMENTAL PAYOUT — if this slot is one of the head's first
       `payout_join_count` brand-new joins, its arrival immediately pays
       `reentry_amount` to the CURRENT head (module docstring: per-joiner
       incremental crediting, not a lump sum at completion).
    2. LEVEL COMPLETION — if this slot is the `threshold`-th brand-new join,
       the head is popped, its re-entries are queued, its sponsor share (if
       any) is queued, and any leftover pool residual is booked as platform
       profit. Per the spec's own worked example ("1st member gets payment
       from 2nd,3rd,4th... popped... 2nd member: 5th,6th,7th will pay"), each
       successive head needs `threshold` BRAND NEW joins counted from when it
       became head — NOT merely "however many people happen to already be
       sitting in the queue". So completion #k (0-indexed by head_position - 1)
       requires the cumulative join count to reach `1 + threshold * (k + 1)`
       — this is what `total_joined >= 1 + threshold * completions_so_far`
       checks below. A naive `next_position - head_position >= threshold`
       check double-counts already-queued members across consecutive
       completions and runs away. Looped (not `if`) purely for defensive
       correctness in case of any bulk/edge-case gap — in practice at most one
       completion is possible per single appended slot.
    """
    q = _get_or_create_queue(db, agent_tier, system_type, level)
    pos_num = q.next_position
    q.next_position += 1
    new_slot = MatrixQueueSlot(
        agent_tier=agent_tier, system_type=system_type, level=level,
        position_number=pos_num, user_id=user_id, is_dummy=is_dummy,
        is_reentry=is_reentry,
    )
    db.add(new_slot)
    db.flush()

    cfg = PAYOUT_CONFIG[system_type][level]
    multiplier = tier_multiplier(agent_tier)
    payouts: list[PendingPayout] = []
    sponsors: list[PendingSponsorPayout] = []
    reentries: list[PendingReentry] = []

    # Only REAL joins can trigger an incremental payout — re-entries must never
    # manufacture a credit for themselves (they didn't bring in a real dollar;
    # see MatrixLevelQueue.real_joins_since_head's docstring for why this
    # can't be derived from pos_num/head_position alone). And a join can never
    # pay ITSELF: pos_num == q.head_position only when this slot is the very
    # first ever created for this queue (head_position defaults to 1 on a
    # fresh queue, matching position 1) — there's no existing head yet to pay,
    # this new slot IS about to become the head. Every later join always has
    # pos_num > head_position (the head is always something already sitting
    # in the queue, never the slot currently being appended).
    if not is_reentry and pos_num != q.head_position:
        q.real_joins_since_head += 1
        if q.real_joins_since_head <= cfg.payout_join_count:
            head_slot = (
                db.query(MatrixQueueSlot)
                .filter_by(agent_tier=agent_tier, system_type=system_type, level=level,
                           position_number=q.head_position)
                .with_for_update()
                .first()
            )
            if head_slot is not None and not head_slot.is_dummy:
                payouts.append(PendingPayout(
                    matrix_position_id=new_slot.id,
                    user_id=head_slot.user_id,
                    agent_tier=agent_tier,
                    system_type=system_type,
                    level=level,
                    wallet_amount=cfg.reentry_amount * multiplier,
                ))

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
        # Fresh count for whoever's head next — see real_joins_since_head's
        # docstring. Reset unconditionally, even if the old head was dummy.
        q.real_joins_since_head = 0
        db.flush()
        if head_slot is None:
            continue  # defensive: should never happen, positions are contiguous

        # Dummy positions (Stream re-entries) fill slots for others but don't
        # earn wallet payouts or spawn further re-entries themselves.
        if head_slot.is_dummy:
            continue

        # wallet_amount was already delivered incrementally above, one credit
        # per contributing joiner — nothing further to pay the head here.

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

        if cfg.reentry_count > 0:
            reentries.append(PendingReentry(
                matrix_position_id=head_slot.id,
                owner_user_id=head_slot.user_id,
                agent_tier=agent_tier,
                system_type=system_type,
                level=level,
                reentry_amount=cfg.reentry_amount * multiplier,
                reentry_count=cfg.reentry_count,
            ))

    return payouts, sponsors, reentries


def place_real_join(
    db: Session, user_id: int, agent_tier: int, system_type: SystemType,
) -> tuple[list[PendingPayout], list[PendingSponsorPayout], list[PendingReentry]]:
    """
    A real purchase's placement: adds one entry to ALL THREE level-queues
    (L1/L2/L3) for this tier+system at once — a member's downline growth
    counts toward every level simultaneously. Returns (payouts, sponsors, reentries).
    """
    payouts: list[PendingPayout] = []
    sponsors: list[PendingSponsorPayout] = []
    reentries: list[PendingReentry] = []
    for level in (1, 2, 3):
        p, s, r = _append_to_level(db, user_id, agent_tier, system_type, level, is_dummy=False)
        payouts.extend(p)
        sponsors.extend(s)
        reentries.extend(r)
    return payouts, sponsors, reentries


def place_level_reentry(
    db: Session, user_id: int, agent_tier: int, system_type: SystemType,
    level: int, is_dummy: bool,
) -> tuple[list[PendingPayout], list[PendingSponsorPayout], list[PendingReentry]]:
    """
    A re-entry granted by a level completion: feeds back into ONLY that same
    level's own queue — the key difference from a real join, and what keeps
    the whole system bounded (see module docstring).
    """
    return _append_to_level(db, user_id, agent_tier, system_type, level, is_dummy, is_reentry=True)
