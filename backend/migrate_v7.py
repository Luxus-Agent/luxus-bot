"""
migrate_v7.py — Add 'software_fee' to the transactiontype PostgreSQL enum.

This migration supports Q4: software fee (10%) is now a separate deduction
from repurchase reserve (10%), recorded as its own transaction type.

Run once:
  cd backend
  python migrate_v7.py
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
        print("=== Adding software_fee to transactiontype enum ===")
        add_if_missing(conn, "transactiontype", "software_fee")
        add_if_missing(conn, "transactiontype", "SOFTWARE_FEE")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\n✅ migrate_v7.py completed successfully.")
