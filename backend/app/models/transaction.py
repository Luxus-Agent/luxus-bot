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
    REPURCHASE_BUY = "repurchase_buy"    # Auto-repurchase: reserve consumed to re-buy a tier
    REPURCHASE_GAS = "repurchase_gas"    # Auto-repurchase: gas-fee portion → platform
    ADMIN_CREDIT = "admin_credit"        # Admin manual wallet credit (audit record)
    SOFTWARE_FEE = "software_fee"        # 10% platform fee deducted from every wallet credit
    WITHDRAWAL = "withdrawal"
    WITHDRAWAL_REFUND = "withdrawal_refund"  # Failed payout returned — reversal, not income
    SPONSOR_MILESTONE_INCOME = "sponsor_milestone_income"  # Matrix sponsor milestone payout
    DEPOSIT = "deposit"                  # Account balance top-up via NOWPayments
    TRANSFER_IN = "transfer_in"          # Received from another user
    TRANSFER_OUT = "transfer_out"        # Sent to another user
    AGENT_PURCHASE = "agent_purchase"    # Deducted from account balance for agent buy
    ADMIN_GENERATE = "admin_generate"    # Admin-minted funds into the admin's account balance
    PLATFORM_PROFIT = "platform_profit"  # Realized platform earnings (residuals, core-retained, transfer fee)
    STREAM_POOL_FUND = "stream_pool_fund"  # 30% of a purchase parked in the Stream matrix pool (per tier)
    BOOST_POOL_FUND = "boost_pool_fund"    # 9% of a purchase parked in the Boost matrix pool (global)
    ADMIN_INCOME = "admin_income"          # 1% of a purchase → admin income wallet (Boost allocation)


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
    # On-chain settlement tx hash, populated ONLY for rows this row's own crediting
    # function actually broadcast on-chain (Stream/Boost matrix payouts + their
    # sponsor-share bonus — see matrix_runtime._settle_or_credit). Core/payout-batch
    # rows are NOT written here; their tx hash is resolved separately via
    # wallet_ops.resolve_tx_hashes (reference_id -> PackPurchase/PayoutBatch), since
    # those settle as part of a shared multisender transaction, not a per-row one.
    # NULL means "still internal-only" — the signal the Completed/Pending status
    # (frontend) and GET /wallet/earnings' `completed` figure key off of.
    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="transactions")
