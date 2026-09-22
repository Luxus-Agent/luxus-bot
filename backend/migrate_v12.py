"""
migrate_v12.py — Normalise wallets.wallet_type values to lowercase.

The wallets table has rows with uppercase 'ACCOUNT', 'MAIN', 'REPURCHASE'
from old code. SQLAlchemy can't deserialise them against the Python WalletType
enum whose values are lowercase.

Complication: some users ended up with BOTH an uppercase row and a lowercase
row for the same (user_id, agent_tier, type) pair. In that case we merge the
balance from the uppercase row into the lowercase row, then delete the
uppercase duplicate. Where no lowercase counterpart exists we simply rename.

Run once:
  cd backend
  python migrate_v12.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine

LOWERCASE_MAP = {
    "MAIN":       "main",
    "REPURCHASE": "repurchase",
    "ACCOUNT":    "account",
}


def run():
    with engine.connect() as conn:
        print("=== Normalising wallets.wallet_type rows to lowercase ===")

        for upper, lower in LOWERCASE_MAP.items():
            # Find all uppercase rows
            rows = conn.execute(
                text(
                    "SELECT id, user_id, agent_tier, balance "
                    "FROM wallets WHERE wallet_type::text = :v"
                ),
                {"v": upper},
            ).fetchall()

            if not rows:
                print(f"  No rows with '{upper}' -- skipped")
                continue

            renamed = 0
            merged = 0
            for row_id, user_id, agent_tier, balance in rows:
                # Check if a lowercase counterpart already exists
                dup = conn.execute(
                    text(
                        "SELECT id, balance FROM wallets "
                        "WHERE user_id = :uid AND agent_tier = :tier "
                        "AND wallet_type::text = :lower"
                    ),
                    {"uid": user_id, "tier": agent_tier, "lower": lower},
                ).fetchone()

                if dup:
                    # Merge: add balance to the lowercase row, delete the uppercase row
                    conn.execute(
                        text("UPDATE wallets SET balance = balance + :bal WHERE id = :id"),
                        {"bal": balance, "id": dup[0]},
                    )
                    conn.execute(text("DELETE FROM wallets WHERE id = :id"), {"id": row_id})
                    merged += 1
                else:
                    # No duplicate — just rename in place
                    conn.execute(
                        text(
                            "UPDATE wallets "
                            "SET wallet_type = CAST(:lower AS wallettype) "
                            "WHERE id = :id"
                        ),
                        {"lower": lower, "id": row_id},
                    )
                    renamed += 1

            conn.commit()
            if renamed:
                print(f"  Renamed  {renamed} rows: '{upper}' -> '{lower}'")
            if merged:
                print(f"  Merged   {merged} duplicate '{upper}' rows into existing '{lower}' rows")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v12.py completed successfully.")
