import logging
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.api.deps import get_current_user
from app.core import rate_limit
from app.core.security import create_access_token, hash_password, verify_password
from app.core.user_lookup import get_user_by_username
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
# Wrong guesses allowed against ONE issued code before it is invalidated and a
# new one must be requested (which is itself rate limited below).
OTP_MAX_ATTEMPTS = 5


def _generate_otp() -> str:
    # Cryptographically secure 6-digit code (never the `random` module).
    return str(secrets.randbelow(900000) + 100000)


def _otp_matches(stored: str | None, supplied: str) -> bool:
    """Constant-time comparison; a missing stored code never matches."""
    return bool(stored) and secrets.compare_digest(stored, (supplied or "").strip())


# ── Username availability check ───────────────────────────────────────────────

@router.get("/check-username")
def check_username(request: Request, username: str, db: Session = Depends(get_db)):
    """Return whether a username is available. Used for live registration feedback.
    Case-insensitive — "Alice" and "alice" are the same username."""
    rate_limit.enforce("check_username", rate_limit.client_ip(request), 120, 60)
    taken = get_user_by_username(db, username) is not None
    return {"available": not taken}


def _wallet_address_taken(db: Session, wallet_address: str) -> bool:
    """Case-insensitive lookup — BEP-20 addresses may be entered/connected in
    either checksummed or lowercase form, and both refer to the same wallet."""
    return (
        db.query(User)
        .filter(func.lower(User.wallet_address) == wallet_address.lower())
        .first()
        is not None
    )


# ── Wallet address availability check ─────────────────────────────────────────

