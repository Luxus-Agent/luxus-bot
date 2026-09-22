"""
Migration v5 — three changes from Luxus (2).docx spec:

  1. matrix_positions.is_dummy  (BOOLEAN NOT NULL DEFAULT FALSE)
       Re-entry positions are marked dummy; they fill slots but earn no wallet payouts.

  2. transfer_verifications  (new table)
       Tracks which (sender, recipient) user pairs have completed email OTP verification.
       First transfer to a new recipient requires OTP; subsequent ones skip it.

  3. wallet_addresses  (new table)
       Stores BEP-20 withdrawal addresses that have been email-verified by the user.
       Withdrawals are only allowed to pre-verified addresses.

Run once after updating code:
    conda activate luxus
    cd backend
    python migrate_v5.py
"""

import sys
import psycopg2

DSN = "postgresql://luxus:dhanush@localhost/luxus"


def run():
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # 1. Add is_dummy to matrix_positions
        cur.execute("""
            ALTER TABLE matrix_positions
            ADD COLUMN IF NOT EXISTS is_dummy BOOLEAN NOT NULL DEFAULT FALSE;
        """)
        print("✓ matrix_positions.is_dummy added")

        # 2. Create transfer_verifications
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transfer_verifications (
                id              SERIAL PRIMARY KEY,
                sender_id       INTEGER NOT NULL REFERENCES users(id),
                recipient_id    INTEGER NOT NULL REFERENCES users(id),
                is_verified     BOOLEAN NOT NULL DEFAULT FALSE,
                pending_otp     VARCHAR,
                otp_expires_at  TIMESTAMP,
                created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (sender_id, recipient_id)
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS ix_transfer_verifications_sender
            ON transfer_verifications (sender_id);
        """)
        print("✓ transfer_verifications table created")

        # 3. Create wallet_addresses
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wallet_addresses (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(id),
                address         VARCHAR NOT NULL,
                label           VARCHAR,
                is_verified     BOOLEAN NOT NULL DEFAULT FALSE,
                pending_otp     VARCHAR,
                otp_expires_at  TIMESTAMP,
                created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, address)
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS ix_wallet_addresses_user_id
            ON wallet_addresses (user_id);
        """)
        print("✓ wallet_addresses table created")

        conn.commit()
        print("\nMigration v5 completed successfully.")

    except Exception as exc:
        conn.rollback()
        print(f"\nMigration failed — rolled back: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
