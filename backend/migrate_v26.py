"""
Migration v26 — Boost matrix payouts scale by the funding purchase's own tier.

Boost's global queue (`BOOST_TIER = 1` in matrix_runtime.py) previously sized
every real join's contribution off the queue's own fixed tier (always 1), so
every Boost credit was a flat $0.30/$0.60/$1.50/$3.60 no matter which tier the
buyer actually purchased. `matrix_engine._append_to_level` now sizes each
join's contribution off `contribution_tier` (the buyer's own purchased tier),
so a Growth-tier ($100 base) join funds a 10x bigger credit than a Trial-tier
($10 base) join, even though both land in the same shared Boost queue.

Because a level's cycle can now be funded by a MIX of tiers, level completion
(sponsor share / re-entry cost / platform residual) can no longer assume a
single `threshold * reentry_amount * multiplier` for the whole cycle — it's
computed from two new running totals instead:

  matrix_level_queues.cycle_gross_accumulated — actual $ contributed so far
  matrix_level_queues.cycle_wallet_paid       — actual $ already credited to the head

Both reset to 0 the instant the head pops, same as the existing
`real_joins_since_head` column.

Backfill: for any queue mid-cycle when this migration runs, the accumulators
are backfilled using tier_multiplier(q.agent_tier) — this reproduces EXACTLY
what those in-flight real joins were actually credited under the old code
(Boost's queue tier is always 1, so this is the true historical rate; Stream's
queue tier already equals every joiner's tier). Going forward, only NEW real
joins into these queues pick up the per-joiner-tier scaling — this backfill is
a one-time snapshot of "what's already happened", not a retroactive rewrite.

Idempotent (`ADD COLUMN IF NOT EXISTS`; the backfill recomputes from scratch
each run). Run from backend/:  python migrate_v26.py
"""
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.matrix_engine import PAYOUT_CONFIG, tier_multiplier
from app.database import engine
from app.models.matrix import MatrixLevelQueue

if __name__ == "__main__":
    print("=== Adding matrix_level_queues cycle accumulator columns ===")
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE matrix_level_queues "
            "ADD COLUMN IF NOT EXISTS cycle_gross_accumulated NUMERIC(14, 4) NOT NULL DEFAULT 0"
        ))
        conn.execute(text(
            "ALTER TABLE matrix_level_queues "
            "ADD COLUMN IF NOT EXISTS cycle_wallet_paid NUMERIC(14, 4) NOT NULL DEFAULT 0"
        ))
        conn.commit()
    print("  columns ready.")

    print("=== Backfilling cycle accumulators for in-progress cycles ===")
    db = Session(bind=engine)
    try:
        queues = db.query(MatrixLevelQueue).all()
        updated = 0
        for q in queues:
            cfg = PAYOUT_CONFIG[q.system_type][q.level]
            # Every real join in this queue's history so far was actually
            # credited at tier_multiplier(q.agent_tier) — true for Stream
            # (queue tier == joiner tier always) and true for pre-migration
            # Boost history too (queue tier was always 1, and that's exactly
            # what every historical join was credited at).
            per_join = (cfg.reentry_amount * tier_multiplier(q.agent_tier)).quantize(Decimal("0.0001"))
            real_count = q.real_joins_since_head
            paid_count = min(real_count, cfg.payout_join_count)
            gross = per_join * real_count
            paid = per_join * paid_count
            if q.cycle_gross_accumulated != gross or q.cycle_wallet_paid != paid:
                q.cycle_gross_accumulated = gross
                q.cycle_wallet_paid = paid
                updated += 1
        db.commit()
        print(f"  {len(queues)} queue(s) checked, {updated} updated.")
    finally:
        db.close()

    print("Done.")
