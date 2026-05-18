import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TransactionType(str, enum.Enum):
    PURCHASE = "purchase"
    PROACTIVE_INCOME = "proactive_income"
    PROACTIVE_SENT = "proactive_sent"
    PROPORTION_PAYOUT = "proportion_payout"
    SPECULATION_PAYOUT = "speculation_payout"
    REENTRY = "reentry"
    REPURCHASE_HOLD = "repurchase_hold"
    WITHDRAWAL = "withdrawal"
    SPONSOR_MILESTONE_INCOME = "sponsor_milestone_income"  # Matrix sponsor milestone payout
    DEPOSIT = "deposit"          # Account balance top-up via NOWPayments
    TRANSFER_IN = "transfer_in"  # Received from another user
    TRANSFER_OUT = "transfer_out"  # Sent to another user
    AGENT_PURCHASE = "agent_purchase"  # Deducted from account balance for agent buy


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="transactions")
