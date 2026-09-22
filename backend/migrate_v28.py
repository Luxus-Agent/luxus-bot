"""
Migration v28 — Stream/Boost drip-feed re-entry release (client-confirmed
correction, 2026-08-06: "the 3 re-entries should be done after every 3rd
user, not at the end").

A level completion used to spawn all `reentry_count` re-entries in one
contiguous batch, immediately. They now drip out ONE at a time, every
`threshold / reentry_count` (always 3) subsequent real joins to that same
level's queue — see matrix_engine._append_to_level's "staggered re-entry
release" section.

Three DB changes:

1. `matrix_level_queues.pending_reentries_json` (new nullable TEXT column) —
   a JSON list of re-entries a completion granted but hasn't released into
   the queue yet. Existing queues have none (the old mechanism placed every
   re-entry immediately, so nothing is ever left pending under the old
   model) — NULL is the correct backfill for every pre-migration row.
2. `matrix_level_queues.real_joins_since_reentry_release` (new INTEGER
   column, default 0) — the drip clock. 0 is correct for every pre-migration
   row for the same reason as above.
3. `matrix_queue_slots.spawned_from_position` (new nullable INTEGER column) —
   which completed position (by position_number) a re-entry slot was
   released for, recorded directly at creation time now that re-entries no
   longer arrive in one contiguous block (the admin flow diagram's old
   "k-th paid position -> k-th contiguous block of re-entries" chunking
   heuristic no longer holds for anything created after this migration).
   Backfilled for EXISTING is_reentry rows using that exact same chunking
   heuristic, since pre-migration re-entries genuinely were created in
   contiguous batches — the heuristic is exact for that historical data, so
   this backfill just moves the answer from "reconstructed on every read" to
   "computed once and stored."

Idempotent (`ADD COLUMN IF NOT EXISTS`; the backfill only touches rows where
spawned_from_position IS NULL). Run from backend/:  python migrate_v28.py
"""
import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.matrix_engine import PAYOUT_CONFIG
from app.database import engine
from app.models.matrix import MatrixLevelQueue, MatrixQueueSlot, SystemType

if __name__ == "__main__":
    print("=== Adding matrix_level_queues columns ===")
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE matrix_level_queues "
            "ADD COLUMN IF NOT EXISTS pending_reentries_json TEXT"
        ))
        conn.execute(text(
            "ALTER TABLE matrix_level_queues "
            "ADD COLUMN IF NOT EXISTS real_joins_since_reentry_release INTEGER NOT NULL DEFAULT 0"
        ))
        conn.commit()
    print("  columns ready.")

    print("=== Adding matrix_queue_slots.spawned_from_position ===")
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE matrix_queue_slots "
            "ADD COLUMN IF NOT EXISTS spawned_from_position INTEGER"
        ))
        conn.commit()
    print("  column ready.")

    print("=== Backfilling spawned_from_position for existing re-entries (contiguous-chunk heuristic) ===")
    db = Session(bind=engine)
    try:
        total_updated = 0
        for system_type in (SystemType.STREAM, SystemType.BOOST):
            for level, cfg in PAYOUT_CONFIG[system_type].items():
                n = cfg.reentry_count
                if n <= 0:
                    continue
                tiers = [
                    row[0] for row in
                    db.query(MatrixQueueSlot.agent_tier)
                    .filter_by(system_type=system_type, level=level)
                    .distinct()
                ]
                for tier in tiers:
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
                    # Matches matrix_flow.py's original (pre-drip-feed) chunking
                    # heuristic exactly: any non-dummy slot before the current
                    # head has already been paid and popped — including a
                    # Boost re-entry that later became head itself.
                    paid_positions = [s.position_number for s in slots if s.position_number < head and not s.is_dummy]
                    reentry_slots = [s for s in slots if s.is_reentry and s.spawned_from_position is None]
                    for i, s in enumerate(reentry_slots):
                        chunk = i // n
                        if chunk < len(paid_positions):
                            s.spawned_from_position = paid_positions[chunk]
                            total_updated += 1
        db.commit()
        print(f"  {total_updated} row(s) backfilled.")
    finally:
        db.close()

    print("Done.")
