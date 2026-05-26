# backend/app/services/nowpayments.py
"""
NOWPayments service — PresZ deposits and agent tier purchases.

Adapted from the CEX Arbitrage project's nowpayments.py.
Payments are in USDT on BEP-20.

Environment:
  APP_ENV=development  → sandbox API  (api-sandbox.nowpayments.io)
  APP_ENV=production   → live API     (api.nowpayments.io)

IPN flow:
  NOWPayments POSTs to   POST /webhooks/nowpayments/ipn
  Signature header:      x-nowpayments-sig  (HMAC-SHA512 of raw body)
  Success status:        "finished"

Order ID formats:
  presz_deposit_{deposit_id}_{unix_ts}   — account balance top-up
  presz_agent_{purchase_id}_{unix_ts}    — legacy direct agent purchase (kept for IPN compat)
"""

import hmac
import hashlib
import logging
import httpx
from datetime import datetime
from typing import Any

from fastapi import HTTPException
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
    payload: dict[str, Any] = {
        "price_amount":        amount_usd,
        "price_currency":      "usdt",   # USDT is 1:1 — no conversion, user pays exactly what they entered
        "order_id":            order_id,
        "order_description":   description,
        "ipn_callback_url":    f"{callback_base}/webhooks/nowpayments/ipn",
        "success_url":         f"{settings.FRONTEND_URL}/deposit?payment=success&order_id={order_id}",
        "cancel_url":          f"{settings.FRONTEND_URL}/deposit?payment=cancelled",
        "is_fixed_rate":       True,
        "is_fee_paid_by_user": True,    # user pays the small network fee on top; amount received = exactly price_amount
    }

    if usdt_network:
        payload["pay_currency"] = usdt_network

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


async def create_agent_invoice(
    db:           Session,
    purchase_id:  int,
    amount_usd:   float,
    agent_tier:   int,
    usdt_network: str | None = None,
) -> dict[str, Any]:
    """
    Create a NOWPayments invoice for an agent tier purchase.
    Stores the generated order_id in AgentPurchase.payment_id.
    """
    from app.models.agent import AgentPurchase

    purchase = db.query(AgentPurchase).filter_by(id=purchase_id).with_for_update().first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Purchase not found.")
    if purchase.status != "pending":
        raise HTTPException(status_code=400, detail="Purchase already processed.")

    oid = _order_id(purchase_id)

    invoice_data = await _create_invoice(
        amount_usd=amount_usd,
        order_id=oid,
        description=f"PresZ Agent {agent_tier} — ${amount_usd:.0f} USDT",
        usdt_network=usdt_network,
    )

    # Store the order_id so we can match it when the IPN arrives
    purchase.payment_id = oid
    db.commit()

    network_label = USDT_NETWORKS[usdt_network]["label"] if usdt_network else "User selects at checkout"

    logger.info(
        "Agent invoice created — purchase_id=%d tier=%d amount=$%.2f order_id=%s",
        purchase_id, agent_tier, amount_usd, oid,
    )

    return {
        "invoice_url":   invoice_data.get("invoice_url"),
        "order_id":      oid,
        "amount_usd":    amount_usd,
        "network_label": network_label,
        "provider":      "nowpayments",
    }


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
        "invoice_url":  invoice_data.get("invoice_url"),
        "order_id":     oid,
        "amount_usd":   amount_usd,
        "network_label": USDT_NETWORKS["usdtbsc"]["label"],
        "provider":     "nowpayments",
    }


# ── IPN signature verification ────────────────────────────────────────────────

def verify_ipn_signature(raw_body: bytes, received_sig: str) -> bool:
    """
    Verify the NOWPayments IPN signature.
    Signs the RAW body bytes with HMAC-SHA512 using IPN_SECRET.
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
    payment_id     = str(payload.get("payment_id", ""))
    payment_status = payload.get("payment_status", "")
    order_id       = payload.get("order_id", "")
    price_amount   = float(payload.get("price_amount", 0))
    actually_paid  = float(payload.get("actually_paid", 0))

    logger.info(
        "[IPN] payment_id=%s status=%s order_id=%s expected=$%.2f received=$%.2f",
        payment_id, payment_status, order_id, price_amount, actually_paid,
    )

    if payment_status not in SUCCESSFUL_STATUSES and payment_status not in FAILED_STATUSES:
        logger.info("[IPN] Intermediate status '%s' — no action", payment_status)
        return {"action": "none", "status": payment_status}

    if payment_status in FAILED_STATUSES:
        _handle_failed_payment(db, order_id, payment_id, payment_status)
        return {"action": "failed", "status": payment_status}

    if order_id.startswith("presz_deposit_"):
        return _complete_deposit(db, order_id, payment_id)

    if order_id.startswith("presz_agent_"):
        return _activate_agent_purchase(db, order_id, payment_id)

    logger.warning("[IPN] Unknown order_id prefix: %s", order_id)
    return {"action": "unknown_order_type", "order_id": order_id}


def _complete_deposit(
    db:         Session,
    order_id:   str,
    payment_id: str,
) -> dict[str, Any]:
    """Find the Deposit by order_id, credit the user's account balance."""
    from app.models.deposit import Deposit
    from app.core.wallet_ops import credit_account
    from app.models.transaction import TransactionType
    from datetime import datetime
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
    db.commit()

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

    # Hand off to Celery — the revenue engine runs asynchronously
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
            db.commit()
            logger.warning("[IPN] Deposit %s → %s", order_id, status_str)
        return

    from app.models.agent import AgentPurchase
    purchase = db.query(AgentPurchase).filter_by(payment_id=order_id).first()
    if purchase and purchase.status == "pending":
        purchase.status = "failed"
        db.commit()
        logger.warning("[IPN] AgentPurchase %s → %s", order_id, status_str)


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
        "address":           wallet_address,
        "currency":          "usdtbsc",
        "amount":            str(round(amount_usd, 4)),
        "ipn_callback_url":  f"{callback_base}/webhooks/nowpayments/payout-ipn",
        "payout_description": f"PresZ withdrawal #{withdrawal_id}",
        "extra_id":          None,
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
