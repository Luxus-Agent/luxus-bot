"""
migrate_v6.py — Fix enum case mismatch between PostgreSQL and SQLAlchemy 2.x.

SQLAlchemy 2.x sends the enum NAMES (uppercase) to PostgreSQL, but migrate_v2
added values using the Python enum VALUES (lowercase). This script adds the
missing uppercase variants so all queries succeed.

Run once:
  cd backend
  python migrate_v6.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine


def add_if_missing(conn, type_name: str, value: str):
    result = conn.execute(text(
        "SELECT 1 FROM pg_enum "
        "JOIN pg_type ON pg_enum.enumtypid = pg_type.oid "
        "WHERE pg_type.typname = :t AND enumlabel = :v"
    ), {"t": type_name, "v": value})
    if result.fetchone() is None:
        conn.execute(text(f"ALTER TYPE {type_name} ADD VALUE '{value}'"))
        conn.commit()
        print(f"  Added '{value}' to {type_name}")
    else:
        print(f"  '{value}' already exists in {type_name} — skipped")


def run():
    with engine.connect() as conn:
        print("=== Fixing wallettype enum ===")
        for val in ["MAIN", "REPURCHASE", "ACCOUNT"]:
            add_if_missing(conn, "wallettype", val)

        print("\n=== Fixing transactiontype enum ===")
        for val in [
            "PURCHASE", "PROACTIVE_INCOME", "PROACTIVE_SENT",
            "PROPORTION_PAYOUT", "SPECULATION_PAYOUT",
            "REENTRY", "REPURCHASE_HOLD", "WITHDRAWAL",
            "DEPOSIT", "TRANSFER_IN", "TRANSFER_OUT",
            "AGENT_PURCHASE", "SPONSOR_MILESTONE_INCOME",
        ]:
            add_if_missing(conn, "transactiontype", val)

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\n✅ migrate_v6.py completed successfully.")
