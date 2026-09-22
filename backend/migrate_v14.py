"""
migrate_v14.py — Add users.wallet_address for the TokenPocket distribution flow.

A primary BEP-20 wallet address is now collected at registration. It is the
address the consolidated distribution endpoint (GET /distribution/wallet-map)
reports as each user's payout target for the frontend TokenPocket / MultiSender
integration.

The column is nullable so pre-existing users (registered before this field) keep
loading; the distribution endpoint falls back to a user's latest verified
WalletAddress when this is empty.

Idempotent — safe to run more than once. Run once:

  cd backend
  python migrate_v14.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        print("=== Adding users.wallet_address ===")
        conn.execute(text(
            "ALTER TABLE users "
            "ADD COLUMN IF NOT EXISTS wallet_address VARCHAR"
        ))
        conn.commit()
        print("  users.wallet_address ready.")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v14.py completed successfully.")
