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

A real purchase adds ONE entry to ONLY L1 of its tier's level-queues — members
do NOT start in L2/L3 simultaneously (client-confirmed correction, 2026-08-06;
previously all three levels filled at once — see git history for the earlier
"3 x 3 simultaneous" design if it needs revisiting). A member only REACHES L2
by GRADUATING there: when their own L1 position FULLY completes — which for
L2/L3 now means only after ALL of that level's `reentry_count` re-entry
milestones have already been placed for this same head, one per `threshold /
reentry_count` (always 3) total slot-fills since it became head (client-
confirmed correction, 2026-08-06: "dhanush will come L3 only after completing
3 re-entry in L2") — the SAME completing member is placed as one brand-new
real join in the level above (see `PendingGraduation` / `place_graduation`).
L2 → L3 works identically; L3 has no next level, so an L3 completion's final
re-entry milestone is the end of the line for that member. A dummy head
(Stream's re-entries) never gets a re-entry milestone or graduates — same as
it never earns anything (per spec).

The re-entries a level-completion grants feed back ONLY into that SAME level's
own queue — matching the spec's diagram, where each level's re-entry count is
drawn directly under its own box ("L1 ReBirth", "L2 ReBirth", "L3 ReBirth" are
each attached to their own level, never pooled). Graduation is the ONLY way a
member reaches L2/L3 now, so those levels' queues are composed entirely of
graduations plus that level's own re-entries — never a fresh purchase directly.

That re-entries-stay-in-their-own-level distinction is also what keeps the
system economically bounded: at every level, reentry_count / threshold is
exactly 1/3 (1 of 3, 3 of 9, 9 of 27) — a contracting geometric series when a
level's re-entries only feed themselves back (each level's total queue size
converges to 1.5x its real-purchase count, see the stability note below).
Graduation doesn't change this bound — it's a single 1-for-1 placement per
completion (not a multiplying re-entry count), so it can't runaway either. An
older implementation used one shared ancestor tree where a single new join
could simultaneously complete all three levels for its parent/grandparent/
great-grandparent at once, feeding real re-entries back into a shared
structure that could trigger further multi-level completions — that's exactly
critical (1/3 summed across 3 levels = 1), and in testing produced 2,985+
payouts (still climbing) from a single purchase, from a Boost pool that had
collected only cents. The queue-per-level redesign fixed that at the root
instead of just rate-limiting it — see matrix_runtime.py for the durable
backlog that still bounds per-request latency as defense-in-depth.

Payout amounts (Agent 1 / $10 base rates — each REAL join's own contribution
scales by ITS OWN purchased tier's `tier_multiplier`, not the queue's; re-entry
COUNT stays fixed at 1/3/9 across tiers):

  Stream Agent  L1: $2.00 wallet + $1.00 re-entry ×1            (no sponsor share)
                L2: $5.00 wallet + $1.00 re-entries ×3          sponsor $0.90 (10% of $9)
                L3: $13.00 wallet + $1.00 re-entries ×9         sponsor $2.70 (10% of $27)
  Boost Agent   L1: $0.60 wallet + $0.30 re-entry ×1            (no sponsor share)
                L2: $1.50 wallet + $0.30 re-entries ×3          sponsor $0.27 (10% of $2.70)
                L3: $3.60 wallet + $0.30 re-entries ×9          sponsor $0.81 (10% of $8.10)
  (remaining level pool after payout + re-entries + sponsor share → platform profit)

Boost Agent uses a SINGLE global queue set (`agent_tier` is always pinned to 1
for queue selection — one shared FIFO line across every purchased tier). Unlike
Stream, where the queue's own tier and every joiner's tier are the same thing,
a Boost queue's real joins can be a MIX of tiers — a Growth-tier ($100 base)
purchase funds a 10× bigger credit than a Trial-tier ($10 base) purchase, even
though both land in the same queue (`contribution_tier` param below — sized by
the actual buyer, decoupled from the queue's own fixed `agent_tier=1`). Because
a cycle's total contribution is no longer a fixed `threshold * reentry_amount *
multiplier`, level completion (sponsor share / re-entry cost / platform
residual) is computed from `MatrixLevelQueue.cycle_gross_accumulated` — the
cycle's ACTUAL running total — using the fixed reentry_count/threshold (1/3)
and sponsor (10%) RATIOS, which hold regardless of tier mix (see that column's
docstring). Boost re-entries are REAL (eligible to be paid themselves later,
same per-joiner-tier rule as any other head); Stream re-entries are DUMMY (fill
a slot to keep the queue moving, earn nothing, and — per spec — spawn no
further re-entries themselves: "All Re-entries instances should be placed as
dummy ones. It will not receive any income.").

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
joiner happened to arrive last. Level completion — the head pop, sponsor
share, and platform residual — still triggers at exactly the same
brand-new-join count as before (`required_total`); only the *wallet_amount
portion* moved from "one credit at completion" to "N credits, one per
contributing joiner, before completion."

Re-entry release is progressive, not a lump sum at completion (client-
confirmed correction, 2026-08-06: "d1,d2,d3 then dhanush does a re-entry,
then d4,d5 then another, then d6,d7 then another — 3 total for L2 — dhanush
will come L3 only after completing 3 re-entry in L2" — reversing an earlier
decision to batch all of a completion's re-entries together). A cycle's
`reentry_count` re-entries are granted ONE AT A TIME, DURING the same head's
own cycle — the 1st once `threshold / reentry_count` (always exactly 3, by
construction — see PAYOUT_CONFIG) total slot-fills (real joins AND
re-entries both count) have arrived since it became head, the 2nd once 3
more have arrived (a just-released re-entry counts as one of those 3 itself,
so every milestone after the first only needs `stride - 1` more REAL joins),
and so on. Because `threshold` is always exactly `reentry_count` strides,
the FINAL milestone of a cycle always lands on the exact same slot-fill as
full completion — the head's own re-entry quota finishes at the same instant
it pops and graduates, never before and never after. Each released re-entry
is itself an ordinary append (it goes through the exact same milestone/
completion checks as any other slot, so it can trigger a cascade of its
own). `MatrixQueueSlot.spawned_from_position` records which head's cycle
each re-entry was released for. See the "staggered re-entry release" section of
_append_to_level below for the exact mechanics.

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
from decimal import ROUND_HALF_UP, Decimal

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
    # Extra 10% paid to the owner's sponsor on level completion — this is the
    # Agent-1/tier-1 baseline dollar amount; _append_to_level derives the
    # underlying 10% RATE from it (sponsor_on_completion / (threshold *
    # reentry_amount)) and applies that rate to the cycle's ACTUAL gross, so
    # it comes out correctly even when a Boost cycle mixes tiers.
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
    INFORMATIONAL ONLY (client-confirmed correction, 2026-08-06) — represents
    ONE re-entry milestone release (not a whole completion's worth). A head's
    cycle grants `reentry_count` of these, one at a time, DURING the cycle —
    the LAST one coincides with the head's own full completion, the earlier
    ones happen mid-cycle (see _append_to_level's "staggered re-entry
    release" section / the module docstring). This dataclass is still
    returned by _append_to_level purely so callers (matrix_runtime.
    run_purchase_matrices) can log/summarize that a release happened —
    nothing enqueues it as durable backlog work; the placement already
    happened inline, synchronously, within _append_to_level itself, via the
    recursive place_level_reentry call that produced it.
    """
    matrix_position_id: int   # the current head's slot id (reference only)
    owner_user_id: int        # who re-enters (the CURRENT head, mid-cycle or completing)
    agent_tier: int
    system_type: SystemType
    level: int
    reentry_amount: Decimal
    reentry_count: int        # always 1 — this release, not the cycle's total quota
    # The tier of whichever join's arrival triggered THIS SPECIFIC milestone
    # — carried forward as this re-entry's own value (client-confirmed
    # correction, 2026-08-06: the re-entry represents that join's money
    # being recycled back into the queue, NOT the head's own tier). Matters
    # once this re-entry itself later completes (Boost's re-entries are
    # real, so this can happen) and sizes ITS OWN future join-contributions.
    contribution_tier: int = 1


@dataclass
class PendingGraduation:
    """
    Triggered when a level completes (L1 or L2 only — L3 has no next level):
    the just-paid head is placed as ONE brand-new REAL join in the NEXT level
    up (client-confirmed correction, 2026-08-06 — see module docstring). Never
    credits a wallet by itself — purely a queue-placement event, same as
    PendingReentry, but lands in a DIFFERENT level's queue than the one that
    completed, and counts as a real (not dummy/re-entry) join there.
    """
    matrix_position_id: int   # the completed head's slot id (reference only)
    owner_user_id: int        # who graduates (the just-paid head)
    agent_tier: int
    system_type: SystemType
    level: int                 # the NEXT level (e.g. 2, when graduating from a completed L1)
    # The graduating member's OWN original purchase tier, carried forward
    # unchanged (client-confirmed correction, 2026-08-06) — an Agent 3 buyer's
    # L2/L3 positions stay valued at Agent 3, never reset to baseline. The
    # opposite rule from PendingReentry, which instead carries the COMPLETING
    # join's tier.
    contribution_tier: int


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
    contribution_tier: int | None = None, is_graduate: bool = False,
    spawned_from_position: int | None = None,
) -> tuple[list[PendingPayout], list[PendingSponsorPayout], list[PendingReentry], list["PendingGraduation"]]:
    """
    Append one slot to (agent_tier, system_type, level)'s own queue. Returns
    (payouts, sponsor_payouts, reentries, graduations).

    `spawned_from_position` is set only by the staggered re-entry release
    below (never by an external caller) — the position_number of the
    completed head this particular re-entry slot was released for, recorded
    directly on the new MatrixQueueSlot for the admin flow diagram.

    `contribution_tier` sizes THIS join's own dollar contribution (defaults to
    `agent_tier`, i.e. Stream's normal case where the queue's own tier and the
    joiner's tier are always the same thing). Boost passes the buyer's actual
    purchased tier here while `agent_tier` stays pinned at 1 (Boost's queue
    selector — still one shared queue across every tier) — this is what makes
    a Growth-tier joiner fund a bigger credit than a Trial-tier joiner even
    though they land in the same queue. See MatrixLevelQueue's docstring for
    why the level's gross/wallet-paid running totals (not a fixed per-tier
    formula) are what make the completion math correct once a cycle's real
    joins can be a mix of tiers.

    `is_graduate` marks a slot placed here by GRADUATING up from the level
    below (see place_graduation) rather than a literal fresh purchase or a
    same-level re-entry — purely a MatrixQueueSlot label (module docstring),
    orthogonal to `is_reentry`: a graduation is financially a REAL join in
    ITS level (is_reentry stays False here, so it counts toward
    real_joins_since_head/cycle_gross_accumulated same as any other real
    join), just not driven by a brand-new pack purchase.

    Three independent things can happen for a single appended slot:

    1. INCREMENTAL PAYOUT — if this slot is one of the head's first
       `payout_join_count` brand-new REAL joins, its arrival immediately pays
       `reentry_amount` to the CURRENT head (module docstring: per-joiner
       incremental crediting, not a lump sum at completion).
    2. RE-ENTRY MILESTONE — every `threshold / reentry_count` (always 3)
       total slot-fills (real joins AND re-entries both count — a released
       re-entry fills a slot exactly like a real join does) since the
       CURRENT head's cycle began, that head is granted ONE more re-entry,
       up to `reentry_count` per cycle (client-confirmed correction,
       2026-08-06: "d1,d2,d3 then dhanush does a re-entry, then d4,d5 then
       another, then d6,d7 then another — 3 total for L2 — and only after
       all 3 does dhanush graduate to L3"). Because a released re-entry
       itself counts toward the NEXT milestone, only the FIRST milestone
       needs `threshold/reentry_count` REAL joins — every later one in the
       same cycle needs one fewer (the just-released re-entry already
       covers one slot). A dummy head (Stream's re-entries) never gets one
       — per spec it earns nothing and spawns nothing itself.
    3. LEVEL COMPLETION — since `threshold` is always exactly
       `reentry_count` milestones apart (by construction — see
       PAYOUT_CONFIG), the FINAL re-entry milestone of a cycle always lands
       on the exact same slot-fill as full completion: the head pops, its
       graduation into the next level (if any) is queued, its sponsor share
       (if any) is queued, and any leftover pool residual is booked as
       platform profit. Per the spec's own worked example ("1st member gets
       payment from 2nd,3rd,4th... popped... 2nd member: 5th,6th,7th will
       pay"), each successive head needs `threshold` total slot-fills
       counted from when it became head — NOT merely "however many people
       happen to already be sitting in the queue". So completion #k
       (0-indexed by head_position - 1) requires the cumulative slot count
       to reach `1 + threshold * (k + 1)` — this is what
       `total_joined >= 1 + threshold * completions_so_far` checks below. A
       naive `next_position - head_position >= threshold` check
       double-counts already-queued members across consecutive completions
       and runs away.

    The `while True` loop below re-checks after EVERY effect (a milestone
    release or a completion), not just once, since each is itself a slot-fill
    that can immediately make the next one due too — e.g. a released
    re-entry can itself complete the head if it happens to be the very last
    slot needed. Looped defensively; in practice at most one completion is
    possible per externally-triggered call (any cascade beyond that comes
    from the release/completion effects themselves, handled by re-looping).
    """
    q = _get_or_create_queue(db, agent_tier, system_type, level)
    pos_num = q.next_position
    q.next_position += 1
    contribution_tier = agent_tier if contribution_tier is None else contribution_tier
    new_slot = MatrixQueueSlot(
        agent_tier=agent_tier, system_type=system_type, level=level,
        position_number=pos_num, user_id=user_id, is_dummy=is_dummy,
        is_reentry=is_reentry, is_graduate=is_graduate,
        contribution_tier=contribution_tier,
        spawned_from_position=spawned_from_position,
    )
    db.add(new_slot)
    db.flush()

    cfg = PAYOUT_CONFIG[system_type][level]
    join_multiplier = tier_multiplier(contribution_tier)
    join_contribution = cfg.reentry_amount * join_multiplier
    payouts: list[PendingPayout] = []
    sponsors: list[PendingSponsorPayout] = []
    reentries: list[PendingReentry] = []
    graduations: list[PendingGraduation] = []

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
        # Every real join contributes to the level's gross pool, whether or
        # not it happens to be one of the ones that pays the head directly
        # (see MatrixLevelQueue.cycle_gross_accumulated's docstring) — sized
        # by THIS joiner's own tier, not the queue's.
        q.cycle_gross_accumulated += join_contribution
        if q.real_joins_since_head <= cfg.payout_join_count:
            head_slot = (
                db.query(MatrixQueueSlot)
                .filter_by(agent_tier=agent_tier, system_type=system_type, level=level,
                           position_number=q.head_position)
                .with_for_update()
                .first()
            )
            if head_slot is not None and not head_slot.is_dummy:
                q.cycle_wallet_paid += join_contribution
                payouts.append(PendingPayout(
                    matrix_position_id=new_slot.id,
                    user_id=head_slot.user_id,
                    agent_tier=agent_tier,
                    system_type=system_type,
                    level=level,
                    wallet_amount=join_contribution,
                ))

    stride = cfg.threshold // cfg.reentry_count if cfg.reentry_count > 0 else 0
    while True:
        total_joined = q.next_position - 1
        completions_so_far = q.head_position - 1
        required_total = 1 + cfg.threshold * (completions_so_far + 1)

        head_slot = (
            db.query(MatrixQueueSlot)
            .filter_by(agent_tier=agent_tier, system_type=system_type, level=level,
                       position_number=q.head_position)
            .with_for_update()
            .first()
        )
        if head_slot is None:
            break  # defensive: should never happen, positions are contiguous

        # RE-ENTRY MILESTONE — every `stride` total slot-fills (real joins
        # AND re-entries both count, module docstring) since this head's
        # cycle began, grant it one more re-entry, up to reentry_count per
        # cycle (client-confirmed correction, 2026-08-06: "d1,d2,d3 then a
        # re-entry, d4,d5 then another, d6,d7 then another — 3 total for
        # L2 — only then does dhanush graduate to L3"). A dummy head
        # (Stream's own re-entries) never gets one — per spec it earns
        # nothing and spawns nothing itself. Checked BEFORE the full-
        # completion check below: since threshold is always exactly
        # reentry_count strides, the LAST milestone of a cycle coincides
        # exactly with full completion, and this ordering makes sure that
        # final re-entry is placed (as this same head's own release) before
        # the head pops and hands off to whoever's next.
        if not head_slot.is_dummy and stride > 0 and q.reentries_released_this_cycle < cfg.reentry_count:
            next_milestone = 1 + cfg.threshold * completions_so_far + stride * (q.reentries_released_this_cycle + 1)
            if total_joined >= next_milestone:
                q.reentries_released_this_cycle += 1
                rp, rs, rr, rg = place_level_reentry(
                    db, head_slot.user_id, agent_tier, system_type, level,
                    is_dummy=(system_type == SystemType.STREAM),
                    # The join whose arrival triggered THIS milestone
                    # (`contribution_tier`, this call's own resolved value)
                    # — NOT the head's original tier. Each release
                    # represents that triggering join's money being
                    # recycled back into the queue; the head's own original
                    # purchase already paid out during its own turn as head
                    # and has nothing further to do with this new position.
                    contribution_tier=contribution_tier,
                    spawned_from_position=head_slot.position_number,
                )
                payouts.extend(rp)
                sponsors.extend(rs)
                reentries.extend(rr)
                graduations.extend(rg)
                reentries.append(PendingReentry(
                    matrix_position_id=head_slot.id,
                    owner_user_id=head_slot.user_id,
                    agent_tier=agent_tier,
                    system_type=system_type,
                    level=level,
                    reentry_amount=cfg.reentry_amount,
                    reentry_count=1,
                    contribution_tier=contribution_tier,
                ))
                continue  # re-check: this release may itself complete the head, or earn another milestone

        if total_joined < required_total:
            break

        # FULL COMPLETION — this cycle's final re-entry milestone (if any)
        # was already placed above, on this exact same total_joined value.
        q.head_position += 1
        # Fresh counters for whoever's head next — see real_joins_since_head's
        # and cycle_gross_accumulated's docstrings. Reset unconditionally,
        # even if the old head was dummy; capture this cycle's actual totals
        # first, since the completion math below needs them.
        q.real_joins_since_head = 0
        q.reentries_released_this_cycle = 0
        level_gross = q.cycle_gross_accumulated
        wallet_paid = q.cycle_wallet_paid
        q.cycle_gross_accumulated = Decimal("0")
        q.cycle_wallet_paid = Decimal("0")
        db.flush()

        # Dummy positions (Stream re-entries) fill slots for others but don't
        # earn wallet payouts, spawn re-entries, graduate, or generate a
        # sponsor share/residual themselves.
        if head_slot.is_dummy:
            continue

        # wallet_amount was already delivered incrementally above, one credit
        # per contributing joiner — nothing further to pay the head here.

        # Realized platform profit = the level's leftover pool after the
        # wallet payout, re-entries, and sponsor share — computed from the
        # ACTUAL gross this cycle collected (level_gross), not a fixed
        # per-tier formula, since a mixed-tier Boost cycle's real joins don't
        # all contribute the same amount. reentry_count/threshold and
        # sponsor's share of gross are fixed RATIOS by design (see
        # PAYOUT_CONFIG's docstring — always 1/3 and 10% respectively), so
        # they still apply correctly regardless of the tier mix that funded
        # this particular cycle.
        reentry_share = Decimal(cfg.reentry_count) / Decimal(cfg.threshold)
        reentry_cost = (level_gross * reentry_share).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if cfg.sponsor_on_completion > 0:
            sponsor_rate = cfg.sponsor_on_completion / (cfg.threshold * cfg.reentry_amount)
            sponsor_amount = (level_gross * sponsor_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            sponsor_amount = Decimal("0")
        residual = level_gross - wallet_paid - reentry_cost - sponsor_amount
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
                amount=sponsor_amount,
            ))

        # The completing head ALSO graduates into the NEXT level up, as ONE
        # brand-new real join there (client-confirmed correction, 2026-08-06
        # — see module docstring), only now that all of ITS OWN re-entry
        # milestones have been placed (client-confirmed correction,
        # 2026-08-06 — "dhanush will come L3 only after completing 3
        # re-entry in L2"). L3 has no next level. The graduation carries the
        # member's OWN original purchase tier forward (client-confirmed
        # correction, 2026-08-06 — an Agent 3 buyer's L2/L3 positions stay
        # valued at Agent 3, never reset to the Agent 1 baseline) — the
        # opposite rule from the re-entries above, which instead each carry
        # whichever join triggered that specific milestone.
        if level < 3:
            graduations.append(PendingGraduation(
                matrix_position_id=head_slot.id,
                owner_user_id=head_slot.user_id,
                agent_tier=agent_tier,
                system_type=system_type,
                level=level + 1,
                contribution_tier=head_slot.contribution_tier or agent_tier,
            ))

    return payouts, sponsors, reentries, graduations


def place_real_join(
    db: Session, user_id: int, agent_tier: int, system_type: SystemType,
    contribution_tier: int | None = None,
) -> tuple[list[PendingPayout], list[PendingSponsorPayout], list[PendingReentry], list[PendingGraduation]]:
    """
    A real purchase's placement: adds ONE entry to ONLY L1 of this tier+system
    (client-confirmed correction, 2026-08-06 — a member no longer starts in
    L2/L3 simultaneously; they GRADUATE there when their own L1/L2 position
    completes, see module docstring / PendingGraduation). Returns
    (payouts, sponsors, reentries, graduations).

    `contribution_tier` defaults to `agent_tier` (Stream's normal case). Boost
    passes the buyer's actual purchased tier here while `agent_tier` stays
    pinned at `BOOST_TIER` (matrix_runtime.py) — see _append_to_level's
    docstring.
    """
    return _append_to_level(
        db, user_id, agent_tier, system_type, level=1, is_dummy=False,
        contribution_tier=contribution_tier,
    )


def place_level_reentry(
    db: Session, user_id: int, agent_tier: int, system_type: SystemType,
    level: int, is_dummy: bool, contribution_tier: int | None = None,
    spawned_from_position: int | None = None,
) -> tuple[list[PendingPayout], list[PendingSponsorPayout], list[PendingReentry], list[PendingGraduation]]:
    """
    A re-entry granted by a level completion: feeds back into ONLY that same
    level's own queue — the key difference from a real join, and what keeps
    the whole system bounded (see module docstring). `contribution_tier`
    (the COMPLETING join's own tier — see PendingReentry's docstring) only
    matters for Boost, whose re-entries are real and can themselves later
    complete/graduate; Stream re-entries are dummy and never reach that code
    path. `spawned_from_position` is threaded through to the new slot for the
    admin flow diagram — see _append_to_level's staggered re-entry release.
    """
    return _append_to_level(
        db, user_id, agent_tier, system_type, level, is_dummy, is_reentry=True,
        contribution_tier=contribution_tier, spawned_from_position=spawned_from_position,
    )


def place_graduation(
    db: Session, user_id: int, agent_tier: int, system_type: SystemType,
    level: int, contribution_tier: int,
) -> tuple[list[PendingPayout], list[PendingSponsorPayout], list[PendingReentry], list[PendingGraduation]]:
    """
    Place a member who just completed the level below into THIS level, as one
    brand-new REAL join (never dummy, for either system — a graduate is a
    genuine earning member here, see module docstring). `level` is already the
    DESTINATION level (e.g. 2, when called for a member graduating out of a
    completed L1) — see PendingGraduation.
    """
    return _append_to_level(
        db, user_id, agent_tier, system_type, level, is_dummy=False,
        contribution_tier=contribution_tier, is_graduate=True,
    )
