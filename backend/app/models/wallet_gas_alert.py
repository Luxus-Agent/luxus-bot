"""
WalletGasAlert — one row per platform-controlled wallet that pays its own BNB
gas (today: platform_fee, repurchase_reserve — see GAS_ALERT_WALLET_KEYS in
core/gas_alerts.py). Tracks whether that wallet's BNB balance is CURRENTLY
known to be low, so the low-gas email fires once on the ok -> low edge and
only re-arms once the balance recovers above threshold — never once per poll
while it stays low.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WalletGasAlert(Base):
    __tablename__ = "wallet_gas_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    is_low: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_alert_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
