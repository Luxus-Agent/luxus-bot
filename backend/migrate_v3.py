"""
migrate_v3.py — Fix sponsor milestone transaction type.

Run once after pulling this update:
  cd backend
  python migrate_v3.py

Changes applied:
  1. Add 'sponsor_milestone_income' to transactiontype enum
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine


def run_migration():
    with engine.connect() as conn:
        print("Adding 'sponsor_milestone_income' to transactiontype enum …")
        conn.execute(text(
            "ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'sponsor_milestone_income';"
        ))
        conn.commit()
        print("Done.")


if __name__ == "__main__":
    run_migration()
    print("\n✅ migrate_v3.py completed successfully.")
