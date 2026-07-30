"""
migrate_v23.py — Split Core odd/even routing into per-tier counters.

users.core_route_count was a single shared counter incremented on every Core
targeting regardless of which agent tier ($11/$22/$55/$111) the purchase was
for. That mixed unrelated tiers together: a string of tier-1 purchases could
flip a recipient's parity right before an unrelated tier-2 purchase targeted
them, so whether they kept or passed up the tier-2 share depended on leftover
tier-1 activity instead of their own tier-2 history.

This replaces the single column with four independent counters, one per tier:
  - users.core_route_count_tier1
  - users.core_route_count_tier2
  - users.core_route_count_tier3
  - users.core_route_count_tier4

All new columns start at 0 (existing users get a clean baseline, same
approach migrate_v13 used when core_route_count was first introduced) — there
is no reliable way to retroactively split the old mixed counter's history back
out by tier. The old core_route_count column is dropped.

Idempotent. Run once:

  cd backend
  python migrate_v23.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        print("=== Adding per-tier users.core_route_count_tierN columns ===")
        for tier in (1, 2, 3, 4):
            conn.execute(text(
                f"ALTER TABLE users "
                f"ADD COLUMN IF NOT EXISTS core_route_count_tier{tier} "
                f"INTEGER NOT NULL DEFAULT 0"
            ))
        conn.commit()
        print("  users.core_route_count_tier1..4 ready.")

        print("=== Dropping old users.core_route_count ===")
        conn.execute(text(
            "ALTER TABLE users DROP COLUMN IF EXISTS core_route_count"
        ))
        conn.commit()
        print("  users.core_route_count dropped.")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v23.py completed successfully.")
