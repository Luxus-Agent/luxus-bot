import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TransactionType(str, enum.Enum):
    PURCHASE = "purchase"
    CORE_INCOME = "core_income"          # Core Agent (60%) — income received
    CORE_SENT = "core_sent"              # Core Agent (60%) — outgoing record on buyer
    STREAM_PAYOUT = "stream_payout"      # Stream Agent (30%) — matrix level payout
    BOOST_PAYOUT = "boost_payout"        # Boost Agent (10%) — matrix level payout
    REENTRY = "reentry"
    REPURCHASE_HOLD = "repurchase_hold"
    SOFTWARE_FEE = "software_fee"        # 10% platform fee deducted from every wallet credit
    WITHDRAWAL = "withdrawal"
    SPONSOR_MILESTONE_INCOME = "sponsor_milestone_income"  # Matrix sponsor milestone payout
    DEPOSIT = "deposit"                  # Account balance top-up via NOWPayments
    TRANSFER_IN = "transfer_in"          # Received from another user
    TRANSFER_OUT = "transfer_out"        # Sent to another user
    AGENT_PURCHASE = "agent_purchase"    # Deducted from account balance for agent buy
    ADMIN_GENERATE = "admin_generate"    # Admin-minted funds into the admin's account balance


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    amount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="transactions")
