"""
One-time backfill: populate the internal per-tier MAIN / REPURCHASE wallet
balances from on-chain CORE_INCOME commissions that were recorded before the
virtual 80/20 tracking was added (see core/wallet_ops.mirror_onchain_earning_split
and api/distribution._mirror_onchain_ledger).

On the on-chain rail the commission money lives in users' own wallets on-chain;
these internal wallet balances are DISPLAY/bookkeeping figures only. This script
recomputes them as 80% main / 20% repurchase reserve per (user, tier) from the
CORE_INCOME ledger.

Idempotent: it SETS the balances absolutely (not incrementally) from the ledger,
so it is safe to re-run. NOTE: it assumes CORE_INCOME is the only source of these
wallets' balances (true on the on-chain-only model). If you have used the admin
manual wallet-credit tool, re-running this would overwrite those manual credits
for the affected tiers — run it only on on-chain-only data.
"""
import os
import sys
from decimal import ROUND_HALF_UP, Decimal

sys.path.insert(0, os.path.dirname(__file__))

import app.models  # noqa: F401 — register all models
from sqlalchemy import func

from app.core.wallet_ops import REPURCHASE_RATE, get_or_create_wallet
from app.database import SessionLocal
from app.models.transaction import Transaction, TransactionType
from app.models.wallet import WalletType

FOUR = Decimal("0.0001")


def backfill() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(
                Transaction.user_id,
                Transaction.agent_tier,
                func.coalesce(func.sum(Transaction.amount), 0),
            )
            .filter(Transaction.transaction_type == TransactionType.CORE_INCOME)
            .group_by(Transaction.user_id, Transaction.agent_tier)
            .all()
        )
        if not rows:
            print("No CORE_INCOME rows found — nothing to backfill.")
            return

        for user_id, agent_tier, total in rows:
            gross = Decimal(str(total)).quantize(FOUR, rounding=ROUND_HALF_UP)
            reserve = (gross * REPURCHASE_RATE).quantize(FOUR, rounding=ROUND_HALF_UP)
            main_credit = gross - reserve

            main_wallet = get_or_create_wallet(db, user_id, agent_tier, WalletType.MAIN)
            main_wallet.balance = main_credit
            repurchase_wallet = get_or_create_wallet(db, user_id, agent_tier, WalletType.REPURCHASE)
            repurchase_wallet.balance = reserve

            print(
                f"user_id={user_id} tier={agent_tier}: gross=${gross} "
                f"-> main=${main_credit} reserve=${reserve}"
            )

        db.commit()
        print("Backfill complete.")
    finally:
        db.close()


if __name__ == "__main__":
    backfill()
