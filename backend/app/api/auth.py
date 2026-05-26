import random
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models.user import User
from app.schemas.user import (
    ForgotPasswordRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserLogin,
    UserOut,
    UserRegister,
    VerifyEmailRequest,
)
from app.services.email_service import (
    send_password_reset_email,
    send_resend_verification_email,
    send_verification_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])

OTP_VERIFY_EXPIRE_HOURS = 24
OTP_RESET_EXPIRE_HOURS  = 1


def _generate_otp() -> str:
    return str(random.randint(100000, 999999))


# ── Username availability check ───────────────────────────────────────────────

@router.get("/check-username")
def check_username(username: str, db: Session = Depends(get_db)):
    """Return whether a username is available. Used for live registration feedback."""
    taken = db.query(User).filter_by(username=username).first() is not None
    return {"available": not taken}


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserRegister,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if db.query(User).filter_by(email=payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if db.query(User).filter_by(username=payload.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    # Sponsor username is required — every user must register under a sponsor (Q7)
    sponsor = db.query(User).filter_by(username=payload.sponsor_username).first()
    if not sponsor:
        raise HTTPException(status_code=400, detail="Sponsor username not found")
    sponsor_position = len(sponsor.downline) + 1

    otp = _generate_otp()

    user = User(
        email=payload.email,
        username=payload.username,
        password_hash=hash_password(payload.password),
        referral_code=uuid.uuid4().hex[:8].upper(),
        sponsor_id=sponsor.id,
        sponsor_position=sponsor_position,
        is_email_verified=False,
        email_verification_code=otp,
        email_verification_expires=datetime.utcnow() + timedelta(hours=OTP_VERIFY_EXPIRE_HOURS),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    background_tasks.add_task(send_verification_email, user.email, otp)

    return user


# ── Verify email ──────────────────────────────────────────────────────────────

@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=payload.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_email_verified:
        return {"message": "Email already verified"}
    if (
        user.email_verification_code != payload.otp
        or not user.email_verification_expires
        or datetime.utcnow() > user.email_verification_expires
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    user.is_email_verified = True
    user.email_verification_code = None
    user.email_verification_expires = None
    db.commit()

    return {"message": "Email verified successfully"}


# ── Resend verification ───────────────────────────────────────────────────────

@router.post("/resend-verification")
async def resend_verification(
    payload: ResendVerificationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(email=payload.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_email_verified:
        return {"message": "Email already verified"}

    otp = _generate_otp()
    user.email_verification_code = otp
    user.email_verification_expires = datetime.utcnow() + timedelta(hours=OTP_VERIFY_EXPIRE_HOURS)
    db.commit()

    background_tasks.add_task(send_resend_verification_email, user.email, otp)

    return {"message": "Verification code sent"}


# ── Me (profile) ──────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_email_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in")
    return {"access_token": create_access_token(user.id)}


# ── Forgot password ───────────────────────────────────────────────────────────

@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(email=payload.email).first()
    # Always return 200 — never reveal whether the email exists
    if user:
        otp = _generate_otp()
        user.password_reset_code = otp
        user.password_reset_expires = datetime.utcnow() + timedelta(hours=OTP_RESET_EXPIRE_HOURS)
        db.commit()
        background_tasks.add_task(send_password_reset_email, user.email, otp)

    return {"message": "If that email is registered, a reset code has been sent"}


# ── Reset password ────────────────────────────────────────────────────────────

@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=payload.email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid reset code")
    if (
        user.password_reset_code != payload.otp
        or not user.password_reset_expires
        or datetime.utcnow() > user.password_reset_expires
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")

    user.password_hash = hash_password(payload.new_password)
    user.password_reset_code = None
    user.password_reset_expires = None
    db.commit()

    return {"message": "Password reset successfully"}
