"""
Deposit model — tracks NOWPayments deposit invoices.

A deposit credits the user's ACCOUNT balance (agent_tier=0, WalletType.ACCOUNT).
Users spend their account balance to purchase AI Agent tiers.

Order ID format:  presz_deposit_{deposit_id}_{unix_ts}
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Deposit(Base):
    __tablename__ = "deposits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    amount_usd: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)

    # NOWPayments order ID set after invoice is created
    order_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # pending → completed | failed
    status: Mapped[str] = mapped_column(String, default="pending")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user = relationship("User", back_populates="deposits")
