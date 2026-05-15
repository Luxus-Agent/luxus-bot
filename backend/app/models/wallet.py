import enum

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WalletType(str, enum.Enum):
    MAIN = "main"            # Withdrawable balance
    REPURCHASE = "repurchase"  # 10% auto-hold per agent tier


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (UniqueConstraint("user_id", "agent_tier", "wallet_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    wallet_type: Mapped[WalletType] = mapped_column(Enum(WalletType), nullable=False)
    balance: Mapped[float] = mapped_column(Numeric(14, 4), default=0)

    user = relationship("User", back_populates="wallets")
