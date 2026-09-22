"""
PackPurchase — record for the on-chain (BEP-20 USDT) pack-purchase rail.

This is a SEPARATE rail from the deposit-first + Core/Stream/Boost matrix engine
(`agent_purchases`). When a user buys a pack, the frontend pays the upline split
directly on-chain from the buyer's connected wallet; the backend only computes the
validated recipient split (API 1) and records the outcome (API 2). No internal
Wallet / Transaction ledger rows are written for this rail.

Lifecycle:
  pending  → created by POST /distribution/pack/purchase (split returned to FE)
  success  → POST /distribution/pack/status with the on-chain tx_hash
  failed   → POST /distribution/pack/status with a failure_reason
"""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PackPurchaseStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class PackPurchase(Base):
    __tablename__ = "pack_purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Public reference returned to the frontend ("ord_..."), referenced by API 2.
    order_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)

    buyer_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    pack_name: Mapped[str] = mapped_column(String, nullable=False)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)

    status: Mapped[PackPurchaseStatus] = mapped_column(
        Enum(PackPurchaseStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=PackPurchaseStatus.PENDING,
    )

    # JSON snapshot of the exact recipient split returned by API 1, so the outcome
    # recorded by API 2 always matches what the frontend was told to pay.
    recipients_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    buyer = relationship("User")
