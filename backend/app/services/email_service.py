# backend/app/services/email_service.py
"""
SMTP email service — OTP verification, password reset, and platform event notifications.
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


def _send_sync(to_email: str, subject: str, body: str) -> bool:
    """Sync wrapper for use inside Celery tasks (which are not async)."""
    try:
        asyncio.run(send_email(to_email, subject, body))
        return True
    except Exception as exc:
        logger.error("Sync email send failed to %s: %s", to_email, exc)
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


# ── Agent activated ───────────────────────────────────────────────────────────

def send_agent_activated_email(email: str, username: str, agent_tier: int, price: float) -> bool:
    subject = f"Agent {agent_tier} Activated — PresZ"
    tier_label = f"Agent {agent_tier} (${price:.0f})"
    body = _card(f"""
        <h2 style="color: #1a1a2e; margin-top: 0;">Your Agent is Active!</h2>
        <p>Hi <strong>{username}</strong>,</p>
        <p>Your payment was confirmed and <strong>{tier_label}</strong> is now active.</p>
        <div style="background-color: #f0fdf4; border-left: 4px solid #10B981;
                    padding: 16px; margin: 24px 0; border-radius: 4px;">
            <p style="margin: 0; color: #065f46; font-weight: bold;">Revenue engine running</p>
            <p style="margin: 8px 0 0; color: #065f46;">
                60% → ProActive &nbsp;|&nbsp; 30% → Proportion matrix &nbsp;|&nbsp; 10% → Speculation matrix
            </p>
        </div>
        <p>Log in to your dashboard to track your matrix position, wallet balance,
           and incoming payouts.</p>
    """)
    return _send_sync(email, subject, body)


# ── Transfer verification OTP ─────────────────────────────────────────────────

async def send_transfer_verification_email(
    email: str, otp: str, recipient_username: str, amount: float
) -> bool:
    subject = "Confirm Your Transfer — PresZ"
    body = _card(f"""
        <h2 style="color: #1a1a2e; margin-top: 0;">Transfer Verification</h2>
        <p>You are about to transfer funds to <strong>@{recipient_username}</strong>
           for the first time.</p>
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <tr>
                <td style="padding: 10px; background: #f9fafb; border-radius: 4px;
                            color: #6b7280; font-size: 13px; width: 40%;">Recipient</td>
                <td style="padding: 10px; font-weight: bold;">@{recipient_username}</td>
            </tr>
            <tr>
                <td style="padding: 10px; color: #6b7280; font-size: 13px;">Amount</td>
                <td style="padding: 10px; font-weight: bold;">${amount:.2f}</td>
            </tr>
        </table>
        <p>Your one-time verification code is:</p>
        <p style="font-size: 36px; font-weight: bold; color: {_ACCENT};
                   letter-spacing: 10px; text-align: center; margin: 24px 0;">{otp}</p>
        <p>Use <code>POST /deposit/transfer/verify</code> with this code to confirm.
           It expires in <strong>30 minutes</strong>.</p>
        <p>After this, transfers to @{recipient_username} will not require verification.</p>
        <p style="color: #6b7280; font-size: 13px;">
            If you did not initiate this transfer, please contact support immediately.
        </p>
    """)
    return await send_email(email, subject, body)


# ── Withdrawal address verification OTP ──────────────────────────────────────

async def send_address_verification_email(
    email: str, otp: str, wallet_address: str
) -> bool:
    subject = "Verify Withdrawal Address — PresZ"
    short_address = f"{wallet_address[:6]}…{wallet_address[-4:]}"
    body = _card(f"""
        <h2 style="color: #1a1a2e; margin-top: 0;">Withdrawal Address Verification</h2>
        <p>You are registering a new BEP-20 withdrawal address:</p>
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
            ⚠ Only verify an address that belongs to you. Withdrawals sent to a wrong address
            cannot be reversed.
        </p>
        <p style="color: #6b7280; font-size: 13px;">
            If you did not request this, please ignore this email.
        </p>
    """)
    return await send_email(email, subject, body)


# ── Withdrawal requested ──────────────────────────────────────────────────────

async def send_withdrawal_requested_email(
    email: str, username: str, amount: float, wallet_address: str, scheduled_for: str
) -> bool:
    subject = "Withdrawal Requested — PresZ"
    short_address = f"{wallet_address[:6]}…{wallet_address[-4:]}"
    body = _card(f"""
        <h2 style="color: #1a1a2e; margin-top: 0;">Withdrawal Scheduled</h2>
        <p>Hi <strong>{username}</strong>,</p>
        <p>Your withdrawal request has been received and funds have been reserved.</p>
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <tr>
                <td style="padding: 10px; background: #f9fafb; border-radius: 4px;
                            color: #6b7280; font-size: 13px; width: 40%;">Amount</td>
                <td style="padding: 10px; font-weight: bold;">${amount:.4f} USDT</td>
            </tr>
            <tr>
                <td style="padding: 10px; color: #6b7280; font-size: 13px;">Network</td>
                <td style="padding: 10px;">BEP-20 (BNB Smart Chain)</td>
            </tr>
            <tr>
                <td style="padding: 10px; background: #f9fafb; border-radius: 4px;
                            color: #6b7280; font-size: 13px;">To Address</td>
                <td style="padding: 10px; font-family: monospace;">{short_address}</td>
            </tr>
            <tr>
                <td style="padding: 10px; color: #6b7280; font-size: 13px;">Scheduled For</td>
                <td style="padding: 10px; font-weight: bold;">{scheduled_for} UTC</td>
            </tr>
        </table>
        <p style="color: #6b7280; font-size: 13px;">
            Your payout is being processed now and will be dispatched automatically to your BEP-20 address.
        </p>
    """)
    return await send_email(email, subject, body)


# ── Withdrawal sent ───────────────────────────────────────────────────────────

def send_withdrawal_sent_email(
    email: str, username: str, amount: float, wallet_address: str, payout_id: str
) -> bool:
    subject = "Withdrawal Sent — PresZ"
    short_address = f"{wallet_address[:6]}…{wallet_address[-4:]}"
    body = _card(f"""
        <h2 style="color: #1a1a2e; margin-top: 0;">Withdrawal Dispatched</h2>
        <p>Hi <strong>{username}</strong>,</p>
        <p>Your USDT withdrawal has been sent successfully.</p>
        <div style="background-color: #f0fdf4; border-left: 4px solid #10B981;
                    padding: 16px; margin: 24px 0; border-radius: 4px;">
            <p style="margin: 0; color: #065f46; font-weight: bold;">
                ${amount:.4f} USDT dispatched on BEP-20
            </p>
            <p style="margin: 8px 0 0; color: #065f46;">To: {short_address}</p>
        </div>
        <p style="color: #6b7280; font-size: 13px;">
            NOWPayments reference: <code>{payout_id}</code><br>
            Funds typically arrive within a few minutes. Check your BEP-20 wallet.
        </p>
    """)
    return _send_sync(email, subject, body)


# ── Withdrawal failed ─────────────────────────────────────────────────────────

def send_withdrawal_failed_email(
    email: str, username: str, amount: float, reason: str
) -> bool:
    subject = "Withdrawal Failed — Funds Refunded — PresZ"
    body = _card(f"""
        <h2 style="color: #1a1a2e; margin-top: 0;">Withdrawal Failed</h2>
        <p>Hi <strong>{username}</strong>,</p>
        <p>Unfortunately your withdrawal of <strong>${amount:.4f} USDT</strong> could not
           be processed.</p>
        <div style="background-color: #fef2f2; border-left: 4px solid #ef4444;
                    padding: 16px; margin: 24px 0; border-radius: 4px;">
            <p style="margin: 0; color: #991b1b; font-weight: bold;">Reason</p>
            <p style="margin: 8px 0 0; color: #991b1b;">{reason}</p>
        </div>
        <p>The full amount of <strong>${amount:.4f} USDT</strong> has been
           <strong>refunded to your wallet</strong> and is available to withdraw again.</p>
        <p style="color: #6b7280; font-size: 13px;">
            If this keeps happening please contact support.
        </p>
    """)
    return _send_sync(email, subject, body)
