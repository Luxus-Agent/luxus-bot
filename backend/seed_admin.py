import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.config import settings
from app.database import SessionLocal
from app.core.security import hash_password, verify_password

# Import all models so SQLAlchemy resolves all relationships before any query
import app.models.user
import app.models.agent
import app.models.matrix
import app.models.wallet
import app.models.transaction
import app.models.deposit
import app.models.withdrawal
import app.models.wallet_address
import app.models.transfer_verification

from app.models.user import User


def seed_admin():
    db = SessionLocal()
    try:
        # Identify the admin by username (the stable key), falling back to any
        # existing admin row — so a changed ADMIN_EMAIL still matches the record.
        existing = (
            db.query(User).filter(User.username == settings.ADMIN_USERNAME).first()
            or db.query(User).filter(User.is_admin == True).first()
        )

        if existing:
            changes = []

            # Update email if it changed in .env
            if existing.email != settings.ADMIN_EMAIL:
                existing.email = settings.ADMIN_EMAIL
                changes.append("email")

            # Update password only if the .env password no longer matches the stored hash
            if not verify_password(settings.ADMIN_PASSWORD, existing.password_hash):
                existing.password_hash = hash_password(settings.ADMIN_PASSWORD)
                changes.append("password")

            # Make sure this account is still flagged as a usable admin
            if not existing.is_admin:
                existing.is_admin = True
                changes.append("is_admin")
            if not existing.is_active:
                existing.is_active = True
                changes.append("is_active")

            if changes:
                db.commit()
                print(f"Admin already exists ({existing.username}) — updated: {', '.join(changes)}")
            else:
                print(f"Admin already exists: {existing.email} — no changes needed")
            return

        admin = User(
            email=settings.ADMIN_EMAIL,
            username=settings.ADMIN_USERNAME,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            referral_code=settings.ADMIN_REFERRAL_CODE,
            is_email_verified=True,
            is_active=True,
            is_admin=True,
            sponsor_id=None,
        )
        db.add(admin)
        db.commit()
        print(f"Admin created: {settings.ADMIN_EMAIL} / username: {settings.ADMIN_USERNAME}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_admin()
