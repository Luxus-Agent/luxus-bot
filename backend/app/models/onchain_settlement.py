"""
OnchainSettlement — durable, idempotent record of every on-chain transfer the
backend itself broadcasts (Stream/Boost matrix payouts + sponsor shares, and the
auto-repurchase reserve consolidation).

Why it exists: those broadcasts happen while a purchase is being processed. If
the request later fails and the database transaction rolls back, a naive retry
would broadcast the SAME payout again — real USDT paid twice. This table is
written through its OWN connection and committed independently of the purchase
transaction, so the fact "payout <key> was broadcast as tx <hash>" survives a
rollback; a retry finds the key and reuses the hash instead of sending again.

Statuses:
  sending   — claim written, broadcast not yet confirmed to have happened. If it
              is still 'sending' later the process died mid-broadcast and the
              outcome is unknown (AMBIGUOUS): never auto-retried, needs a manual
              check of the signer wallet on the explorer.
  sent      — broadcast accepted by the node, tx_hash recorded.
  confirmed — mined and successful.
  pending   — broadcast but no receipt within the wait window (likely still
              mining); treated as paid.
  reverted  — mined but reverted (no funds moved); safe to retry.
  failed    — broadcast raised (nothing was sent); safe to retry.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OnchainSettlement(Base):
    __tablename__ = "onchain_settlements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)          # matrix_payout | repurchase
    dest_address: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="sending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
