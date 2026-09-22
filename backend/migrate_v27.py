"""
Migration v27 — Stream/Boost sequential graduation (client-confirmed
correction, 2026-08-06).

A real purchase now places the buyer into ONLY L1 of its tier+system, not all
three levels simultaneously (the earlier "3 x 3 at once" design). A member
only reaches L2 by GRADUATING there when their own L1 position completes —
see matrix_engine.py's module docstring / PendingGraduation / place_graduation.

Three DB changes:

1. `pendingkind` Postgres ENUM gains `'graduate'` — a graduation-spawn is its
   own MatrixPendingPayout backlog kind, alongside payout/sponsor/reentry.
2. `matrix_queue_slots.contribution_tier` (new INTEGER column) — the tier this
   occupant's own join contribution is sized by (matrix_engine._append_to_
   level's `contribution_tier` param), persisted so that if/when this slot
   itself later completes and graduates (or, for Boost, spawns a real
   re-entry), the next placement carries the same tier forward. Backfilled
   from each slot's own `agent_tier` — true for Stream (queue tier == joiner
   tier always) and true for pre-migration Boost history too (queue tier was
   always 1, and that's exactly what every historical join was credited at,
   per migrate_v26.py's same reasoning).
3. `matrix_queue_slots.is_graduate` (new BOOLEAN column, default false) — was
   this slot placed here by graduating up from the level below, vs. a literal
   fresh purchase or a same-level re-entry? Orthogonal to is_reentry/is_dummy.
   No backfill needed: no pre-migration slot could have been a graduation
   (the mechanic didn't exist yet), so `false` is correct for all of them.
4. `matrix_pending_payouts.contribution_tier` (new INTEGER column) — carries
   the tier forward for a queued GRADUATE row (and now also REENTRY rows, so
   a Boost re-entry that itself later graduates sizes correctly). No backfill
   needed: any REENTRY rows still sitting in the backlog at migration time
   fall back to their own `agent_tier` when read (NULL-safe in code).

Idempotent (`ADD COLUMN IF NOT EXISTS`, enum value guarded; the backfill
recomputes from scratch each run). Run from backend/:  python migrate_v27.py
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine
from app.models.matrix import MatrixQueueSlot, PendingKind

if __name__ == "__main__":
    print("=== Adding pendingkind enum value ===")
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older
    # Postgres; AUTOCOMMIT keeps each statement standalone.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        existing = {
            r[0] for r in conn.execute(text(
                "SELECT enumlabel FROM pg_enum e "
                "JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'pendingkind'"
            ))
        }
        for member in PendingKind:
            if member.value in existing:
                continue
            conn.execute(text(
                f"ALTER TYPE pendingkind ADD VALUE IF NOT EXISTS '{member.value}'"
            ))
            print(f"  • added {member.value}")

    print("=== Adding matrix_queue_slots columns ===")
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE matrix_queue_slots "
            "ADD COLUMN IF NOT EXISTS contribution_tier INTEGER"
        ))
        conn.execute(text(
            "ALTER TABLE matrix_queue_slots "
            "ADD COLUMN IF NOT EXISTS is_graduate BOOLEAN NOT NULL DEFAULT false"
        ))
        conn.commit()
    print("  columns ready.")

    print("=== Adding matrix_pending_payouts.contribution_tier ===")
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE matrix_pending_payouts "
            "ADD COLUMN IF NOT EXISTS contribution_tier INTEGER"
        ))
        conn.commit()
    print("  column ready.")

    print("=== Backfilling matrix_queue_slots.contribution_tier from agent_tier ===")
    db = Session(bind=engine)
    try:
        updated = (
            db.query(MatrixQueueSlot)
            .filter(MatrixQueueSlot.contribution_tier.is_(None))
            .update({MatrixQueueSlot.contribution_tier: MatrixQueueSlot.agent_tier}, synchronize_session=False)
        )
        db.commit()
        print(f"  {updated} row(s) backfilled.")
    finally:
        db.close()

    print("Done.")
