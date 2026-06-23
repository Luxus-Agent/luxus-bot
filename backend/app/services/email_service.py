# backend/app/services/email_service.py
"""
SMTP email service — OTP emails only: email verification, password reset, and
BEP-20 address verification. (Deposit/withdrawal/transfer/agent-activation emails
were removed with the deposit-first + NOWPayments rails.)
Runs blocking SMTP calls in a thread pool so the event loop is not blocked.

Config keys (set in .env):
    SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SENDER_EMAIL
"""

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)

_BRAND = "PresZ Platform"
_ACCENT = "#6C63FF"       # purple accent
_BG = "#f5f5f5"
_CARD_BG = "#ffffff"


# ── Core send ─────────────────────────────────────────────────────────────────

async def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an HTML email. Returns True on success, False on failure."""
    def _send():
        message = MIMEMultipart()
        message["Subject"] = subject
        message["From"]    = settings.SENDER_EMAIL
        message["To"]      = to_email
        message.attach(MIMEText(body, "html"))

        with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.sendmail(settings.SENDER_EMAIL, to_email, message.as_string())

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _send)
        logger.info("Email sent to %s — %s", to_email, subject)
        return True
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_email, exc)
        return False


def _card(content: str) -> str:
    """Wrap content in the standard card layout."""
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px; background-color: {_BG};">
        <div style="max-width: 600px; margin: 0 auto; background-color: {_CARD_BG};
                    padding: 30px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
            {content}
            <hr style="border: none; border-top: 1px solid #e5e7eb; margin-top: 30px;">
            <p style="color: #9ca3af; font-size: 12px; margin-top: 12px;">{_BRAND}</p>
        </div>
    </body>
    </html>
    """


# ── Email verification OTP ────────────────────────────────────────────────────

async def send_verification_email(email: str, otp: str) -> bool:
    subject = "Verify Your PresZ Account"
    body = _card(f"""
        <h2 style="color: #1a1a2e; margin-top: 0;">Email Verification</h2>
        <p>Welcome to <strong>{_BRAND}</strong>! Please verify your email address
           to activate your account.</p>
        <p>Your verification code is:</p>
        <p style="font-size: 36px; font-weight: bold; color: {_ACCENT};
                   letter-spacing: 10px; text-align: center; margin: 24px 0;">{otp}</p>
        <p>Enter this code on the verification page. It expires in <strong>24 hours</strong>.</p>
        <p style="color: #6b7280; font-size: 13px;">
            If you did not create a PresZ account, you can safely ignore this email.
        </p>
    """)
    return await send_email(email, subject, body)


async def send_resend_verification_email(email: str, otp: str) -> bool:
    subject = "New Verification Code — PresZ"
    body = _card(f"""
        <h2 style="color: #1a1a2e; margin-top: 0;">New Verification Code</h2>
        <p>Here is your new verification code:</p>
        <p style="font-size: 36px; font-weight: bold; color: {_ACCENT};
                   letter-spacing: 10px; text-align: center; margin: 24px 0;">{otp}</p>
        <p>It expires in <strong>24 hours</strong>.</p>
    """)
    return await send_email(email, subject, body)


# ── Password reset OTP ────────────────────────────────────────────────────────

async def send_password_reset_email(email: str, otp: str) -> bool:
    subject = "Reset Your PresZ Password"
    body = _card(f"""
        <h2 style="color: #1a1a2e; margin-top: 0;">Password Reset</h2>
        <p>We received a request to reset your password.</p>
        <p>Your reset code is:</p>
        <p style="font-size: 36px; font-weight: bold; color: {_ACCENT};
                   letter-spacing: 10px; text-align: center; margin: 24px 0;">{otp}</p>
        <p>Enter this code to set a new password. It expires in <strong>1 hour</strong>.</p>
        <p style="color: #6b7280; font-size: 13px;">
            If you did not request a password reset, you can safely ignore this email.
        </p>
    """)
    return await send_email(email, subject, body)


# ── BEP-20 address verification OTP ──────────────────────────────────────────

async def send_address_verification_email(
    email: str, otp: str, wallet_address: str
) -> bool:
    subject = "Verify BEP-20 Address — PresZ"
    body = _card(f"""
        <h2 style="color: #1a1a2e; margin-top: 0;">BEP-20 Address Verification</h2>
        <p>You are registering a new BEP-20 payout address:</p>
        <p style="font-family: monospace; background: #f9fafb; padding: 12px;
                   border-radius: 6px; word-break: break-all; margin: 16px 0;">
            {wallet_address}
        </p>
        <p>Your verification code is:</p>
        <p style="font-size: 36px; font-weight: bold; color: {_ACCENT};
                   letter-spacing: 10px; text-align: center; margin: 24px 0;">{otp}</p>
        <p>Use <code>POST /wallet/address/verify</code> with this code to confirm.
           It expires in <strong>30 minutes</strong>.</p>
        <p style="color: #ef4444; font-size: 13px; font-weight: bold;">
            ⚠ Only verify an address that belongs to you. On-chain payouts sent to a
            wrong address cannot be reversed.
        </p>
        <p style="color: #6b7280; font-size: 13px;">
            If you did not request this, please ignore this email.
        </p>
    """)
    return await send_email(email, subject, body)
