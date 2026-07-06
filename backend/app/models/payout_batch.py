"""
PayoutBatch — record for an admin-triggered on-chain distribution of members'
accumulated internal earnings (Stream/Boost matrix credits, Core commissions,
etc.) to their own BEP-20 wallets, via the same MultiSender contract used for
pack purchases — run in reverse (platform wallet -> many members instead of
buyer -> platform + uplines).

Mirrors the pack_purchases lifecycle (see app/models/pack_purchase.py):

Lifecycle:
  pending  -> created by POST /distribution/payout/create (snapshot returned to FE)
  success  -> POST /distribution/payout/status with the on-chain tx_hash; debits
             each recipient's withdrawable balance so it can't be paid out twice
  failed   -> POST /distribution/payout/status with a failure_reason (no debit)
"""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PayoutBatchStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class PayoutBatch(Base):
    __tablename__ = "payout_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Public reference returned to the frontend ("pob_..."), referenced by API 2.
    batch_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)

    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)

    status: Mapped[PayoutBatchStatus] = mapped_column(
        Enum(PayoutBatchStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=PayoutBatchStatus.PENDING,
    )

    # JSON snapshot of the exact recipient list returned by API 1 (user_id,
    # username, wallet_address, amount), so the debit recorded by API 2 always
    # matches what the frontend was told to pay.
    recipients_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_by = relationship("User")
