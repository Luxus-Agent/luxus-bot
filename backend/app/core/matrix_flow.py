"""
Read-only "queue flow" reconstruction for the admin Stream/Boost diagram — the
client's own "How matrix queue work?" spec picture: a single vertical stack of
every position in one level's queue (real joins + re-entries, in true arrival
order), with each paying position linked to the re-entry slot(s) it spawned.

The spawn pairing isn't stored directly on MatrixQueueSlot — it's reconstructed
here. matrix_runtime.drain_matrix_backlog processes payouts strictly oldest-first
(MatrixPendingPayout.id ASC) and places every re-entry a payout grants in one
uninterrupted block before moving to the next backlog row (see that module's
docstring), so within one level's queue the k-th paid position's re-entries are
always exactly the k-th contiguous block of `reentry_count` is_reentry=True
slots, in position_number order. This function is pure/read-only.
"""
from sqlalchemy.orm import Session

from app.core.matrix_engine import PAYOUT_CONFIG
from app.models.matrix import MatrixLevelQueue, MatrixQueueSlot, SystemType
from app.models.user import User


def get_queue_flow(db: Session, system_type: SystemType, tier: int, level: int) -> dict:
    cfg = PAYOUT_CONFIG[system_type][level]
    queue = (
        db.query(MatrixLevelQueue)
        .filter_by(agent_tier=tier, system_type=system_type, level=level)
        .first()
    )
    head = queue.head_position if queue else 1

    slots = (
        db.query(MatrixQueueSlot)
        .filter_by(agent_tier=tier, system_type=system_type, level=level)
        .order_by(MatrixQueueSlot.position_number)
        .all()
    )
    user_ids = {s.user_id for s in slots}
    usernames = (
        dict(db.query(User.id, User.username).filter(User.id.in_(user_ids)).all())
        if user_ids else {}
    )

    # Reconstruct spawn pairing (see module docstring for why chunking by
    # reentry_count, in position_number order, is exact rather than heuristic).
    paid_positions = [s.position_number for s in slots if s.position_number < head and not s.is_dummy]
    reentry_positions = [s.position_number for s in slots if s.is_reentry]

    spawned_by: dict[int, int] = {}
    n = cfg.reentry_count or 0
    if n > 0:
        for i, paid_pos in enumerate(paid_positions):
            for r_pos in reentry_positions[i * n:(i + 1) * n]:
                spawned_by[r_pos] = paid_pos

    return {
        "system_type": system_type.value,
        "agent_tier": tier,
        "level": level,
        "threshold": cfg.threshold,
        "reentry_count": n,
        "head_position": head,
        "total_slots": len(slots),
        "slots": [
            {
                "position_number": s.position_number,
                "username": usernames.get(s.user_id, f"user{s.user_id}"),
                "is_dummy": s.is_dummy,
                "is_reentry": s.is_reentry,
                "is_paid": s.position_number < head and not s.is_dummy,
                "is_head": s.position_number == head,
                "spawned_from": spawned_by.get(s.position_number),
            }
            for s in slots
        ],
    }
