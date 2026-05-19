from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TransferVerification(Base):
    """
    Tracks whether a (sender, recipient) pair has been verified via email OTP.
    Once verified, all future transfers from sender → recipient skip the OTP step.
    """

    __tablename__ = "transfer_verifications"
    __table_args__ = (UniqueConstraint("sender_id", "recipient_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_otp: Mapped[str | None] = mapped_column(String, nullable=True)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
