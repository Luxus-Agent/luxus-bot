"""
migrate_v20.py — Create the payout_batches table for the admin-triggered member
payout rail (POST /distribution/payout/create + /distribution/payout/status).

This mirrors pack_purchases but runs the MultiSender contract in reverse:
platform wallet -> every member with a positive withdrawable balance, instead
of buyer -> platform + uplines.

Idempotent — safe to run more than once. Run once:

  cd backend
  python migrate_v20.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        print("=== Creating payout_batches ===")
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS payout_batches (
                id              SERIAL PRIMARY KEY,
                batch_id        VARCHAR NOT NULL UNIQUE,
                created_by_id   INTEGER NOT NULL REFERENCES users(id),
                total_amount    NUMERIC(14, 4) NOT NULL,
                status          VARCHAR NOT NULL DEFAULT 'pending',
                recipients_json TEXT,
                tx_hash         VARCHAR,
                failure_reason  VARCHAR,
                created_at      TIMESTAMP,
                recorded_at     TIMESTAMP
            )
            """
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_payout_batches_batch_id "
            "ON payout_batches (batch_id)"
        ))
        conn.commit()
        print("  payout_batches ready.")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v20.py completed successfully.")
