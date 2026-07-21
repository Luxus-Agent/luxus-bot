from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.platform_state import PLATFORM_FROZEN_MESSAGE, is_platform_frozen
from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter_by(id=user_id, is_active=True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_platform_active(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """
    Gate for money-movement endpoints. Blocks regular users with HTTP 423 while
    the global kill switch is engaged. Admin accounts are never blocked so they
    can keep operating and lift the freeze. Returns the current user on success.
    """
    if current_user.is_admin:
        return current_user

    if is_platform_frozen(db):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=PLATFORM_FROZEN_MESSAGE,
        )
    return current_user
