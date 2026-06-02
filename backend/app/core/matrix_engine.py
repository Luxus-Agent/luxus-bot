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

Payout amounts (Agent 1 / $10 base — higher Stream tiers scale wallet/re-entry
$ amounts by tier_multiplier; re-entry COUNT stays fixed across tiers):

  Stream Agent  L1: $2.00 wallet + $1.00 re-entry ×1
                    sponsor on completion: none
                L2: $5.00 wallet + $1.00 re-entries ×2
                    sponsor on completion: $0.90 (= 10% of $9 level gross)
                L3: $13.00 wallet + $1.00 re-entries ×3
                    sponsor on completion: $2.70 (= 10% of $27 level gross)
                (remaining pool amount → platform profit, not distributed)

  Boost Agent   L1: $0.60 wallet + $0.30 re-entry ×1  (single queue, always tier 1)
                    sponsor on completion: none
                L2: $1.50 wallet + $0.30 re-entries ×2
                    sponsor on completion: $0.27 (= 10% of $2.70 level gross)
                L3: $3.60 wallet + $0.30 re-entries ×3
                    sponsor on completion: $0.81 (= 10% of $8.10 level gross)
                (remaining pool amount → platform profit, not distributed)

  Note: Boost Agent uses a SINGLE global queue (agent_tier=1 for all tiers).
        All re-entries (from Stream and Boost) enter this same single Boost queue.
        Re-entries in the Boost queue are NOT dummy — they receive full payouts.

Re-entry destination (each queue self-cycles — per the client matrix diagram
  A · B · C · D · A1 · E · F · B1 · …, where A1/B1/… are re-entries rejoining the
  same queue at the next breadth-first slot):
  Stream re-entries → placed back into the SAME tier's Stream queue as DUMMY slots
  Boost  re-entries → placed back into the single Boost queue as REAL slots

Re-entry count (Stream): FIXED at 1 / 2 / 3 across all tiers (per client doc —
  "every Nth income spawns a re-entry", giving 1 at L1, 2 at L2, 3 at L3;
  total 6 re-entries over a full cycle). Only the per-re-entry $ amount scales
  by tier_multiplier:
       Agent 2 (2×): each re-entry = $2  (still 1/2/3 re-entries)
       Agent 3 (5×): each re-entry = $5  (still 1/2/3 re-entries)
       Agent 4 (10×): each re-entry = $10 (still 1/2/3 re-entries)

Sponsor share — Stream AND Boost (L2 + L3 only):
  Per the client doc, "10% of every income goes to the user's sponsor — not
  deducted from the income, paid extra from the pool." Both systems use the
  same model: a single sponsor credit fired on level completion equal to
  10% × level_gross, scaled by tier_multiplier (Boost is always tier 1, ×1):
       Stream L2 base = $0.90 (10% of 9×$1), L3 base = $2.70 (10% of 27×$1)
       Boost  L2      = $0.27 (10% of $2.70), L3     = $0.81 (10% of $8.10)
  L1 has no sponsor share. (The older Boost per-position milestone model —
  5th/4th/20th member → $0.30 — has been retired in favour of this.)

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
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.matrix import MatrixCounter, MatrixPosition, SystemType
from app.models.transaction import Transaction, TransactionType

AGENT_TIER_PRICES = {1: 10, 2: 20, 3: 50, 4: 100}


@dataclass
class LevelConfig:
    threshold: int
    wallet_amount: Decimal
    reentry_amount: Decimal
    reentry_count: int          # Fixed across tiers (Stream + Boost both)
    # Stream & Boost: extra 10% paid to the owner's sponsor on level completion
    # (base amount — scaled by tier_multiplier at runtime; Boost is always ×1).
    sponsor_on_completion: Decimal = Decimal("0")


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
            reentry_amount=Decimal("1.00"),
            reentry_count=2,
            sponsor_on_completion=Decimal("0.90"),
        ),
        3: LevelConfig(
            threshold=27,
            wallet_amount=Decimal("13.00"),
            reentry_amount=Decimal("1.00"),
            reentry_count=3,
            sponsor_on_completion=Decimal("2.70"),
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
            reentry_amount=Decimal("0.30"),
            reentry_count=2,
            sponsor_on_completion=Decimal("0.27"),  # 10% of $2.70 level gross
        ),
        3: LevelConfig(
            threshold=27,
            wallet_amount=Decimal("3.60"),
            reentry_amount=Decimal("0.30"),
            reentry_count=3,
            sponsor_on_completion=Decimal("0.81"),  # 10% of $8.10 level gross
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
                # Re-entry count is FIXED across tiers; only $ amount scales.
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
                # wallet payout, re-entries, and sponsor share. reentry_amount is the
                # per-member contribution (equal by design: Stream $1, Boost $0.30),
                # so level gross = threshold × reentry_amount.
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

                # Stream & Boost L2/L3: 10% extra to owner's sponsor on level
                # completion (paid from platform pool, not deducted from wallet).
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
