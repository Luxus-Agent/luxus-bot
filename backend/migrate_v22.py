"""
migrate_v22.py — Add `matrix_queue_slots.is_reentry`.

Distinguishes a re-entry slot (granted by a level completion) from a brand-new
real-purchase join. Stream already marks re-entries via `is_dummy`, but Boost
re-entries are REAL (is_dummy stays False per spec) so there was previously no
way to tell a Boost re-entry apart from a genuine new member — this column
fixes that for the admin queue-flow diagram (labels/pairs re-entries for both
systems).

Backfills existing Stream rows (is_dummy=True implies is_reentry=True historically
— that has always been the case for Stream). Existing Boost rows can't be
backfilled retroactively (no prior marker existed) — they'll just show as
"real join" in the flow diagram; only new Boost re-entries created after this
migration will be correctly labeled.

Idempotent — safe to run more than once. Run once:

  cd backend
  python migrate_v22.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        print("=== Adding matrix_queue_slots.is_reentry ===")
        conn.execute(text(
            "ALTER TABLE matrix_queue_slots "
            "ADD COLUMN IF NOT EXISTS is_reentry BOOLEAN NOT NULL DEFAULT false"
        ))
        conn.commit()
        print("  is_reentry column ready.")

        print("=== Backfilling Stream re-entries (is_dummy=True => is_reentry=True) ===")
        result = conn.execute(text(
            "UPDATE matrix_queue_slots SET is_reentry = true "
            "WHERE is_dummy = true AND is_reentry = false"
        ))
        conn.commit()
        print(f"  {result.rowcount} row(s) backfilled.")

    print("\nDone. Note: pre-existing Boost re-entries (is_dummy is always false for "
          "Boost) cannot be backfilled retroactively — only Boost re-entries created "
          "after this migration will be labeled correctly.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v22.py completed successfully.")
