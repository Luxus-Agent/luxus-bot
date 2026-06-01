"""
One-time, idempotent backfill of realized PLATFORM_PROFIT ledger entries for events
that happened BEFORE profit-ledgering was added:

  1. Matrix level residuals  — for every completed (non-dummy) matrix level.
  2. Core retained           — old CORE_SENT rows that were "retained by platform".
  3. Transfer fees           — the 1% gap on past user transfers (TRANSFER_OUT - TRANSFER_IN).

Software fees are already ledgered (SOFTWARE_FEE) and are NOT touched here.

Safe to re-run: every insert uses a deterministic reference_id and is skipped if a
PLATFORM_PROFIT row with that reference already exists.

Run from backend/:  python backfill_platform_profit.py
"""
from decimal import Decimal

from app.database import SessionLocal
from app.core.matrix_engine import PAYOUT_CONFIG, tier_multiplier
from app.models.matrix import MatrixPosition, SystemType
from app.models.transaction import Transaction, TransactionType
from app.models.user import User


def _existing_refs(db) -> set[str]:
    rows = (
        db.query(Transaction.reference_id)
        .filter(Transaction.transaction_type == TransactionType.PLATFORM_PROFIT)
        .all()
    )
    return {r[0] for r in rows if r[0]}


def backfill_residuals(db, existing: set[str]) -> Decimal:
    total = Decimal("0")
    positions = db.query(MatrixPosition).filter_by(is_dummy=False).all()
    for pos in positions:
        cfg_levels = PAYOUT_CONFIG[pos.system_type]
        mult = tier_multiplier(pos.agent_tier)
        for level, paid in ((1, pos.l1_paid), (2, pos.l2_paid), (3, pos.l3_paid)):
            if not paid:
                continue
            cfg = cfg_levels[level]
            residual = (
                cfg.threshold * cfg.reentry_amount
                - cfg.wallet_amount
                - cfg.reentry_count * cfg.reentry_amount
                - cfg.sponsor_on_completion
            ) * mult
            if residual <= 0:
                continue
            ref = f"residual_{pos.system_type.value}_t{pos.agent_tier}_pos{pos.id}_L{level}"
            if ref in existing:
                continue
            # Stamp with the source event's time (the level payout, else the position
            # placement) so backfilled rows interleave naturally in the ledger feed.
            payout = (
                db.query(Transaction)
                .filter(Transaction.reference_id == f"matrix_pos_{pos.id}_L{level}")
                .first()
            )
            src_dt = payout.created_at if payout else pos.created_at
            db.add(Transaction(
                user_id=pos.user_id,
                agent_tier=pos.agent_tier,
                transaction_type=TransactionType.PLATFORM_PROFIT,
                amount=residual,
                reference_id=ref,
                notes=f"[backfill] {pos.system_type.value} L{level} level residual → platform",
                created_at=src_dt,
            ))
            existing.add(ref)
            total += residual
    return total


def backfill_core_retained(db, existing: set[str]) -> Decimal:
    total = Decimal("0")
    rows = (
        db.query(Transaction)
        .filter(
            Transaction.transaction_type == TransactionType.CORE_SENT,
            Transaction.notes.ilike("%retained by platform%"),
        )
        .all()
    )
    for tx in rows:
        ref = f"core_retained_backfill_{tx.id}"
        if ref in existing:
            continue
        db.add(Transaction(
            user_id=tx.user_id,
            agent_tier=tx.agent_tier,
            transaction_type=TransactionType.PLATFORM_PROFIT,
            amount=Decimal(str(tx.amount)),
            reference_id=ref,
            notes=f"[backfill] core retained (no sponsor) from tx #{tx.id}",
            created_at=tx.created_at,
        ))
        existing.add(ref)
        total += Decimal(str(tx.amount))
    return total


def backfill_transfer_fees(db, existing: set[str]) -> Decimal:
    """Fee = TRANSFER_OUT amount - matching TRANSFER_IN amount (same reference_id).
    Admin fee-free transfers net to 0 and are skipped automatically."""
    total = Decimal("0")
    outs = (
        db.query(Transaction)
        .filter(Transaction.transaction_type == TransactionType.TRANSFER_OUT)
        .all()
    )
    for tx in outs:
        if not tx.reference_id:
            continue
        tin = (
            db.query(Transaction)
            .filter(
                Transaction.transaction_type == TransactionType.TRANSFER_IN,
                Transaction.reference_id == tx.reference_id,
            )
            .first()
        )
        if not tin:
            continue
        fee = Decimal(str(tx.amount)) - Decimal(str(tin.amount))
        if fee <= 0:
            continue
        ref = f"{tx.reference_id}_fee"
        if ref in existing:
            continue
        db.add(Transaction(
            user_id=tx.user_id,
            agent_tier=tx.agent_tier,
            transaction_type=TransactionType.PLATFORM_PROFIT,
            amount=fee,
            reference_id=ref,
            notes=f"[backfill] 1% transfer fee from tx #{tx.id}",
            created_at=tx.created_at,
        ))
        existing.add(ref)
        total += fee
    return total


if __name__ == "__main__":
    db = SessionLocal()
    try:
        existing = _existing_refs(db)
        r = backfill_residuals(db, existing)
        c = backfill_core_retained(db, existing)
        t = backfill_transfer_fees(db, existing)
        db.commit()
        print(f"Backfilled residuals:      ${r:.4f}")
        print(f"Backfilled core-retained:  ${c:.4f}")
        print(f"Backfilled transfer fees:  ${t:.4f}")
        print(f"Total new PLATFORM_PROFIT:  ${r + c + t:.4f}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
