from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Distribution base — the amount the 60/30/10 revenue split is computed off.
AGENT_TIER_PRICES = {1: 10, 2: 20, 3: 50, 4: 100}

# Flat platform fee added on top of the base price (per the client "purchase cost"
# spec). The buyer pays base + fee; the extra goes straight to the platform profit
# wallet and is NOT part of the revenue split. Applies to repurchase too.
AGENT_TIER_PLATFORM_FEE = {1: 1, 2: 2, 3: 5, 4: 11}

# What the buyer actually pays for a tier (base + platform fee):
#   Agent 1 $11  ·  Agent 2 $22  ·  Agent 3 $55  ·  Agent 4 $111
AGENT_TIER_COST = {t: AGENT_TIER_PRICES[t] + AGENT_TIER_PLATFORM_FEE[t] for t in AGENT_TIER_PRICES}


class AgentPurchase(Base):
    __tablename__ = "agent_purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    status: Mapped[str] = mapped_column(String, default="pending")  # pending | active
    payment_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user = relationship("User", back_populates="purchases")
