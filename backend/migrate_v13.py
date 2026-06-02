"""
migrate_v13.py — Schema changes for the Core-routing and refund-classification fixes.

1. users.core_route_count
   New per-user counter that tracks how many times a user has been TARGETED as a
   Core recipient (sponsor/supreme). Its parity drives the odd/even keep-or-pass
   rule. Previously the rule counted only KEPT credits, which left a recipient
   stuck on "even" forever after their first pass-up (they then lost every
   subsequent Core payment). All existing users start at 0 — a clean baseline.

2. transactiontype enum: add 'withdrawal_refund'
   Failed-payout refunds were recorded as 'transfer_in' and therefore counted as
   income in the user's "Total In". They are now their own neutral type.

Both statements are idempotent. Run once:

  cd backend
  python migrate_v13.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine


def run():
    # 1. Add the users.core_route_count column (safe inside a transaction).
    with engine.connect() as conn:
        print("=== Adding users.core_route_count ===")
        conn.execute(text(
            "ALTER TABLE users "
            "ADD COLUMN IF NOT EXISTS core_route_count INTEGER NOT NULL DEFAULT 0"
        ))
        conn.commit()
        print("  users.core_route_count ready.")

    # 2. Add the 'withdrawal_refund' enum value. ALTER TYPE ... ADD VALUE cannot
    #    run inside a transaction block, so use an AUTOCOMMIT connection.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        print("=== Adding transactiontype 'withdrawal_refund' ===")
        conn.execute(text(
            "ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'withdrawal_refund'"
        ))
        print("  transactiontype 'withdrawal_refund' ready.")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v13.py completed successfully.")
