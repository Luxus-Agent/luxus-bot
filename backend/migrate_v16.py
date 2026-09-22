"""
Migration v16 — recreate the Stream / Boost matrix tables.

Adds `matrix_positions` and `matrix_counters` (removed in the on-chain migration,
restored for the Stream + Boost matrix engines). Idempotent: create_all only
creates tables that don't already exist; existing tables/data are untouched.

Run from backend/:  python migrate_v16.py
"""
import app.models  # noqa: F401 — register all models with Base

from app.database import Base, engine
from app.models.matrix import MatrixCounter, MatrixPosition

if __name__ == "__main__":
    print("Creating matrix tables (matrix_positions, matrix_counters) if missing...")
    Base.metadata.create_all(
        bind=engine,
        tables=[MatrixPosition.__table__, MatrixCounter.__table__],
    )
    print("Done.")
