"""
Migration v24 — Stream/Boost per-joiner incremental payouts.

Two DB changes, both required for the incremental-payout redesign in
matrix_engine.py / matrix_runtime.py (Stream/Boost payouts are now credited
per-joiner instead of as a lump sum at level completion; Boost also skips the
70/20/10 split entirely — see those modules' docstrings):

1. `pendingkind` Postgres ENUM gains `'reentry'` — re-entry spawning is now
   its own MatrixPendingPayout backlog kind, decoupled from crediting a
   payout (previously bundled into the PAYOUT kind's processing).
2. `matrix_level_queues.real_joins_since_head` (new INTEGER column) — tracks
   how many REAL (non-reentry) joins have arrived since the CURRENT head
   became head, which per-joiner incremental crediting needs to know when to
   pay vs. when a joining slot is just a re-entry padding the queue. See
   MatrixLevelQueue's docstring for why this can't be derived from
   `next_position - head_position` alone.

Backfill for #2: existing queues aren't necessarily mid-way through a fresh
cycle at 0 — a queue's current head may already have some real joins queued
up under the old lump-sum code that haven't completed yet. For each existing
MatrixLevelQueue row, the "current cycle" started right after the previous
completion, at position `1 + threshold * completions_so_far` (completions_so_far
= head_position - 1; the same `required_total` arithmetic matrix_engine.py
already uses, replayed here for the ONE most recent boundary). real_joins_since_head
is backfilled as the count of MatrixQueueSlot rows after that boundary, before
next_position, that are NOT re-entries (is_reentry=False) — i.e. exactly the
joins the new incremental-payout logic would still owe a payout to.

Idempotent (uses IF NOT EXISTS for the column/enum value; the backfill
recomputes from scratch each run, which converges to the same correct value).
Run from backend/:  python migrate_v24.py
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.matrix_engine import PAYOUT_CONFIG
from app.database import engine
from app.models.matrix import MatrixLevelQueue, MatrixQueueSlot, PendingKind

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

    print("=== Adding matrix_level_queues.real_joins_since_head ===")
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE matrix_level_queues "
            "ADD COLUMN IF NOT EXISTS real_joins_since_head INTEGER NOT NULL DEFAULT 0"
        ))
        conn.commit()
    print("  column ready.")

    print("=== Backfilling real_joins_since_head for existing queues ===")
    db = Session(bind=engine)
    try:
        queues = db.query(MatrixLevelQueue).all()
        updated = 0
        for q in queues:
            threshold = PAYOUT_CONFIG[q.system_type][q.level].threshold
            completions_so_far = q.head_position - 1
            boundary_position = 1 + threshold * completions_so_far
            real_count = (
                db.query(MatrixQueueSlot)
                .filter(
                    MatrixQueueSlot.agent_tier == q.agent_tier,
                    MatrixQueueSlot.system_type == q.system_type,
                    MatrixQueueSlot.level == q.level,
                    MatrixQueueSlot.position_number > boundary_position,
                    MatrixQueueSlot.position_number < q.next_position,
                    MatrixQueueSlot.is_reentry.is_(False),
                )
                .count()
            )
            if q.real_joins_since_head != real_count:
                q.real_joins_since_head = real_count
                updated += 1
        db.commit()
        print(f"  {len(queues)} queue(s) checked, {updated} updated.")
    finally:
        db.close()

    print("Done.")
