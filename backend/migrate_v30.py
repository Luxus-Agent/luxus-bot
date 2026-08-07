"""
migrate_v30.py — Create the wallet_gas_alerts table, backing the low-gas email
alert for the platform's own gas-paying wallets (Platform Fee, Repurchase
Reserve — see core/gas_alerts.py). One row per watched wallet tracks whether
its BNB balance is CURRENTLY known to be low, so the admin only gets one
email when it crosses below threshold, not one every 20s while the dashboard
polls — see that module's docstring for the full mechanic.

Idempotent — safe to run more than once. Run once:

  cd backend
  python migrate_v30.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text

from app.database import engine


def run():
    with engine.connect() as conn:
        print("=== Creating wallet_gas_alerts ===")
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS wallet_gas_alerts (
                id                  SERIAL PRIMARY KEY,
                wallet_key          VARCHAR NOT NULL UNIQUE,
                is_low              BOOLEAN NOT NULL DEFAULT FALSE,
                last_alert_sent_at  TIMESTAMP,
                updated_at          TIMESTAMP
            )
            """
        ))
        conn.commit()
        print("  wallet_gas_alerts ready.")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v30.py completed successfully.")