@router.get("/check-wallet-address")
def check_wallet_address(request: Request, wallet_address: str, db: Session = Depends(get_db)):
    """Return whether a BEP-20 wallet address is free to register with. Each
    wallet may only be attached to one account — used for live registration
    feedback, mirroring /auth/check-username."""
    rate_limit.enforce("check_wallet", rate_limit.client_ip(request), 120, 60)
    taken = _wallet_address_taken(db, wallet_address)
    return {"available": not taken}


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    payload: UserRegister,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    rate_limit.enforce("register", rate_limit.client_ip(request), 20, 3600)
    if db.query(User).filter_by(email=payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if get_user_by_username(db, payload.username) is not None:
        raise HTTPException(status_code=400, detail="Username already taken")
    if payload.wallet_address and _wallet_address_taken(db, payload.wallet_address):
        raise HTTPException(status_code=400, detail="Wallet address already registered to another account")

    # Sponsor username is required — every user must register under a sponsor (Q7)
    sponsor = get_user_by_username(db, payload.sponsor_username)
    if not sponsor:
        raise HTTPException(status_code=400, detail="Sponsor username not found")
    sponsor_position = len(sponsor.downline) + 1

    otp = _generate_otp()

    user = User(
        email=payload.email,
        username=payload.username,
        password_hash=hash_password(payload.password),
        referral_code=uuid.uuid4().hex[:8].upper(),
        wallet_address=payload.wallet_address,
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

    logger.info(
        "AUTH register: user_id=%d username=%s email=%s sponsor=%s joined=%s",
        user.id, user.username, user.email, payload.sponsor_username,
        user.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
    )
    logger.info("AUTH otp_sent: type=email_verification user_id=%d email=%s", user.id, user.email)
    return user


# ── Verify email ──────────────────────────────────────────────────────────────

@router.post("/verify-email")
def verify_email(request: Request, payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    rate_limit.enforce("verify_email_ip", rate_limit.client_ip(request), 30, 600)
    user = db.query(User).filter_by(email=payload.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_email_verified:
        return {"message": "Email already verified"}
    otp_key = f"verify:{payload.email.lower()}"
    if (
        not _otp_matches(user.email_verification_code, payload.otp)
        or not user.email_verification_expires
        or datetime.utcnow() > user.email_verification_expires
    ):
        logger.warning("AUTH verify_email failed: invalid/expired OTP email=%s", payload.email)
        if rate_limit.otp_failed(otp_key, OTP_MAX_ATTEMPTS):
            user.email_verification_code = None
            user.email_verification_expires = None
            db.commit()
            raise HTTPException(
                status_code=429,
                detail="Too many incorrect attempts. Please request a new verification code.",
            )
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    rate_limit.otp_reset(otp_key)
    user.is_email_verified = True
    user.email_verification_code = None
    user.email_verification_expires = None
    db.commit()

    logger.info("AUTH email_verified: user_id=%d email=%s", user.id, user.email)
    return {"message": "Email verified successfully"}


# ── Resend verification ───────────────────────────────────────────────────────

@router.post("/resend-verification")
async def resend_verification(
    request: Request,
    payload: ResendVerificationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    rate_limit.enforce("resend_ip", rate_limit.client_ip(request), 20, 3600)
    user = db.query(User).filter_by(email=payload.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_email_verified:
        return {"message": "Email already verified"}
    rate_limit.enforce("resend_email", payload.email.lower(), 5, 3600)

    otp = _generate_otp()
    rate_limit.otp_reset(f"verify:{payload.email.lower()}")
    user.email_verification_code = otp
    user.email_verification_expires = datetime.utcnow() + timedelta(hours=OTP_VERIFY_EXPIRE_HOURS)
    db.commit()

    background_tasks.add_task(send_resend_verification_email, user.email, otp)

    logger.info("AUTH otp_sent: type=email_verification_resend user_id=%d email=%s", user.id, user.email)
    return {"message": "Verification code sent"}


# ── Me (profile) ──────────────────────────────────────────────────────────────

@router.get("/me")
def get_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "referral_code": current_user.referral_code,
        "wallet_address": current_user.wallet_address,
        "sponsor_id": current_user.sponsor_id,
        "sponsor_username": current_user.sponsor.username if current_user.sponsor else None,
        "is_email_verified": current_user.is_email_verified,
        "is_admin": current_user.is_admin,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


@router.get("/referrals")
def get_direct_referrals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Direct referrals = users who registered using this user's username as their
    sponsor (i.e. sponsor_id == current_user.id). Returns the count and a list.
    """
    referrals = (
        db.query(User)
        .filter(User.sponsor_id == current_user.id)
        .order_by(User.created_at.desc())
        .all()
    )
    return {
        "count": len(referrals),
        "referrals": [
            {
                "username": r.username,
                "is_active": r.is_active,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in referrals
        ],
    }


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(request: Request, payload: UserLogin, db: Session = Depends(get_db)):
    ip = rate_limit.client_ip(request)
    user_key = f"{ip}:{payload.username.strip().lower()}"
    # Check first, count only FAILURES — a legitimate user logging in repeatedly
    # is never throttled, a password-guesser is.
    rate_limit.enforce("login_ip", ip, 40, 900, record_hit=False)
    rate_limit.enforce("login_user", user_key, 8, 900, record_hit=False)
    user = get_user_by_username(db, payload.username)
    if not user or not verify_password(payload.password, user.password_hash):
        rate_limit.record("login_ip", ip)
        rate_limit.record("login_user", user_key)
        logger.warning("AUTH login_failed: invalid credentials username=%s", payload.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_email_verified:
        logger.warning("AUTH login_failed: email not verified user_id=%d email=%s", user.id, user.email)
        raise HTTPException(status_code=403, detail="Please verify your email before logging in")
    if not user.is_active:
        logger.warning("AUTH login_failed: account frozen user_id=%d username=%s", user.id, user.username)
        raise HTTPException(
            status_code=403,
            detail="Your account has been frozen by the administrator. Please contact support.",
        )
    logger.info("AUTH login: user_id=%d username=%s", user.id, user.username)
    return {"access_token": create_access_token(user.id)}


# ── Forgot password ───────────────────────────────────────────────────────────

@router.post("/forgot-password")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    ip = rate_limit.client_ip(request)
    # Enforced BEFORE the account lookup so it also throttles email enumeration.
    rate_limit.enforce("forgot_ip", ip, 15, 3600)
    user = db.query(User).filter_by(email=payload.email).first()
    if not user:
        logger.warning("AUTH forgot_password failed: email not registered email=%s", payload.email)
        raise HTTPException(status_code=404, detail="No account found with this email")
    # Few codes per mailbox: each new code resets the attempt allowance below.
    rate_limit.enforce("forgot_email", payload.email.lower(), 3, 3600)

    otp = _generate_otp()
    rate_limit.otp_reset(f"reset:{payload.email.lower()}")
    user.password_reset_code = otp
    user.password_reset_expires = datetime.utcnow() + timedelta(hours=OTP_RESET_EXPIRE_HOURS)
    db.commit()
    background_tasks.add_task(send_password_reset_email, user.email, otp)
    logger.info("AUTH otp_sent: type=password_reset user_id=%d email=%s", user.id, user.email)

    return {"message": "A reset code has been sent to your email"}


# ── Reset password ────────────────────────────────────────────────────────────

@router.post("/reset-password")
def reset_password(request: Request, payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    rate_limit.enforce("reset_ip", rate_limit.client_ip(request), 30, 600)
    user = db.query(User).filter_by(email=payload.email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid reset code")
    otp_key = f"reset:{payload.email.lower()}"
    if (
        not _otp_matches(user.password_reset_code, payload.otp)
        or not user.password_reset_expires
        or datetime.utcnow() > user.password_reset_expires
    ):
        logger.warning("AUTH reset_password failed: invalid/expired OTP email=%s", payload.email)
        if rate_limit.otp_failed(otp_key, OTP_MAX_ATTEMPTS):
            user.password_reset_code = None
            user.password_reset_expires = None
            db.commit()
            raise HTTPException(
                status_code=429,
                detail="Too many incorrect attempts. Please request a new reset code.",
            )
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")

    rate_limit.otp_reset(otp_key)
    user.password_hash = hash_password(payload.new_password)
    user.password_reset_code = None
    user.password_reset_expires = None
    db.commit()

    logger.info("AUTH password_reset: user_id=%d email=%s", user.id, user.email)
    return {"message": "Password reset successfully"}
