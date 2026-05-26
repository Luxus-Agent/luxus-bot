"""
migrate_v9.py — Sync all PostgreSQL enums with the current Python models.

The previous migrations used old names (PROACTIVE_INCOME, PROPORTION_PAYOUT,
SPECULATION_PAYOUT) that no longer exist in the Python code, and never added
the current names (core_income, stream_payout, boost_payout, etc.).
This migration ensures every value used by SQLAlchemy is present in the DB.

SQLAlchemy stores the Python enum's .value (lowercase), so that's what the
PostgreSQL enum needs. The uppercase variants from migrate_v6 are kept for
backward compat but are no longer the primary values.

Run once:
  cd backend
  python migrate_v9.py
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

        # ── transactiontype ───────────────────────────────────────────────────
        print("=== Syncing transactiontype enum ===")
        # All values currently used by TransactionType in models/transaction.py
        current_values = [
            # lowercase (.value) — what SQLAlchemy actually stores
            "purchase",
            "core_income",
            "core_sent",
            "stream_payout",
            "boost_payout",
            "reentry",
            "repurchase_hold",
            "software_fee",
            "withdrawal",
            "sponsor_milestone_income",
            "deposit",
            "transfer_in",
            "transfer_out",
            "agent_purchase",
        ]
        for val in current_values:
            add_if_missing(conn, "transactiontype", val)

        # ── withdrawalstatus ──────────────────────────────────────────────────
        print("\n=== Syncing withdrawalstatus enum ===")
        for val in ["pending", "processing", "sent", "failed",
                    "PENDING", "PROCESSING", "SENT", "FAILED"]:
            add_if_missing(conn, "withdrawalstatus", val)

        # ── wallettype ────────────────────────────────────────────────────────
        print("\n=== Syncing wallettype enum ===")
        for val in ["MAIN", "REPURCHASE", "ACCOUNT",
                    "main", "repurchase", "account"]:
            add_if_missing(conn, "wallettype", val)

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v9.py completed successfully.")
