"""
Helpers for the platform-wide freeze (kill switch).

A single PlatformSetting row (id=1) stores whether the platform is frozen.
When frozen, all user money-movement flows are paused; admins can lift it.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.platform_setting import PLATFORM_SETTING_ID, PlatformSetting


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
