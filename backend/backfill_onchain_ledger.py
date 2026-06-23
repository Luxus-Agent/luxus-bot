"""
One-off, idempotent backfill: write the reporting-only Transaction rows for
on-chain pack purchases that succeeded BEFORE _mirror_onchain_ledger existed.

Background: successful `pack_purchases` rows recorded before commit 1ef9376
(which added _mirror_onchain_ledger) never produced internal Transaction rows,
so they were invisible in the admin dashboard / transaction history. This script
replays the mirror for every SUCCESS pack purchase that has no mirror rows yet.

Safe to re-run — it skips any order that already has a mirrored transaction
(matched by reference_id == order_id).

    cd backend && python backfill_onchain_ledger.py
"""
import logging

from app.api.distribution import _mirror_onchain_ledger
from app.database import SessionLocal
from app.models.pack_purchase import PackPurchase, PackPurchaseStatus
from app.models.transaction import Transaction

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backfill")


def main() -> None:
    db = SessionLocal()
    try:
        successes = (
            db.query(PackPurchase)
            .filter(PackPurchase.status == PackPurchaseStatus.SUCCESS)
            .order_by(PackPurchase.id.asc())
            .all()
        )
        log.info("Found %d successful pack purchases.", len(successes))

        mirrored = 0
        skipped = 0
        for record in successes:
            already = (
                db.query(Transaction.id)
                .filter(Transaction.reference_id == record.order_id)
                .first()
            )
            if already:
                skipped += 1
                log.info("  skip %s (already mirrored)", record.order_id)
                continue

            _mirror_onchain_ledger(db, record)
            mirrored += 1
            log.info(
                "  mirror %s (buyer_id=%s tier=%s amount=%s)",
                record.order_id, record.buyer_id, record.agent_tier, record.amount,
            )

        db.commit()
        log.info("Done. Mirrored %d, skipped %d.", mirrored, skipped)
    except Exception:
        db.rollback()
        log.exception("Backfill failed — no changes committed.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
