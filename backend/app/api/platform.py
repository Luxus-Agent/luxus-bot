"""
Public-ish platform state endpoint.

Any authenticated user can read whether the platform is currently frozen so the
frontend can surface a banner and disable money-movement actions. Admin-only
freeze/unfreeze controls live in app/api/admin.py.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.platform_state import get_platform_setting
from app.database import get_db
from app.models.user import User

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get("/status")
def platform_status(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Lightweight freeze status for the current user's UI.

    Intentionally does NOT expose the freeze reason — that is an internal admin
    note and is only available via the admin-only GET /admin/platform/status.
    """
    setting = get_platform_setting(db)
    return {"is_frozen": setting.is_frozen}
