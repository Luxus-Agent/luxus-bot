"""
Run this once to create all database tables.
Run from the backend/ directory:  python create_tables.py
"""
import app.models  # noqa: F401 — registers all models with Base

from app.database import Base, engine

if __name__ == "__main__":
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Done. All tables created successfully.")
