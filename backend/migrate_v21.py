"""
migrate_v21.py — Enforce wallet address uniqueness on `users.wallet_address`.

Adds a case-insensitive unique index (checksummed vs lowercase input refer to
the same wallet) so two accounts can never register with the same BEP-20
address. NULLs are excluded from the index, so legacy rows without a wallet
address don't conflict with each other or block the migration.

Idempotent — safe to run more than once. Run once:

  cd backend
  python migrate_v21.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        print("=== Checking for existing duplicate wallet addresses ===")
        dupes = conn.execute(text(
            """
            SELECT lower(wallet_address) AS addr, count(*)
            FROM users
            WHERE wallet_address IS NOT NULL
            GROUP BY lower(wallet_address)
            HAVING count(*) > 1
            """
        )).fetchall()
        if dupes:
            print("  Found duplicate wallet addresses — resolve these before re-running:")
            for addr, count in dupes:
                print(f"    {addr}: {count} accounts")
            return

        print("=== Creating unique index on users.wallet_address (case-insensitive) ===")
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_wallet_address_lower "
            "ON users (lower(wallet_address)) "
            "WHERE wallet_address IS NOT NULL"
        ))
        conn.commit()
        print("  ix_users_wallet_address_lower ready.")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v21.py completed successfully.")
