"""
migrate_v19.py — Create matrix_level_queues + matrix_queue_slots: the Stream/
Boost matrix engine's new per-level FIFO queue tables.

Why: matrix_engine.py was rewritten to match the client's actual "How matrix
(Queue system) work?" spec — three SEPARATE queues per (agent_tier,
system_type), one per level (L1/L2/L3), each a plain FIFO line, instead of a
single shared ancestor tree. A real purchase adds one entry to all three
level-queues at once; re-entries a level-completion grants feed back ONLY into
that same level's own queue. This is both spec-accurate and (unlike the old
tree) mathematically self-bounding — see matrix_engine.py's module docstring.

The old matrix_positions / matrix_counters tables are left in place (still
referenced by migrate_v16.py / backfill_platform_profit.py for history) but are
no longer written to — they were confirmed empty before this migration, so
nothing is lost by retiring them.

Idempotent — safe to run more than once. Run once:

  cd backend
  python migrate_v19.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        print("=== Creating matrix_level_queues ===")
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS matrix_level_queues (
                id            SERIAL PRIMARY KEY,
                agent_tier    INTEGER NOT NULL,
                system_type   systemtype NOT NULL,
                level         INTEGER NOT NULL,
                head_position INTEGER NOT NULL DEFAULT 1,
                next_position INTEGER NOT NULL DEFAULT 1,
                UNIQUE (agent_tier, system_type, level)
            )
            """
        ))
        print("  matrix_level_queues ready.")

        print("=== Creating matrix_queue_slots ===")
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS matrix_queue_slots (
                id              SERIAL PRIMARY KEY,
                agent_tier      INTEGER NOT NULL,
                system_type     systemtype NOT NULL,
                level           INTEGER NOT NULL,
                position_number INTEGER NOT NULL,
                user_id         INTEGER NOT NULL REFERENCES users(id),
                is_dummy        BOOLEAN NOT NULL DEFAULT false,
                created_at      TIMESTAMP,
                UNIQUE (agent_tier, system_type, level, position_number)
            )
            """
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_matrix_queue_slots_id "
            "ON matrix_queue_slots (id)"
        ))
        conn.commit()
        print("  matrix_queue_slots ready.")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v19.py completed successfully.")
