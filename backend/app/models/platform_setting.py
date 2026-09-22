"""
PlatformSetting — a single-row table that holds platform-wide operational state.

Currently it backs the global "freeze" kill switch: when ``is_frozen`` is True,
all user money-movement flows (deposit, withdraw, transfer, agent purchase) are
blocked until an admin lifts the freeze. Admin accounts are never blocked.

The table always has exactly one row with id=1 (created lazily on first read).
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# The singleton row id — there is only ever one platform-settings row.
PLATFORM_SETTING_ID = 1


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always PLATFORM_SETTING_ID

    # Global kill switch — when True, all user financial flows are paused.
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Audit trail for the most recent freeze action.
    frozen_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    frozen_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
