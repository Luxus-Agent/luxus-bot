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
    Kept only because migrate_v16.py and backfill_platform_profit.py still
    import it; the table itself has always been empty in this environment.

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
    RETIRED — see MatrixPosition's docstring. Kept for migrate_v16.py only.

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

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PendingKind(str, enum.Enum):
    PAYOUT = "payout"
    SPONSOR = "sponsor"


class MatrixPendingPayout(Base):
    """
    Durable backlog of matrix level-completion work not yet credited.

    A level completion (payout OR sponsor share) is queued here the moment it's
    detected — see matrix_engine._append_to_level, called from place_real_join /
    place_level_reentry — and only removed once actually credited. This makes
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
    matrix_position_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # PAYOUT: the position owner who gets credited. SPONSOR: the position owner
    # whose *current* sponsor gets credited (resolved lazily at drain time, same
    # as the old in-memory _process_sponsor_payout — sponsor status can only be
    # checked when the row is actually processed, not when it's queued).
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    system_type: Mapped[SystemType] = mapped_column(
        Enum(SystemType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    # PAYOUT: wallet_amount. SPONSOR: the sponsor-share amount.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # Only populated for kind=PAYOUT (drives the re-entries it grants).
    reentry_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    reentry_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
