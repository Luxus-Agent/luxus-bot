import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SystemType(str, enum.Enum):
    STREAM = "stream"
    BOOST  = "boost"


class MatrixPosition(Base):
    """
    One user slot in a 3x3 forced matrix for a (agent_tier, system_type) pair.

    Tree is indexed breadth-first by position_number (1-based).
    Parent of position P: floor((P - 2) / 3) + 1  for P >= 2

    Fill counts track how many members joined below this slot:
      l1_filled: direct children  (threshold 3)
      l2_filled: grandchildren    (threshold 9)
      l3_filled: great-grandchildren (threshold 27)
    """

    __tablename__ = "matrix_positions"
    __table_args__ = (UniqueConstraint("agent_tier", "system_type", "position_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    system_type: Mapped[SystemType] = mapped_column(Enum(SystemType), nullable=False)
    position_number: Mapped[int] = mapped_column(Integer, nullable=False)

    l1_filled: Mapped[int] = mapped_column(Integer, default=0)
    l2_filled: Mapped[int] = mapped_column(Integer, default=0)
    l3_filled: Mapped[int] = mapped_column(Integer, default=0)

    l1_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    l2_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    l3_paid: Mapped[bool] = mapped_column(Boolean, default=False)

    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    reentry_count: Mapped[int] = mapped_column(Integer, default=0)
    is_dummy: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="matrix_positions")


class MatrixCounter(Base):
    """
    Tracks next available position_number per (agent_tier, system_type).
    Locked with SELECT FOR UPDATE to prevent concurrent position conflicts.
    """

    __tablename__ = "matrix_counters"
    __table_args__ = (UniqueConstraint("agent_tier", "system_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    system_type: Mapped[SystemType] = mapped_column(Enum(SystemType), nullable=False)
    next_position: Mapped[int] = mapped_column(Integer, default=1)
