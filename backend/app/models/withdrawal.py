import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WithdrawalStatus(str, enum.Enum):
    PENDING = "pending"        # Requested, awaiting 24h hold
    PROCESSING = "processing"  # Celery picked it up
    SENT = "sent"              # NOWPayments payout created
    FAILED = "failed"          # Payout failed — balance refunded


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[WithdrawalStatus] = mapped_column(
        Enum(WithdrawalStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=WithdrawalStatus.PENDING,
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    nowpayments_payout_id: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user = relationship("User", back_populates="withdrawals")
