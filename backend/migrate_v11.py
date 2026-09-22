"""
migrate_v11.py — Normalise transaction_type values to lowercase.

Old code inserted uppercase values (e.g. 'AGENT_PURCHASE', 'DEPOSIT') that no
longer exist in the Python TransactionType enum. SQLAlchemy can't deserialise
them, causing LookupError when loading the wallet/transaction pages.

This migration UPDATE-s every affected row to its lowercase equivalent and
removes the now-unused uppercase enum labels from the PostgreSQL type.

Run once:
  cd backend
  python migrate_v11.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine

# All TransactionType values — maps uppercase (legacy DB label) → lowercase (current)
LOWERCASE_MAP = {
    "PURCHASE":                 "purchase",
    "CORE_INCOME":              "core_income",
    "CORE_SENT":                "core_sent",
    "STREAM_PAYOUT":            "stream_payout",
    "BOOST_PAYOUT":             "boost_payout",
    "REENTRY":                  "reentry",
    "REPURCHASE_HOLD":          "repurchase_hold",
    "SOFTWARE_FEE":             "software_fee",
    "WITHDRAWAL":               "withdrawal",
    "SPONSOR_MILESTONE_INCOME": "sponsor_milestone_income",
    "DEPOSIT":                  "deposit",
    "TRANSFER_IN":              "transfer_in",
    "TRANSFER_OUT":             "transfer_out",
    "AGENT_PURCHASE":           "agent_purchase",
}


def run():
    with engine.connect() as conn:
        print("=== Normalising transaction_type rows to lowercase ===")

        for upper, lower in LOWERCASE_MAP.items():
            # Cast the column to text so Postgres doesn't reject uppercase
            # values that are not in the current enum definition.
            result = conn.execute(
                text("SELECT COUNT(*) FROM transactions WHERE transaction_type::text = :v"),
                {"v": upper},
            )
            count = result.scalar()
            if count:
                conn.execute(
                    text(
                        "UPDATE transactions "
                        "SET transaction_type = CAST(:lower AS transactiontype) "
                        "WHERE transaction_type::text = :upper"
                    ),
                    {"lower": lower, "upper": upper},
                )
                conn.commit()
                print(f"  Updated {count} rows: '{upper}' -> '{lower}'")
            else:
                print(f"  No rows with '{upper}' — skipped")

    print("\nDone.")


if __name__ == "__main__":
    run()
    print("\nmigrate_v11.py completed successfully.")
