# backend/app/services/nowpayments.py
"""
NOWPayments service — PresZ deposits and agent tier purchases.

Payments are in USDT on BEP-20 only.

Environment:
  APP_ENV=development  → sandbox API  (api-sandbox.nowpayments.io)
  APP_ENV=production   → live API     (api.nowpayments.io)

IPN flow (deposits):
  NOWPayments POSTs to   POST /webhooks/nowpayments/ipn
  Signature header:      x-nowpayments-sig  (HMAC-SHA512 of raw body)
  Success status:        "finished"

Payout IPN flow (withdrawals):
  NOWPayments POSTs to   POST /webhooks/nowpayments/payout-ipn
  Signature header:      x-nowpayments-sig
  Terminal statuses:     "FINISHED" (confirmed on-chain), "FAILED"

Order ID formats:
  presz_deposit_{deposit_id}_{unix_ts}   — account balance top-up
  presz_agent_{purchase_id}_{unix_ts}    — legacy direct agent purchase (IPN compat only)
"""

import hmac
import hashlib
import logging
import httpx
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

NOWPAYMENTS_LIVE_BASE    = "https://api.nowpayments.io/v1"
NOWPAYMENTS_SANDBOX_BASE = "https://api-sandbox.nowpayments.io/v1"

USDT_NETWORKS: dict[str, dict[str, str]] = {
    "usdtbsc": {
        "label":   "USDT (BEP-20 / BNB Smart Chain)",
        "network": "BEP-20",
        "note":    "~$0.50 fee",
        "icon":    "bnb",
    },
}

SUCCESSFUL_STATUSES = {"finished"}
FAILED_STATUSES     = {"failed", "refunded", "expired"}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _base_url() -> str:
    return (
        NOWPAYMENTS_LIVE_BASE
        if settings.APP_ENV == "production"
        else NOWPAYMENTS_SANDBOX_BASE
    )


def _headers() -> dict[str, str]:
    return {
        "x-api-key":    settings.NOWPAYMENTS_API_KEY,
        "Content-Type": "application/json",
    }


def _order_id(purchase_id: int) -> str:
    return f"presz_agent_{purchase_id}_{int(datetime.utcnow().timestamp())}"


def _deposit_order_id(deposit_id: int) -> str:
    return f"presz_deposit_{deposit_id}_{int(datetime.utcnow().timestamp())}"


def _parse_purchase_id(order_id: str) -> int | None:
    """Extract purchase_id from agent order_id string."""
    try:
        parts = order_id.split("_")  # ['presz', 'agent', '{purchase_id}', '{ts}']
        return int(parts[2])
    except (IndexError, ValueError):
        return None


def _parse_deposit_id(order_id: str) -> int | None:
    """Extract deposit_id from deposit order_id string."""
    try:
        parts = order_id.split("_")  # ['presz', 'deposit', '{deposit_id}', '{ts}']
        return int(parts[2])
    except (IndexError, ValueError):
        return None


# ── Public helpers ────────────────────────────────────────────────────────────

def get_usdt_networks() -> list:
    return [{"currency_code": code, **info} for code, info in USDT_NETWORKS.items()]


async def check_api_status() -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{_base_url()}/status")
        return r.json().get("message") == "OK"
    except Exception as exc:
        logger.error("NOWPayments status check failed: %s", exc)
        return False


# ── Invoice creation ──────────────────────────────────────────────────────────

