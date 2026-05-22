import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.config import settings
from app.database import SessionLocal
from app.core.security import hash_password

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
        existing = db.query(User).filter(User.is_admin == True).first()
        if existing:
            print(f"Admin already exists: {existing.email}")
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
