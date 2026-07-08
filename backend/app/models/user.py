import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)

    referral_code: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, default=lambda: uuid.uuid4().hex[:8].upper()
    )

    # Primary BEP-20 wallet address collected at registration. Used by the
    # TokenPocket / MultiSender distribution endpoint to know where each user's
    # credited amount should be sent. Nullable so pre-existing users (registered
    # before this field) still load; the distribution endpoint falls back to the
    # user's latest verified WalletAddress when this is empty.
    wallet_address: Mapped[str | None] = mapped_column(String, nullable=True)
    sponsor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    # Position in sponsor's direct downline (1-based) — used by Core odd/even routing
    sponsor_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # How many times this user has been TARGETED as a Core recipient (sponsor or
    # supreme). Incremented on every targeting — whether the amount is kept (odd)
    # or passed up (even) — so the odd/even alternation is preserved. Counting
    # only kept credits (the old behaviour) left a recipient stuck on "even"
    # forever after their first pass-up.
    core_route_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Email verification OTP
    email_verification_code: Mapped[str | None] = mapped_column(String, nullable=True)
    email_verification_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Password reset OTP
    password_reset_code: Mapped[str | None] = mapped_column(String, nullable=True)
    password_reset_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sponsor: Mapped["User | None"] = relationship("User", remote_side=[id], backref="downline")
    purchases = relationship("AgentPurchase", back_populates="user")
    wallets = relationship("Wallet", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    wallet_addresses = relationship("WalletAddress", back_populates="user")

    __table_args__ = (
        # Case-insensitive uniqueness (checksummed vs lowercase input refer to
        # the same wallet) — NULLs excluded, so legacy rows without a wallet
        # address don't conflict with each other.
        Index(
            "ix_users_wallet_address_lower",
            text("lower(wallet_address)"),
            unique=True,
            postgresql_where=text("wallet_address IS NOT NULL"),
        ),
    )
