"""
migrate_v2.py — Apply schema changes for the Luxus.docx updated flow.

Run once after pulling this update:
  cd backend
  python migrate_v2.py

Changes applied:
  1. Add new enum values to wallettype   (account)
  2. Add new enum values to transactiontype
     (deposit, transfer_in, transfer_out, agent_purchase)
  3. Create the `deposits` table
  4. Run SQLAlchemy create_all() to pick up any remaining new tables/columns
"""
import sys
import os

# Ensure the backend package is importable
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine, Base

# Import all models so Base.metadata is fully populated
import app.models  # noqa: F401


def run_migration():
    with engine.connect() as conn:
        # ── 1. New wallettype enum values ─────────────────────────────────────
        print("Adding 'account' to wallettype enum …")
        conn.execute(text(
            "ALTER TYPE wallettype ADD VALUE IF NOT EXISTS 'account';"
        ))
        conn.commit()

        # ── 2. New transactiontype enum values ────────────────────────────────
        new_tx_values = ["deposit", "transfer_in", "transfer_out", "agent_purchase"]
        for val in new_tx_values:
            print(f"Adding '{val}' to transactiontype enum …")
            conn.execute(text(
                f"ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS '{val}';"
            ))
            conn.commit()

        print("Enum migrations complete.")

    # ── 3. Create new tables (deposits) + any other missing tables ────────────
    print("Running create_all (new tables only) …")
    Base.metadata.create_all(bind=engine)
    print("Done.")


if __name__ == "__main__":
    run_migration()
    print("\n✅ migrate_v2.py completed successfully.")
