"""
reset_db.py — DESTRUCTIVE. Drops every table and recreates them with the current
schema, giving a clean slate for fresh testing. Re-seed the admin afterwards with
`python seed_admin.py`.

Run from the backend/ directory:  python reset_db.py
"""
import app.models  # noqa: F401 — registers all models with Base

from sqlalchemy import text

from app.database import Base, engine

if __name__ == "__main__":
    # Drop the entire public schema (CASCADE handles every FK / table, including
    # ones not registered in SQLAlchemy metadata like transfer_verifications),
    # then recreate it empty.
    print("Dropping public schema (CASCADE)...")
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    print("Recreating all tables...")
    Base.metadata.create_all(bind=engine)
    print("Done. Database is fresh.")
