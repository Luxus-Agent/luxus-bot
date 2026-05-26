"""
migrate_v8.py — Create the webhook_events table for IPN idempotency.

This table guards against duplicate NOWPayments IPN events (same payment_id +
status) by storing a unique event_id for every terminal IPN we process.
A race condition between two simultaneous IPNs fails fast on the UNIQUE
constraint before any business logic (e.g. balance credit) runs.

Run once:
  cd backend
  python migrate_v8.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        print("=== Creating webhook_events table ===")

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS webhook_events (
                id                SERIAL PRIMARY KEY,
                event_id          VARCHAR(255) NOT NULL UNIQUE,
                event_type        VARCHAR(50)  NOT NULL,
                order_id          VARCHAR(255),
                payload           JSONB,
                processing_status VARCHAR(20)  NOT NULL DEFAULT 'success',
                error_message     TEXT,
                created_at        TIMESTAMP    NOT NULL DEFAULT NOW()
            )
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_webhook_events_event_id
            ON webhook_events (event_id)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_webhook_events_order_id
            ON webhook_events (order_id)
        """))

        conn.commit()
        print("  webhook_events table ready.")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v8.py completed successfully.")
