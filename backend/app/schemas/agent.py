from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator


class PurchaseRequest(BaseModel):
    agent_tier: int


class PurchaseOut(BaseModel):
    id: int
    agent_tier: int
    price: Decimal
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WalletOut(BaseModel):
    agent_tier: int
    wallet_type: str
    balance: Decimal

    model_config = {"from_attributes": True}


class TransactionOut(BaseModel):
    id: int
    agent_tier: int
    transaction_type: str
    amount: Decimal
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MatrixPositionOut(BaseModel):
    id: int
    agent_tier: int
    system_type: str
    position_number: int
    l1_filled: int
    l2_filled: int
    l3_filled: int
    l1_paid: bool
    l2_paid: bool
    l3_paid: bool
    completed: bool
    reentry_count: int

    model_config = {"from_attributes": True}


class WithdrawalIn(BaseModel):
    agent_tier: int
    amount: Decimal
    wallet_address: str

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be greater than zero")
        return v

    @field_validator("wallet_address")
    @classmethod
    def address_must_be_bep20(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("0x") or len(v) != 42:
            raise ValueError("wallet_address must be a valid BEP-20 address (0x + 40 hex chars)")
        return v

    @field_validator("agent_tier")
    @classmethod
    def tier_must_be_valid(cls, v: int) -> int:
        if v not in (10, 20, 50, 100):
            raise ValueError("agent_tier must be 10, 20, 50, or 100")
        return v


class WithdrawalOut(BaseModel):
    id: int
    agent_tier: int
    amount: Decimal
    wallet_address: str
    status: str
    scheduled_for: datetime
    created_at: datetime
    processed_at: datetime | None = None
    nowpayments_payout_id: str | None = None

    model_config = {"from_attributes": True}
