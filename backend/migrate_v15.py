"""
migrate_v15.py — Create the pack_purchases table for the on-chain (BEP-20 USDT)
pack-purchase rail (POST /distribution/pack/purchase + /distribution/pack/status).

This is a separate rail from the deposit-first matrix engine: the frontend pays
the upline split on-chain and the backend records each order's split + outcome.

Idempotent — safe to run more than once. Run once:

  cd backend
  python migrate_v15.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        print("=== Creating pack_purchases ===")
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS pack_purchases (
                id              SERIAL PRIMARY KEY,
                order_id        VARCHAR NOT NULL UNIQUE,
                buyer_id        INTEGER NOT NULL REFERENCES users(id),
                pack_name       VARCHAR NOT NULL,
                agent_tier      INTEGER NOT NULL,
                amount          NUMERIC(14, 4) NOT NULL,
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
            "CREATE INDEX IF NOT EXISTS ix_pack_purchases_order_id "
            "ON pack_purchases (order_id)"
        ))
        conn.commit()
        print("  pack_purchases ready.")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v15.py completed successfully.")
