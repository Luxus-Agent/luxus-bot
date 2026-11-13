"""
Read-only "queue flow" reconstruction for the admin Stream/Boost diagram — the
client's own "How matrix queue work?" spec picture: a single vertical stack of
every position in one level's queue (real joins + re-entries, in true arrival
order), with each paying position linked to the re-entry slot(s) it spawned.

Spawn pairing (`MatrixQueueSlot.spawned_from_position`) is recorded directly
at creation time by matrix_engine._append_to_level's staggered re-entry
release (client-confirmed correction, 2026-08-06: re-entries drip out one at
a time, one per 3 subsequent real joins, instead of all at once — see that
module's docstring), so a completion's re-entries are no longer a contiguous
block in queue order and can't be reconstructed by position adjacency alone.
Pre-migration rows (created before that change) have `spawned_from_position`
NULL — this function falls back to the old contiguous-chunk heuristic for
just those (kept so the diagram stays correct for any legacy row, or a fresh
row that somehow arrives without it). This function is pure/read-only.
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

    # Legacy fallback ONLY for rows predating spawned_from_position (see
    # module docstring) — chunk any such re-entries by reentry_count, in
    # position order, against paid positions that also predate the column.
    n = cfg.reentry_count or 0
    legacy_paid = [s.position_number for s in slots if s.position_number < head and not s.is_dummy]
    legacy_reentries = [s.position_number for s in slots if s.is_reentry and s.spawned_from_position is None]
    legacy_spawned_by: dict[int, int] = {}
    if n > 0:
        for i, r_pos in enumerate(legacy_reentries):
            chunk = i // n
            if chunk < len(legacy_paid):
                legacy_spawned_by[r_pos] = legacy_paid[chunk]

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
                "spawned_from": s.spawned_from_position or legacy_spawned_by.get(s.position_number),
                # A dummy (Stream re-entry) position that has already popped —
                # per spec it earns nothing and spawns nothing further, so it
                # produces no visible payout/re-entry marker of its own. Flag
                # it explicitly so the diagram doesn't read as an unexplained
                # gap (a stretch of real joins with no re-entry in between is
                # actually two completions, one of them silent).
                "is_passed_through": s.is_dummy and s.position_number < head,
            }
            for s in slots
        ],
    }
