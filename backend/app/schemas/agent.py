from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator


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


class WalletAddressIn(BaseModel):
    address: str
    label: str | None = None

    @field_validator("address")
    @classmethod
    def address_must_be_bep20(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("0x") or len(v) != 42:
            raise ValueError("address must be a valid BEP-20 address (0x + 40 hex chars)")
        return v


class WalletAddressVerifyIn(BaseModel):
    address: str
    otp: str

    @field_validator("address")
    @classmethod
    def address_must_be_bep20(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("0x") or len(v) != 42:
            raise ValueError("address must be a valid BEP-20 address (0x + 40 hex chars)")
        return v


class WalletAddressOut(BaseModel):
    id: int
    address: str
    label: str | None
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Admin schemas ─────────────────────────────────────────────────────────────

class AdminUserOut(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    is_admin: bool
    sponsor_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminWalletCreditIn(BaseModel):
    user_id: int
    agent_tier: int
    amount: Decimal
    notes: str | None = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v


class AdminWalletDebitIn(BaseModel):
    user_id: int
    agent_tier: int
    amount: Decimal
    notes: str | None = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v


class AdminTransferIn(BaseModel):
    to_username: str
    amount: Decimal

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be greater than zero")
        return v


class PlatformFreezeIn(BaseModel):
    # Optional note explaining why the platform was frozen (stored for the audit trail).
    reason: str | None = None


class PlatformStatusOut(BaseModel):
    is_frozen: bool
    frozen_reason: str | None = None
    frozen_by: int | None = None
    frozen_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
