"""
migrate_v10.py — Add lowercase systemtype enum values to PostgreSQL.

migrate_v9.py synced transactiontype, withdrawalstatus, and wallettype but
missed systemtype. The DB still only has 'STREAM' and 'BOOST' (uppercase),
while SQLAlchemy sends the Python enum's .value which is lowercase.

Run once:
  cd backend
  python migrate_v10.py
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
        print(f"  '{value}' already in {type_name}")


def run():
    with engine.connect() as conn:
        print("=== Syncing systemtype enum ===")
        for val in ["stream", "boost"]:
            add_if_missing(conn, "systemtype", val)

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v10.py completed successfully.")
