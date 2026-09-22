from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.user import User


def get_user_by_username(db: Session, username: str) -> User | None:
    """Case-insensitive username lookup (client spec: usernames are not case
    sensitive; only passwords are — password verification is untouched by this
    and stays case-sensitive since it hashes the exact string)."""
    if not username:
        return None
    return db.query(User).filter(func.lower(User.username) == username.strip().lower()).first()


def usernames_equal(a: str | None, b: str | None) -> bool:
    """Case-insensitive username equality check."""
    if not a or not b:
        return False
    return a.strip().lower() == b.strip().lower()
