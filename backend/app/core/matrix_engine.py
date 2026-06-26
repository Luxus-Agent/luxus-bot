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
On each fill increment two events can fire:

  1. Level completion — when a fill count reaches the threshold (3 / 9 / 27) the
                        owner gets the main wallet payout + re-entry grants.
  2. Sponsor share    — at L2/L3 completion, 10% of the level gross is paid to the
                        owner's sponsor (extra, from the pool — not deducted).

Payout amounts (Agent 1 / $10 base — higher Stream tiers scale wallet/re-entry $
amounts by tier_multiplier; re-entry COUNT stays fixed at 1/3/9 across tiers):

  Stream Agent  L1: $2.00 wallet + $1.00 re-entry ×1            (no sponsor share)
                L2: $5.00 wallet + $1.00 re-entries ×3          sponsor $0.90 (10% of $9)
                L3: $13.00 wallet + $1.00 re-entries ×9         sponsor $2.70 (10% of $27)
  Boost Agent   L1: $0.60 wallet + $0.30 re-entry ×1            (no sponsor share)
                L2: $1.50 wallet + $0.30 re-entries ×3          sponsor $0.27 (10% of $2.70)
                L3: $3.60 wallet + $0.30 re-entries ×9          sponsor $0.81 (10% of $8.10)
  (remaining level pool after payout + re-entries + sponsor share → platform profit)

Each member contributes `reentry_amount` per level × 3 levels, so a single purchase's
matrix funding = 3 × reentry_amount — exactly the 30% (Stream, $3 of $10) / 9% (Boost,
$0.90 of $10) pool collected on-chain for that purchase. The matrix IS the distribution
of that pool; residuals are booked as platform profit.

Boost Agent uses a SINGLE global queue (agent_tier=1 for all tiers). Boost re-entries
are REAL (full payouts); Stream re-entries are DUMMY (fill slots, earn nothing, spawn
no further re-entries — only one real Stream entry per user at a time).

Concurrency: MatrixCounter and each touched ancestor row are locked with
SELECT FOR UPDATE, guaranteeing sequential position numbers under concurrent joins.

This module is pure/synchronous — it mutates rows and RETURNS the pending payouts;
it does NOT credit wallets or place re-entries (the runtime layer does that). It must
run inside an active transaction and does NOT commit.
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.agent import AGENT_TIER_PRICES
from app.models.matrix import MatrixCounter, MatrixPosition, SystemType
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
    """Triggered when a level completes and its owner's sponsor is owed 10%."""
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

    Returns (new_slot, pending_payouts, sponsor_payouts). Must run inside an active
    transaction — does NOT commit.
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
                pending_payouts.append(PendingPayout(
                    matrix_position_id=ancestor.id,
                    user_id=ancestor.user_id,
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
                        user_id=ancestor.user_id,
                        agent_tier=agent_tier,
                        transaction_type=TransactionType.PLATFORM_PROFIT,
                        amount=residual,
                        reference_id=f"residual_{system_type.value}_t{agent_tier}_pos{ancestor.id}_L{level}",
                        notes=f"{system_type.value} L{level} level residual → platform",
                    ))

                # L2/L3: 10% extra to owner's sponsor on level completion (paid
                # from the pool, not deducted from the owner's wallet).
                if cfg.sponsor_on_completion > 0:
                    sponsor_payouts.append(PendingSponsorPayout(
                        matrix_position_id=ancestor.id,
                        owner_user_id=ancestor.user_id,
                        agent_tier=agent_tier,
                        system_type=system_type,
                        level=level,
                        amount=cfg.sponsor_on_completion * multiplier,
                    ))

    return new_slot, pending_payouts, sponsor_payouts
