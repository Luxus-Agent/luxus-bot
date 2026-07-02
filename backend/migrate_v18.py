"""
migrate_v18.py — Create the matrix_pending_payouts table: a durable backlog for
Stream/Boost matrix level-completion payouts and sponsor shares.

Why: the matrix payout cascade used to be resolved entirely in-memory within a
single purchase request. Because Boost re-entries are real (not dummy, per the
client spec) and Boost is one global queue shared by every purchase on the
platform, that cascade can self-sustain far longer than a single request should
run once enough real purchases have accumulated (observed: 2,985+ payouts from
one purchase, still climbing, starting around the 19th real Boost placement
platform-wide) — and worse, hitting the old safety step-cap silently discarded
whatever was still in-flight, even though the DB already recorded those matrix
levels as paid. This table lets the payout cascade be processed in bounded,
resumable chunks across purchases instead — see app/core/matrix_runtime.py.

Idempotent — safe to run more than once. Run once:

  cd backend
  python migrate_v18.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        print("=== Creating pendingkind enum ===")
        conn.execute(text(
            """
            DO $$ BEGIN
                CREATE TYPE pendingkind AS ENUM ('payout', 'sponsor');
            EXCEPTION WHEN duplicate_object THEN null;
            END $$;
            """
        ))

        print("=== Creating matrix_pending_payouts ===")
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS matrix_pending_payouts (
                id                 SERIAL PRIMARY KEY,
                kind               pendingkind NOT NULL,
                matrix_position_id INTEGER NOT NULL,
                owner_user_id      INTEGER NOT NULL REFERENCES users(id),
                agent_tier         INTEGER NOT NULL,
                system_type        systemtype NOT NULL,
                level              INTEGER NOT NULL,
                amount             NUMERIC(14, 4) NOT NULL,
                reentry_amount     NUMERIC(14, 4),
                reentry_count      INTEGER,
                created_at         TIMESTAMP
            )
            """
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_matrix_pending_payouts_id "
            "ON matrix_pending_payouts (id)"
        ))
        conn.commit()
        print("  matrix_pending_payouts ready.")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v18.py completed successfully.")
