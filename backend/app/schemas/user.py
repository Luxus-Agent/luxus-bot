from pydantic import BaseModel, EmailStr, field_validator


class UserRegister(BaseModel):
    email: EmailStr
    username: str
    password: str
    sponsor_username: str  # Sponsor's username — required for all registrations (Q7)
    # BEP-20 wallet address (TokenPocket). Optional so existing flows keep working,
    # but the frontend register form should collect it — it is the address the
    # distribution / MultiSender endpoint pays each user's profit to.
    wallet_address: str | None = None

    @field_validator("wallet_address")
    @classmethod
    def wallet_address_must_be_bep20(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        if not v.startswith("0x") or len(v) != 42:
            raise ValueError("wallet_address must be a valid BEP-20 address (0x + 40 hex chars)")
        return v


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    referral_code: str
    wallet_address: str | None = None
    sponsor_id: int | None
    is_email_verified: bool
    is_admin: bool = False
    is_active: bool = True

    model_config = {"from_attributes": True}


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    otp: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: str
