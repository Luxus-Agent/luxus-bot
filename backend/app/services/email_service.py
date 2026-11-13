# backend/app/services/email_service.py
"""
SMTP email service — OTP emails (email verification, password reset, BEP-20
address verification) plus one operational alert: low platform-wallet gas
(see core/gas_alerts.py). (Deposit/withdrawal/transfer/agent-activation emails
were removed with the deposit-first + NOWPayments rails.)
Runs blocking SMTP calls in a thread pool so the event loop is not blocked.

Config keys (set in .env):
    SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SENDER_EMAIL
"""

import asyncio
import logging
import os
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)

_BRAND = "Luxus"
_ACCENT = "#12B278"       # brand green (matches the logo mark; readable on the white card)
_BG = "#f5f5f5"
_CARD_BG = "#ffffff"

# Inline (CID) logo images, referenced by every template via _card()'s header.
# Kept as backend-local copies (not imported from frontend/src/assets) so the
# email service doesn't depend on the frontend's directory layout.
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "email")
_LOGO_MARK_PATH = os.path.join(_ASSETS_DIR, "logo.png")
_LOGO_WORDMARK_PATH = os.path.join(_ASSETS_DIR, "logo-wordmark.png")  # dark text, for a light/white background


def _attach_inline_image(message: MIMEMultipart, path: str, content_id: str) -> None:
    """Attach `path` as an inline image referenced in HTML via `cid:{content_id}`."""
    try:
        with open(path, "rb") as f:
            image = MIMEImage(f.read())
    except OSError:
        logger.warning("Email logo asset not found, sending without it: %s", path)
        return
    image.add_header("Content-ID", f"<{content_id}>")
    image.add_header("Content-Disposition", "inline", filename=os.path.basename(path))
    message.attach(image)


# ── Core send ─────────────────────────────────────────────────────────────────

async def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an HTML email (with the inline Luxus logo). Returns True on success, False on failure."""
    def _send():
        # "related" (not "mixed") — the HTML part refers to the logo parts below
        # via cid: URIs, which mail clients only resolve inside a related group.
        message = MIMEMultipart("related")
        message["Subject"] = subject
        message["From"]    = settings.SENDER_EMAIL
        message["To"]      = to_email
        message.attach(MIMEText(body, "html"))
        _attach_inline_image(message, _LOGO_MARK_PATH, "logo_mark")
        _attach_inline_image(message, _LOGO_WORDMARK_PATH, "logo_wordmark")

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
    """Wrap content in the standard card layout, with the Luxus logo at the top."""
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px; background-color: {_BG};">
        <div style="max-width: 600px; margin: 0 auto; background-color: {_CARD_BG};
                    padding: 30px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
            <div style="text-align: center; margin-bottom: 24px;">
                <img src="cid:logo_mark" alt="" height="32" style="height: 32px; width: auto; vertical-align: middle;">
                <img src="cid:logo_wordmark" alt="{_BRAND}" height="20" style="height: 20px; width: auto; vertical-align: middle; margin-left: 8px;">
            </div>
            {content}
            <hr style="border: none; border-top: 1px solid #e5e7eb; margin-top: 30px;">
            <p style="color: #9ca3af; font-size: 12px; margin-top: 12px;">{_BRAND}</p>
        </div>
    </body>
    </html>
    """


# ── Email verification OTP ────────────────────────────────────────────────────

async def send_verification_email(email: str, otp: str) -> bool:
    subject = "Verify Your Luxus Account"
    body = _card(f"""
        <h2 style="color: #1a1a2e; margin-top: 0;">Email Verification</h2>
        <p>Welcome to <strong>{_BRAND}</strong>! Please verify your email address
           to activate your account.</p>
        <p>Your verification code is:</p>
        <p style="font-size: 36px; font-weight: bold; color: {_ACCENT};
                   letter-spacing: 10px; text-align: center; margin: 24px 0;">{otp}</p>
        <p>Enter this code on the verification page. It expires in <strong>24 hours</strong>.</p>
        <p style="color: #6b7280; font-size: 13px;">
            If you did not create a Luxus account, you can safely ignore this email.
        </p>
    """)
    return await send_email(email, subject, body)


async def send_resend_verification_email(email: str, otp: str) -> bool:
    subject = "New Verification Code — Luxus"
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
    subject = "Reset Your Luxus Password"
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
    subject = "Verify BEP-20 Address — Luxus"
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


# ── Low platform-wallet gas alert ────────────────────────────────────────────

async def send_low_gas_alert_email(
    email: str,
    wallet_label: str,
    wallet_address: str,
    bnb_balance,
    recommended_topup_bnb=None,
) -> bool:
    """One wallet's low-gas alert — see core/gas_alerts.py for when this fires.

    `recommended_topup_bnb` is computed from the live network gas price at
    alert time (core/onchain.get_recommended_gas_topup_bnb) — omitted from the
    email (falls back to a generic line) only if that RPC read itself failed.
    """
    subject = f"Low Gas Alert — {wallet_label}"
    topup_line = (
        f"""<p>Recommended top-up: at least
               <strong style="color: #16a34a;">{recommended_topup_bnb} BNB</strong> —
               enough to comfortably outlast the current network gas price.</p>"""
        if recommended_topup_bnb is not None
        else """<p style="color: #6b7280; font-size: 13px;">
               (Couldn't fetch a live gas price to size a recommendation — any
               top-up well above the balance below will do.)</p>"""
    )
    body = _card(f"""
        <h2 style="color: #1a1a2e; margin-top: 0;">Low Gas — {wallet_label}</h2>
        <p>The <strong>{wallet_label}</strong> is running low on BNB gas and may soon
           fail to broadcast its on-chain transactions.</p>
        <p style="font-family: monospace; background: #f9fafb; padding: 12px;
                   border-radius: 6px; word-break: break-all; margin: 16px 0;">
            {wallet_address}
        </p>
        <p>Current balance:
           <strong style="color: #ef4444;">{bnb_balance} BNB</strong></p>
        {topup_line}
        <p style="color: #6b7280; font-size: 13px;">
            Top up this wallet with BNB directly — there is no automated top-up.
            You'll receive another alert only after this wallet's balance recovers
            above the threshold and later drops again.
        </p>
    """)
    return await send_email(email, subject, body)
