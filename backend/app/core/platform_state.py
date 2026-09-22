"""
Helpers for the platform-wide freeze (kill switch).

A single PlatformSetting row (id=1) stores whether the platform is frozen.
When frozen, all money-movement flows are paused; admins can lift it.
"""
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.platform_setting import PLATFORM_SETTING_ID, PlatformSetting

# HTTP 423 Locked — the platform is temporarily frozen by an admin.
PLATFORM_FROZEN_MESSAGE = (
    "The platform is temporarily frozen by the administrator. "
    "Deposits, withdrawals, transfers, and agent purchases are paused. "
    "Please try again later."
)


def get_platform_setting(db: Session) -> PlatformSetting:
    """Return the singleton platform-settings row, creating it (unfrozen) if absent."""
    setting = db.get(PlatformSetting, PLATFORM_SETTING_ID)
    if setting is None:
        setting = PlatformSetting(id=PLATFORM_SETTING_ID, is_frozen=False)
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


def is_platform_frozen(db: Session) -> bool:
    """True if the global kill switch is engaged."""
    return get_platform_setting(db).is_frozen


def ensure_platform_active(db: Session) -> None:
    """
    Raise HTTP 423 if the global kill switch is engaged. NO admin bypass —
    unlike `require_platform_active` (the FastAPI dependency gating regular
    user purchase endpoints, which lets admins keep operating), this is for
    every code path that actually moves money — settlement, matrix payouts,
    auto-repurchase, and admin-triggered payout/treasury actions — so freeze
    is a true full stop regardless of who or what triggers it.
    """
    if is_platform_frozen(db):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=PLATFORM_FROZEN_MESSAGE,
        )


def set_platform_frozen(
    db: Session,
    frozen: bool,
    admin_id: int | None = None,
    reason: str | None = None,
) -> PlatformSetting:
    """Engage or release the global freeze and record who/when/why."""
    setting = get_platform_setting(db)
    setting.is_frozen = frozen
    if frozen:
        setting.frozen_by = admin_id
        setting.frozen_at = datetime.utcnow()
        setting.frozen_reason = reason
    else:
        # Keep the last reason for the audit trail but clear the active flag.
        setting.frozen_by = admin_id
        setting.frozen_at = None
    db.commit()
    db.refresh(setting)
    return setting