async def _create_invoice(
    amount_usd:   float,
    order_id:     str,
    description:  str,
    usdt_network: str | None,
) -> dict[str, Any]:
    if usdt_network and usdt_network not in USDT_NETWORKS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported network '{usdt_network}'. Available: {list(USDT_NETWORKS.keys())}",
        )

    callback_base = settings.NOWPAYMENTS_CALLBACK_BASE.rstrip("/")
    # Price and pay in the same currency (usdtbsc) to avoid any conversion.
    # NOWPayments cannot estimate cross-network USDT pairs (e.g. usdt→usdtbsc),
    # and sandbox USD→USDT rates are unreliable test values.
    pay_currency = usdt_network or "usdtbsc"
    payload: dict[str, Any] = {
        "price_amount":        amount_usd,
        "price_currency":      pay_currency,  # same as pay_currency → 1:1, no conversion
        "pay_currency":        pay_currency,
        "order_id":            order_id,
        "order_description":   description,
        "ipn_callback_url":    f"{callback_base}/webhooks/nowpayments/ipn",
        "success_url":         f"{settings.FRONTEND_URL}/deposit?payment=success&order_id={order_id}",
        "cancel_url":          f"{settings.FRONTEND_URL}/deposit?payment=cancelled",
        "is_fixed_rate":       True,
        "is_fee_paid_by_user": True,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{_base_url()}/invoice",
                headers=_headers(),
                json=payload,
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as exc:
        logger.error("NOWPayments invoice creation failed: %s", exc.response.text)
        raise HTTPException(status_code=502, detail="Failed to create payment invoice.")


async def create_deposit_invoice(
    db:         Session,
    deposit_id: int,
    amount_usd: float,
) -> dict[str, Any]:
    """
    Create a NOWPayments invoice for an account balance deposit.
    Stores the generated order_id in Deposit.order_id.
    """
    from app.models.deposit import Deposit

    deposit = db.query(Deposit).filter_by(id=deposit_id).with_for_update().first()
    if not deposit:
        raise HTTPException(status_code=404, detail="Deposit not found.")
    if deposit.status != "pending":
        raise HTTPException(status_code=400, detail="Deposit already processed.")

    oid = _deposit_order_id(deposit_id)

    invoice_data = await _create_invoice(
        amount_usd=amount_usd,
        order_id=oid,
        description=f"PresZ Account Deposit — ${amount_usd:.2f} USDT",
        usdt_network="usdtbsc",
    )

    deposit.order_id = oid
    db.commit()

    logger.info(
        "Deposit invoice created — deposit_id=%d amount=$%.2f order_id=%s",
        deposit_id, amount_usd, oid,
    )

    return {
        "invoice_url":   invoice_data.get("invoice_url"),
        "order_id":      oid,
        "amount_usd":    amount_usd,
        "network_label": USDT_NETWORKS["usdtbsc"]["label"],
        "provider":      "nowpayments",
    }


# ── IPN signature verification ────────────────────────────────────────────────

def verify_ipn_signature(raw_body: bytes, received_sig: str) -> bool:
    """
    Verify the NOWPayments IPN signature.
    NOWPayments signs the RAW body bytes — do NOT sort or re-encode the JSON.
    """
    try:
        expected = hmac.new(
            key=settings.NOWPAYMENTS_IPN_SECRET.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha512,
        ).hexdigest()

        result = hmac.compare_digest(expected, received_sig)
        if not result:
            logger.error(
                "[IPN] HMAC mismatch — expected=%s... received=%s...",
                expected[:20], received_sig[:20],
            )
        return result
    except Exception as exc:
        logger.error("[IPN] Signature verification error: %s", exc)
        return False


# ── IPN event processing ──────────────────────────────────────────────────────

def process_ipn_event(
    db:      Session,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Process a NOWPayments payment IPN.

    Uses WebhookEvent with a unique constraint on event_id to guard against
    duplicate IPNs and race conditions — the DB insert fails fast if we've
    already processed this (payment_id, status) pair.
    """
    from app.models.webhook_event import WebhookEvent

    payment_id     = str(payload.get("payment_id", ""))
    payment_status = payload.get("payment_status", "")
    order_id       = payload.get("order_id", "")
    price_amount   = float(payload.get("price_amount", 0))
    actually_paid  = float(payload.get("actually_paid", 0))

    logger.info(
        "[IPN] payment_id=%s status=%s order_id=%s expected=$%.2f received=$%.2f",
        payment_id, payment_status, order_id, price_amount, actually_paid,
    )

    # Skip intermediate statuses — no DB writes needed
    if payment_status not in SUCCESSFUL_STATUSES and payment_status not in FAILED_STATUSES:
        logger.info("[IPN] Intermediate status '%s' — no action", payment_status)
        return {"action": "none", "status": payment_status}

    # Idempotency: insert a WebhookEvent record with unique event_id.
    # If a duplicate IPN arrives, the IntegrityError fires here — before any
    # business logic — so we can never double-credit a deposit.
    event_id = f"nowpayments:{payment_id}:{payment_status}"
    event = WebhookEvent(
        event_id=event_id,
        event_type=f"nowpayments.{payment_status}",
        order_id=order_id,
        payload=payload,
        processing_status="pending",
    )
    db.add(event)
    try:
        db.flush()  # triggers the unique constraint check immediately
    except IntegrityError:
        db.rollback()
        logger.info("[IPN] Duplicate event_id=%s — skipping", event_id)
        return {"action": "duplicate", "event_id": event_id}

    # Route to the correct handler
    try:
        if payment_status in FAILED_STATUSES:
            _handle_failed_payment(db, order_id, payment_id, payment_status)
            result = {"action": "failed", "status": payment_status}
        elif order_id.startswith("presz_deposit_"):
            result = _complete_deposit(db, order_id, payment_id)
        elif order_id.startswith("presz_agent_"):
            result = _activate_agent_purchase(db, order_id, payment_id)
        else:
            logger.warning("[IPN] Unknown order_id prefix: %s", order_id)
            result = {"action": "unknown_order_type", "order_id": order_id}

        event.processing_status = "success"
        db.commit()
        return result

    except Exception as exc:
        event.processing_status = "failed"
        event.error_message = str(exc)[:500]
        db.commit()
        logger.exception("[IPN] Processing error for event_id=%s: %s", event_id, exc)
        raise


def _complete_deposit(
    db:         Session,
    order_id:   str,
    payment_id: str,
) -> dict[str, Any]:
    """Find the Deposit by order_id, credit the user's account balance."""
    from app.models.deposit import Deposit
    from app.core.wallet_ops import credit_account
    from app.models.transaction import TransactionType
    from decimal import Decimal

    deposit = db.query(Deposit).filter_by(order_id=order_id).first()

    if not deposit:
        logger.error("[IPN] Deposit not found for order_id=%s", order_id)
        return {"action": "error", "message": "Deposit order not found"}

    if deposit.status == "completed":
        logger.info("[IPN] Deposit already completed: %s", order_id)
        return {"action": "already_processed"}

    credit_account(
        db=db,
        user_id=deposit.user_id,
        amount=Decimal(str(deposit.amount_usd)),
        tx_type=TransactionType.DEPOSIT,
        reference_id=f"deposit_{deposit.id}",
        notes=f"Account deposit via NOWPayments — order {order_id}",
    )

    deposit.status = "completed"
    deposit.completed_at = datetime.utcnow()

    logger.info(
        "[IPN] Deposit completed — deposit_id=%d user_id=%d amount=$%.2f",
        deposit.id, deposit.user_id, deposit.amount_usd,
    )
    return {"action": "deposit_completed", "deposit_id": deposit.id}


def _activate_agent_purchase(
    db:         Session,
    order_id:   str,
    payment_id: str,
) -> dict[str, Any]:
    """Find the AgentPurchase by order_id and trigger the revenue engine via Celery."""
    from app.models.agent import AgentPurchase
    from app.workers.tasks import activate_purchase

    purchase = db.query(AgentPurchase).filter_by(payment_id=order_id).first()

    if not purchase:
        logger.error("[IPN] AgentPurchase not found for order_id=%s", order_id)
        return {"action": "error", "message": "Order not found"}

    if purchase.status == "active":
        logger.info("[IPN] Already activated: %s", order_id)
        return {"action": "already_processed"}

    logger.info(
        "[IPN] Payment confirmed — queuing activation for purchase_id=%d user_id=%d tier=%d",
        purchase.id, purchase.user_id, purchase.agent_tier,
    )

    activate_purchase.delay(purchase.id)

    return {"action": "activation_queued", "purchase_id": purchase.id}


def _handle_failed_payment(
    db:         Session,
    order_id:   str,
    payment_id: str,
    status_str: str,
) -> None:
    if order_id.startswith("presz_deposit_"):
        from app.models.deposit import Deposit
        deposit = db.query(Deposit).filter_by(order_id=order_id).first()
        if deposit and deposit.status == "pending":
            deposit.status = "failed"
            logger.warning("[IPN] Deposit %s → %s", order_id, status_str)
        return

    from app.models.agent import AgentPurchase
    purchase = db.query(AgentPurchase).filter_by(payment_id=order_id).first()
    if purchase and purchase.status == "pending":
        purchase.status = "failed"
        logger.warning("[IPN] AgentPurchase %s → %s", order_id, status_str)


# ── Payout IPN processing ─────────────────────────────────────────────────────

def process_payout_ipn_event(
    db:      Session,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Process a NOWPayments payout IPN (withdrawal status update).

    NOWPayments fires this when a payout transitions to a terminal state:
      FINISHED — transaction confirmed on-chain
      FAILED   — payout failed; we refund the balance to the user's MAIN wallet
    """
    from app.models.webhook_event import WebhookEvent
    from app.models.withdrawal import WithdrawalRequest, WithdrawalStatus

    payout_id = str(payload.get("id", ""))
    status    = str(payload.get("status", "")).upper()

    logger.info("[PayoutIPN] payout_id=%s status=%s", payout_id, status)

    if not payout_id:
        return {"action": "error", "message": "Missing payout id"}

    # Idempotency guard
    event_id = f"nowpayments_payout:{payout_id}:{status}"
    event = WebhookEvent(
        event_id=event_id,
        event_type=f"nowpayments.payout.{status.lower()}",
        order_id=None,
        payload=payload,
        processing_status="pending",
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.info("[PayoutIPN] Duplicate event_id=%s — skipping", event_id)
        return {"action": "duplicate", "event_id": event_id}

    if status not in ("FINISHED", "FAILED"):
        # Intermediate status (WAITING, PROCESSING, SENT, etc.) — log only
        event.processing_status = "success"
        db.commit()
        return {"action": "none", "status": status}

    withdrawal = (
        db.query(WithdrawalRequest)
        .filter_by(nowpayments_payout_id=payout_id)
        .first()
    )
    if not withdrawal:
        logger.warning("[PayoutIPN] No withdrawal found for payout_id=%s", payout_id)
        event.processing_status = "success"
        db.commit()
        return {"action": "not_found", "payout_id": payout_id}

    if status == "FINISHED":
        # Payout confirmed on-chain — status is already SENT, nothing more to do
        logger.info(
            "[PayoutIPN] Withdrawal %d confirmed on-chain (payout_id=%s)",
            withdrawal.id, payout_id,
        )
        event.processing_status = "success"
        db.commit()
        return {"action": "withdrawal_confirmed", "withdrawal_id": withdrawal.id}

    # status == "FAILED"
    if withdrawal.status == WithdrawalStatus.FAILED:
        # Already handled (tasks.py caught a sync failure earlier)
        event.processing_status = "success"
        db.commit()
        return {"action": "already_failed", "withdrawal_id": withdrawal.id}

    logger.warning(
        "[PayoutIPN] Payout FAILED for withdrawal_id=%d — refunding balance",
        withdrawal.id,
    )

    from decimal import Decimal
    from app.core.wallet_ops import credit_main_wallet_direct
    from app.models.transaction import TransactionType

    withdrawal.status         = WithdrawalStatus.FAILED
    withdrawal.failure_reason = f"NOWPayments payout IPN: FAILED (payout_id={payout_id})"
    withdrawal.processed_at   = datetime.utcnow()

    credit_main_wallet_direct(
        db=db,
        user_id=withdrawal.user_id,
        agent_tier=withdrawal.agent_tier,
        amount=Decimal(str(withdrawal.amount)),
        tx_type=TransactionType.TRANSFER_IN,
        reference_id=f"withdrawal_{withdrawal.id}_payout_failed_refund",
        notes=f"Payout failed on-chain — balance restored (payout_id={payout_id})",
    )

    event.processing_status = "success"
    db.commit()

    logger.info(
        "[PayoutIPN] Refunded $%.4f to user_id=%d for failed withdrawal_id=%d",
        float(withdrawal.amount), withdrawal.user_id, withdrawal.id,
    )
    return {"action": "withdrawal_refunded", "withdrawal_id": withdrawal.id}


# ── Payouts (withdrawals) ─────────────────────────────────────────────────────

async def send_payout(
    withdrawal_id: int,
    amount_usd:    float,
    wallet_address: str,
) -> dict[str, Any]:
    """
    Call the NOWPayments Payouts API to send USDT (BEP-20) to the given address.
    Returns the full API response dict on success.
    Raises HTTPException on failure.
    """
    callback_base = settings.NOWPAYMENTS_CALLBACK_BASE.rstrip("/")

    payload: dict[str, Any] = {
        "address":            wallet_address,
        "currency":           "usdtbsc",
        "amount":             str(round(amount_usd, 4)),
        "ipn_callback_url":   f"{callback_base}/webhooks/nowpayments/payout-ipn",
        "payout_description": f"PresZ withdrawal #{withdrawal_id}",
        "extra_id":           None,
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{_base_url()}/payout",
                headers=_headers(),
                json=payload,
            )
            r.raise_for_status()
            data = r.json()

        logger.info(
            "[Payout] withdrawal_id=%d amount=$%.4f address=%s payout_id=%s",
            withdrawal_id, amount_usd, wallet_address, data.get("id"),
        )
        return data

    except httpx.HTTPStatusError as exc:
        logger.error(
            "[Payout] NOWPayments error for withdrawal_id=%d: %s",
            withdrawal_id, exc.response.text,
        )
        raise HTTPException(status_code=502, detail="Payout failed via NOWPayments.")
