"""
3×3 Forced Matrix Engine — shared by the Stream and Boost Agent systems.

Tree layout (breadth-first, 1-indexed)
---------------------------------------
    1
    ├── 2  └── 3  └── 4
        ├── 5,6,7       ├── 8,9,10      ├── 11,12,13
            └── ...

Parent formula: parent(p) = (p - 2) // 3 + 1  for p >= 2

When position P joins, it increments the fill count of its L1, L2, and L3 ancestors.
Two types of events can fire on each fill increment:

  1. Sponsor milestone  — at specific fill counts a portion goes to the position
                          owner's sponsor (routes through credit_wallet).
  2. Level completion   — when fill count reaches the threshold (3 / 9 / 27) the
                          owner gets the main wallet payout + re-entry grants.

Payout amounts (Agent 1 / $10 base — higher Stream tiers scale by multiplier):

  Stream Agent  L1: $2.00 wallet + $1.00 re-entry ×(1 × tier_multiplier)
                    sponsor milestones: none
                L2: $5.00 wallet + $2.00 re-entries ×(2 × tier_multiplier)
                    sponsor milestones: {5: $1.00}
                L3: $13.00 wallet + $3.00 re-entries ×(3 × tier_multiplier)
                    sponsor milestones: {20: $1.00}
                (remaining pool amount → platform profit, not distributed)

  Boost Agent   L1: $0.60 wallet + $0.30 re-entry ×1  (single queue, always tier 1)
                    sponsor milestones: none
                L2: $1.50 wallet + $0.60 re-entries ×2
                    sponsor milestones: {5: $0.30}
                L3: $4.90 wallet + $0.90 re-entries ×3
                    sponsor milestones: {4: $0.30, 20: $0.30}
                (remaining pool amount → platform profit, not distributed)

  Note: Boost Agent uses a SINGLE global queue (agent_tier=1 for all tiers).
        All re-entries (from Stream and Boost) enter this same single Boost queue.
        Re-entries in the Boost queue are NOT dummy — they receive full payouts.

Re-entry destination (each queue self-cycles — per the client matrix diagram
  A · B · C · D · A1 · E · F · B1 · …, where A1/B1/… are re-entries rejoining the
  same queue at the next breadth-first slot):
  Stream re-entries → placed back into the SAME tier's Stream queue as DUMMY slots
  Boost  re-entries → placed back into the single Boost queue as REAL slots

Re-entry count scaling (Stream only):
  reentry_count = base_count × tier_multiplier
  e.g. Agent 2 (2×): L1=2, L2=4, L3=6
       Agent 3 (5×): L1=5, L2=10, L3=15
       Agent 4 (10×): L1=10, L2=20, L3=30

Dummy positions (Stream re-entries) fill slots to push the real members above them
  toward their next level completion, but they themselves earn no wallet payout and
  spawn no further re-entries. Only one real Stream entry exists per user at a time.
  Boost positions (including re-entries) are all real and receive full payouts.

Concurrency safety
------------------
MatrixCounter is locked with SELECT FOR UPDATE before reading/incrementing,
guaranteeing sequential position numbers under concurrent joins.
Each ancestor row is also locked before its fill count is updated.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.matrix import MatrixCounter, MatrixPosition, SystemType

AGENT_TIER_PRICES = {1: 10, 2: 20, 3: 50, 4: 100}


@dataclass
class LevelConfig:
    threshold: int
    wallet_amount: Decimal
    reentry_amount: Decimal
    reentry_count: int          # Base count — multiplied by tier_multiplier for Stream
    # fill_count → amount to send to the position owner's sponsor
    sponsor_milestones: dict[int, Decimal] = field(default_factory=dict)


PAYOUT_CONFIG: dict[SystemType, dict[int, LevelConfig]] = {
    SystemType.STREAM: {
        1: LevelConfig(
            threshold=3,
            wallet_amount=Decimal("2.00"),
            reentry_amount=Decimal("1.00"),
            reentry_count=1,
        ),
        2: LevelConfig(
            threshold=9,
            wallet_amount=Decimal("5.00"),
            reentry_amount=Decimal("2.00"),
            reentry_count=2,
            sponsor_milestones={5: Decimal("1.00")},
        ),
        3: LevelConfig(
            threshold=27,
            wallet_amount=Decimal("13.00"),
            reentry_amount=Decimal("3.00"),
            reentry_count=3,
            sponsor_milestones={20: Decimal("1.00")},
        ),
    },
    SystemType.BOOST: {
        1: LevelConfig(
            threshold=3,
            wallet_amount=Decimal("0.60"),
            reentry_amount=Decimal("0.30"),
            reentry_count=1,
        ),
        2: LevelConfig(
            threshold=9,
            wallet_amount=Decimal("1.50"),
            reentry_amount=Decimal("0.60"),
            reentry_count=2,
            sponsor_milestones={5: Decimal("0.30")},
        ),
        3: LevelConfig(
            threshold=27,
            wallet_amount=Decimal("4.90"),
            reentry_amount=Decimal("0.90"),
            reentry_count=3,
            sponsor_milestones={4: Decimal("0.30"), 20: Decimal("0.30")},
        ),
    },
}


def tier_multiplier(agent_tier: int) -> Decimal:
    return Decimal(str(AGENT_TIER_PRICES[agent_tier])) / Decimal("10")


def parent_position(pos: int) -> int | None:
    if pos <= 1:
        return None
    return (pos - 2) // 3 + 1


def ancestor_chain(pos: int, depth: int = 3) -> list[int]:
    ancestors = []
    current = pos
    for _ in range(depth):
        p = parent_position(current)
        if p is None:
            break
        ancestors.append(p)
        current = p
    return ancestors


@dataclass
class PendingPayout:
    """Triggered when a matrix level reaches its fill threshold."""
    matrix_position_id: int
    user_id: int
    agent_tier: int
    system_type: SystemType
    level: int
    wallet_amount: Decimal
    reentry_amount: Decimal
    reentry_count: int


@dataclass
class PendingSponsorPayout:
    """Triggered when a fill count hits a sponsor milestone position."""
    matrix_position_id: int
    owner_user_id: int   # The matrix position owner (their sponsor gets paid)
    agent_tier: int
    system_type: SystemType
    level: int
    amount: Decimal      # Amount to credit to owner's sponsor


def place_in_matrix(
    db: Session,
    user_id: int,
    agent_tier: int,
    system_type: SystemType,
    is_dummy: bool = False,
) -> tuple[MatrixPosition, list[PendingPayout], list[PendingSponsorPayout]]:
    """
    Assign the next available matrix slot to user_id and update ancestor fill counts.

    Returns:
        new_slot           — the created MatrixPosition
        pending_payouts    — level-completion payouts to queue via Celery
        sponsor_payouts    — sponsor milestone payouts to queue via Celery

    Must run inside an active transaction — does NOT commit.
    """
    # 1. Claim next position (row-level lock prevents concurrent conflicts)
    counter = (
        db.query(MatrixCounter)
        .filter_by(agent_tier=agent_tier, system_type=system_type)
        .with_for_update()
        .first()
    )
    if not counter:
        counter = MatrixCounter(agent_tier=agent_tier, system_type=system_type, next_position=1)
        db.add(counter)
        db.flush()

    new_pos_num = counter.next_position
    counter.next_position += 1
    db.flush()

    # 2. Insert the new slot
    new_slot = MatrixPosition(
        user_id=user_id,
        agent_tier=agent_tier,
        system_type=system_type,
        position_number=new_pos_num,
        is_dummy=is_dummy,
    )
    db.add(new_slot)
    db.flush()

    # 3. Walk up the ancestor chain, increment fill counts, check for events
    pending_payouts: list[PendingPayout] = []
    sponsor_payouts: list[PendingSponsorPayout] = []

    for depth_index, ancestor_pos_num in enumerate(ancestor_chain(new_pos_num)):
        level = depth_index + 1  # 1, 2, or 3

        ancestor = (
            db.query(MatrixPosition)
            .filter_by(agent_tier=agent_tier, system_type=system_type, position_number=ancestor_pos_num)
            .with_for_update()
            .first()
        )
        if not ancestor:
            continue

        # Increment fill count for this level
        if level == 1:
            ancestor.l1_filled += 1
            filled, already_paid = ancestor.l1_filled, ancestor.l1_paid
        elif level == 2:
            ancestor.l2_filled += 1
            filled, already_paid = ancestor.l2_filled, ancestor.l2_paid
        else:
            ancestor.l3_filled += 1
            filled, already_paid = ancestor.l3_filled, ancestor.l3_paid

        db.flush()

        cfg = PAYOUT_CONFIG[system_type][level]
        multiplier = tier_multiplier(agent_tier)

        # ── Sponsor milestone check ──────────────────────────────────────────
        if filled in cfg.sponsor_milestones:
            base_sponsor_amount = cfg.sponsor_milestones[filled]
            sponsor_payouts.append(PendingSponsorPayout(
                matrix_position_id=ancestor.id,
                owner_user_id=ancestor.user_id,
                agent_tier=agent_tier,
                system_type=system_type,
                level=level,
                amount=base_sponsor_amount * multiplier,
            ))

        # ── Level completion check ───────────────────────────────────────────
        if filled >= cfg.threshold and not already_paid:
            if level == 1:
                ancestor.l1_paid = True
            elif level == 2:
                ancestor.l2_paid = True
            else:
                ancestor.l3_paid = True
                ancestor.completed = True

            # Dummy positions (Stream re-entries) fill slots for others but don't
            # earn wallet payouts or spawn further re-entries themselves.
            if not ancestor.is_dummy:
                # Scale reentry_count by tier multiplier for Stream Agent.
                # Boost Agent is always tier 1 (multiplier=1) so count stays as-is.
                scaled_reentry_count = int(cfg.reentry_count * int(multiplier))
                pending_payouts.append(PendingPayout(
                    matrix_position_id=ancestor.id,
                    user_id=ancestor.user_id,
                    agent_tier=agent_tier,
                    system_type=system_type,
                    level=level,
                    wallet_amount=cfg.wallet_amount * multiplier,
                    reentry_amount=cfg.reentry_amount * multiplier,
                    reentry_count=scaled_reentry_count,
                ))

    return new_slot, pending_payouts, sponsor_payouts
