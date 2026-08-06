"""
Migration v29 — Stream/Boost re-entry milestones become progressive WITHIN
the same head's cycle, not staggered AFTER it (client-confirmed correction,
2026-08-06: "d1,d2,d3 then dhanush does a re-entry, then d4,d5 then another,
then d6,d7 then another — 3 total for L2 — dhanush will come L3 only after
completing 3 re-entry in L2"). This supersedes migrate_v28.py's design,
shipped moments earlier in the same conversation and never released — that
version parked a completion's re-entries in a JSON backlog column and
drained them after the fact; this version instead grants them one at a time
DURING the cycle, using a simple per-cycle counter, with the final one
landing on the exact same slot-fill as the cycle's own completion.

Two DB changes:

1. `matrix_level_queues.pending_reentries_json` and
   `matrix_level_queues.real_joins_since_reentry_release` (both added by
   migrate_v28.py) are DROPPED — no longer used by this design.
2. `matrix_level_queues.reentries_released_this_cycle` (new INTEGER column,
   default 0) — how many of the CURRENT head's `reentry_count` re-entry
   milestones have already been granted this cycle; resets to 0 the instant
   the head pops. 0 is the correct value for every existing queue: under
   migrate_v28's now-superseded design nothing was ever left mid-release for
   an ONGOING cycle (a completion either had already fully released its
   batch, or hadn't started yet) — see that migration's own reasoning, which
   still holds for this narrower column.

`matrix_queue_slots.spawned_from_position` (from migrate_v28.py) is
untouched — still exactly what the admin flow diagram needs, still populated
the same way (the position of the head whose cycle a re-entry belongs to).

Idempotent (`ADD COLUMN IF NOT EXISTS` / `DROP COLUMN IF EXISTS`). Run from
backend/:  python migrate_v29.py
"""
from sqlalchemy import text

from app.database import engine

if __name__ == "__main__":
    print("=== Dropping migrate_v28's now-superseded columns ===")
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE matrix_level_queues DROP COLUMN IF EXISTS pending_reentries_json"
        ))
        conn.execute(text(
            "ALTER TABLE matrix_level_queues DROP COLUMN IF EXISTS real_joins_since_reentry_release"
        ))
        conn.commit()
    print("  dropped.")

    print("=== Adding matrix_level_queues.reentries_released_this_cycle ===")
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE matrix_level_queues "
            "ADD COLUMN IF NOT EXISTS reentries_released_this_cycle INTEGER NOT NULL DEFAULT 0"
        ))
        conn.commit()
    print("  column ready (0 is correct for every existing row — see module docstring).")

    print("Done.")
