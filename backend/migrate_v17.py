"""
Migration v17 — add the auto-repurchase / admin-credit transaction types.

The `transactions.transaction_type` column is a native Postgres ENUM, so new
TransactionType members must be added to the DB type with ALTER TYPE ... ADD VALUE
before rows using them can be inserted. This syncs the DB enum with every value
currently defined in app.models.transaction.TransactionType — covering the new
auto-repurchase types (repurchase_buy, repurchase_gas), the admin_credit fix for
the old PROPORTION_PAYOUT bug, and the matrix pool/admin types
(stream_pool_fund, boost_pool_fund, admin_income) added with the matrix engine.

Idempotent (uses IF NOT EXISTS). Run from backend/:  python migrate_v17.py
"""
from sqlalchemy import text

from app.database import engine
from app.models.transaction import TransactionType

if __name__ == "__main__":
    print("Syncing transactiontype enum values with the model...")
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older
    # Postgres; AUTOCOMMIT keeps each statement standalone.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        existing = {
            r[0] for r in conn.execute(text(
                "SELECT enumlabel FROM pg_enum e "
                "JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'transactiontype'"
            ))
        }
        for member in TransactionType:
            if member.value in existing:
                continue
            conn.execute(text(
                f"ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS '{member.value}'"
            ))
            print(f"  • added {member.value}")
    print("Done.")
