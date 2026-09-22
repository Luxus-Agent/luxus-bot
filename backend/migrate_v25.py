"""
Migration v25 — add `transactions.tx_hash`.

Supports instant on-chain settlement for Stream/Boost matrix payouts and their
sponsor-share bonus (app/core/matrix_runtime.py's `_settle_or_credit`, backed
by app/core/onchain.py's `send_matrix_payout_settlement`). When a payout
settles on-chain, its headline Transaction row gets its own `tx_hash`; NULL
means it stayed internal-only (feature disabled, broadcast failed, or the
recipient has no wallet address on file) — the same signal the frontend's
Completed/Pending status and `GET /wallet/earnings`'s `completed` figure now
key off of for these rows, instead of a flat per-type assumption.

Idempotent (`ADD COLUMN IF NOT EXISTS`). Run from backend/:  python migrate_v25.py
"""
from sqlalchemy import text

from app.database import engine

if __name__ == "__main__":
    print("=== Adding transactions.tx_hash ===")
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS tx_hash VARCHAR"
        ))
        conn.commit()
    print("Done.")
