"""
migrate_v4.py — Add is_admin column to users table.

Run once after pulling this update:
  cd backend
  python migrate_v4.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.database import engine, Base
import app.models  # noqa: F401


def run_migration():
    with engine.connect() as conn:
        print("Adding 'is_admin' column to users table …")
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;"
        ))
        conn.commit()
        print("Done.")

    print("Running create_all …")
    Base.metadata.create_all(bind=engine)
    print("Done.")


if __name__ == "__main__":
    run_migration()
    print("\n✅ migrate_v4.py completed successfully.")
