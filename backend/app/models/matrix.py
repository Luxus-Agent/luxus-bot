import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SystemType(str, enum.Enum):
    STREAM = "stream"
    BOOST  = "boost"


class MatrixPosition(Base):
    """
    RETIRED — superseded by MatrixLevelQueue/MatrixQueueSlot below (the client's
    actual "3 separate queues per level" spec, not a shared ancestor tree — see
    matrix_engine.py's module docstring for why the tree model was replaced).
    Kept only because backfill_platform_profit.py still imports it; the table
    itself has always been empty in this environment.

    One user slot in a 3x3 forced matrix for a (agent_tier, system_type) pair.

    Tree is indexed breadth-first by position_number (1-based).
    Parent of position P: floor((P - 2) / 3) + 1  for P >= 2

    Fill counts track how many members joined below this slot:
      l1_filled: direct children  (threshold 3)
      l2_filled: grandchildren    (threshold 9)
      l3_filled: great-grandchildren (threshold 27)
    """

    __tablename__ = "matrix_positions"
    __table_args__ = (UniqueConstraint("agent_tier", "system_type", "position_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    system_type: Mapped[SystemType] = mapped_column(
        Enum(SystemType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    position_number: Mapped[int] = mapped_column(Integer, nullable=False)

    l1_filled: Mapped[int] = mapped_column(Integer, default=0)
    l2_filled: Mapped[int] = mapped_column(Integer, default=0)
    l3_filled: Mapped[int] = mapped_column(Integer, default=0)

    l1_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    l2_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    l3_paid: Mapped[bool] = mapped_column(Boolean, default=False)

    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    reentry_count: Mapped[int] = mapped_column(Integer, default=0)
    is_dummy: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MatrixCounter(Base):
    """
    RETIRED — see MatrixPosition's docstring. Kept so the existing table stays in the schema.

    Tracks next available position_number per (agent_tier, system_type).
    Locked with SELECT FOR UPDATE to prevent concurrent position conflicts.
    """

    __tablename__ = "matrix_counters"
    __table_args__ = (UniqueConstraint("agent_tier", "system_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    system_type: Mapped[SystemType] = mapped_column(
        Enum(SystemType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    next_position: Mapped[int] = mapped_column(Integer, default=1)


class MatrixLevelQueue(Base):
    """
    One independent FIFO queue for a single (agent_tier, system_type, level).

    Per the client's "How matrix (Queue system) work?" spec: Stream and Boost
    each run as THREE SEPARATE per-level queues, not one combined ancestor
    tree. Position 1 (the head) is paid once the next `threshold` members join
    that SAME level's queue behind them (L1: 3, L2: 9, L3: 27), then pops out
    and the next-in-line becomes head — "likewise, it goes through."

    head_position: position_number of the slot currently waiting to be paid.
    next_position: position_number that will be assigned to the next entry.
    A level pays out (advancing head_position) whenever
    next_position - head_position reaches the level's threshold.

    real_joins_since_head: how many REAL (non-reentry) joins have arrived since
    the CURRENT head became head — drives per-joiner incremental payouts (see
    matrix_engine.py's module docstring). This can't be derived from
    `next_position - head_position` alone: re-entries occupy queue slots too
    (they count toward the completion threshold, per spec), but they must
    NEVER themselves trigger a payout — a re-entry didn't bring in a real
    dollar, so crediting the head for one would manufacture money from
    nothing. Explicitly tracking only real joins avoids that: it's incremented
    on every real join, left untouched by re-entries, and reset to 0 the
    instant the head pops (a fresh count for whoever's head next).

    cycle_gross_accumulated / cycle_wallet_paid: running dollar totals for the
    CURRENT head's cycle — the ACTUAL amount contributed so far and the ACTUAL
    amount already credited to the head, not a fixed per-tier formula. Needed
    because Boost's queue is shared across every tier (`BOOST_TIER = 1` in
    matrix_runtime.py): each real joiner's own purchased tier sizes their
    contribution, so a cycle's joins can be a mix of tiers, and the old
    `threshold * reentry_amount * multiplier` shortcut (a single multiplier for
    the whole cycle) no longer holds. Stream's queue is always single-tier, so
    for Stream these accumulators just reproduce that same fixed-formula total.
    Reset to 0 the instant the head pops, same as real_joins_since_head.
    """

    __tablename__ = "matrix_level_queues"
    __table_args__ = (UniqueConstraint("agent_tier", "system_type", "level"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    system_type: Mapped[SystemType] = mapped_column(
        Enum(SystemType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, or 3
    head_position: Mapped[int] = mapped_column(Integer, default=1)
    next_position: Mapped[int] = mapped_column(Integer, default=1)
    real_joins_since_head: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cycle_gross_accumulated: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), default=Decimal("0"), server_default="0"
    )
    cycle_wallet_paid: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), default=Decimal("0"), server_default="0"
    )
    # Progressive re-entry release within the CURRENT head's own cycle
    # (client-confirmed correction, 2026-08-06: "d1,d2,d3 then dhanush does a
    # re-entry, then d4,d5 then another re-entry, then d6,d7 then another —
    # 3 total for L2 — and only after all 3 does dhanush graduate to L3").
    # Counts how many of this level's `reentry_count` re-entries the CURRENT
    # head has already been granted THIS cycle — reset to 0 the instant the
    # head pops (a new cycle, a new head, starts this back at 0). A
    # milestone is due once total_joined (real + re-entry slots combined —
    # see matrix_engine._append_to_level) reaches `threshold/reentry_count`
    # (always 3) more than the last one. Because threshold is always exactly
    # `reentry_count` such steps, the FINAL release always coincides with
    # the cycle's actual completion (head pop + graduation + sponsor share)
    # — they're the same event, not two independent ones. Separate from
    # real_joins_since_head, which gates the INCREMENTAL WALLET PAYOUT (real
    # joins only) — this counts toward re-entry milestones instead, which
    # count re-entries too (a released re-entry fills a slot just like a
    # real join does, and counts toward the NEXT milestone the same way).
    reentries_released_this_cycle: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class MatrixQueueSlot(Base):
    """
    One occupied slot in one level's queue: who's there, and whether they're a
    dummy (a Stream re-entry — fills the slot to keep the queue moving but
    earns nothing and, per spec, spawns no further re-entries itself).
    """

    __tablename__ = "matrix_queue_slots"
    __table_args__ = (
        UniqueConstraint("agent_tier", "system_type", "level", "position_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    system_type: Mapped[SystemType] = mapped_column(
        Enum(SystemType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    position_number: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    is_dummy: Mapped[bool] = mapped_column(Boolean, default=False)
    # Was this slot granted by a level completion (a re-entry), vs. a brand-new
    # real purchase join? For Stream, this always matches is_dummy (Stream
    # re-entries are dummy). For Boost, re-entries are REAL (is_dummy stays
    # False per spec) so is_dummy alone can't tell a re-entry apart from a
    # genuine new member — this column exists so admin views (the "A1/B1..."
    # queue-flow diagram) can label/pair re-entries for Boost too.
    is_reentry: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Was this slot placed here by GRADUATING up from the level below (this
    # user's own L1/L2 position completing), rather than a literal fresh
    # purchase or a same-level re-entry? Orthogonal to is_reentry/is_dummy: a
    # graduation is financially a REAL join in ITS level (is_reentry=False,
    # is_dummy=False — it counts toward payouts/gross same as any other real
    # join there), just not one driven by a brand-new pack purchase. Only L1
    # slots can ever be non-graduate (every L2/L3 slot is either a graduation
    # or a same-level re-entry — see matrix_engine.place_real_join, which only
    # ever places a fresh purchase into L1).
    is_graduate: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # The tier this occupant's OWN join contribution was sized by at the
    # moment they joined (see matrix_engine._append_to_level's
    # `contribution_tier` param). Read back when THIS slot itself later
    # completes, but only for its GRADUATION into the next level — the
    # graduating member's own original purchase tier follows them up
    # unchanged (client-confirmed correction, 2026-08-06: an Agent 3 buyer
    # stays valued at Agent 3 in L2/L3, never resets). The same-level
    # re-entry this completion also spawns does NOT read this column — it
    # instead carries forward whichever join's arrival triggered the
    # completion (see PendingReentry/PendingGraduation's docstrings).
    # Nullable for legacy rows; falls back to `agent_tier` wherever read
    # (matches how those historical joins were actually credited).
    contribution_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Which completed position (by position_number, THIS level's own queue)
    # this slot was released as the re-entry for — set only when is_reentry
    # is True. Recorded directly at creation time now that re-entries drip out
    # one at a time (matrix_engine._append_to_level) rather than in one
    # contiguous batch, so the admin flow diagram can no longer assume the
    # k-th paid position's re-entries are the k-th contiguous block of
    # is_reentry slots (see matrix_flow.py). NULL for pre-migration rows and
    # for any non-reentry slot; matrix_flow.py falls back to the old
    # contiguous-chunk reconstruction only for rows where this is NULL.
    spawned_from_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PendingKind(str, enum.Enum):
    PAYOUT = "payout"
    SPONSOR = "sponsor"
    # RETIRED (client-confirmed correction, 2026-08-06) — re-entries no longer
    # spawn via this durable backlog kind at all; they're granted inline, one
    # per re-entry milestone, straight from matrix_engine._append_to_level
    # (see MatrixLevelQueue.reentries_released_this_cycle). Kept in the enum
    # only because historical MatrixPendingPayout rows / the Postgres type may
    # still reference it; nothing enqueues it anymore.
    REENTRY = "reentry"
    GRADUATE = "graduate"  # Spawn the completed head's graduation into the NEXT level. Never credits a wallet.


class MatrixPendingPayout(Base):
    """
    Durable backlog of matrix level-completion work not yet credited.

    A payout increment (credited the instant a contributing joiner arrives), a
    level completion's sponsor share, the re-entries a completion grants, or
    the completing head's own graduation into the next level up, is queued
    here the moment it's detected — see matrix_engine._append_to_level, called
    from place_real_join / place_level_reentry / place_graduation — and only
    removed once actually processed. This makes
    the payout cascade resumable across requests instead of an in-memory list
    that vanishes if a single purchase's cascade is cut off at a step cap.

    Kept even after the queue-per-level redesign made the underlying math
    self-bounding (see matrix_engine.py): it's cheap defense-in-depth that
    guarantees every purchase request stays fast regardless of backlog size,
    and guarantees a payout is never silently lost — it's either credited or
    still sitting here, never both, never neither. The runtime drains a
    bounded number of rows per purchase call and leaves the rest for the next
    purchase (any user, any tier) to continue — the same pattern already used
    by sweep_auto_repurchases.
    """

    __tablename__ = "matrix_pending_payouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[PendingKind] = mapped_column(
        Enum(PendingKind, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    # Meaning is kind-dependent (see matrix_engine.py's PendingPayout/PendingReentry/
    # PendingGraduation docstrings): PAYOUT rows are now an *incremental per-joiner*
    # credit — this is the id of the MatrixQueueSlot that just JOINED and triggered
    # this specific increment (not the head's slot), so every increment naturally
    # gets a distinct reference at drain time. SPONSOR/REENTRY/GRADUATE rows use the
    # completed HEAD's slot id, same as each other.
    matrix_position_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # PAYOUT/REENTRY/GRADUATE: the position owner who gets credited / who re-enters /
    # who graduates. SPONSOR: the position owner whose *current* sponsor gets
    # credited (resolved lazily at drain time, same as the old in-memory
    # _process_sponsor_payout — sponsor status can only be checked when the row is
    # actually processed, not when it's queued).
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    system_type: Mapped[SystemType] = mapped_column(
        Enum(SystemType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    # PAYOUT/SPONSOR/REENTRY: the level that just completed. GRADUATE: the NEXT
    # level up the owner is being placed into (level + 1 of the level that completed).
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    # PAYOUT: this joiner's incremental wallet credit. SPONSOR: the sponsor-share
    # amount. REENTRY/GRADUATE: unused (0) — no wallet is ever touched for these kinds.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # Only populated for kind=REENTRY (drives the re-entries it grants).
    reentry_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    reentry_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # REENTRY: the COMPLETING join's own tier, carried forward as this
    # re-entry's value (see PendingReentry's docstring). GRADUATE: the
    # graduating member's OWN original purchase tier, carried forward
    # unchanged (see PendingGraduation's docstring — the opposite rule from
    # REENTRY). Unused for PAYOUT/SPONSOR (their amount is already fully
    # computed at enqueue time).
    contribution_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
