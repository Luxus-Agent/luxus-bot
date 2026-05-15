"""
Payment endpoints:

  POST /agents/purchase/{purchase_id}/checkout
    → creates a NOWPayments invoice and returns the invoice_url

  POST /webhooks/nowpayments/ipn
    → receives IPN from NOWPayments, verifies HMAC, triggers revenue engine
"""
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.agent import AgentPurchase, AGENT_TIER_PRICES
from app.models.user import User
from app.services.nowpayments import (
    create_agent_invoice,
    get_usdt_networks,
    process_ipn_event,
    verify_ipn_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payments"])


# ── Checkout — create invoice ─────────────────────────────────────────────────

@router.post("/agents/purchase/{purchase_id}/checkout")
async def checkout(
    purchase_id: int,
    usdt_network: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a NOWPayments USDT invoice for a pending agent purchase.
    Returns the invoice_url — redirect the user there to complete payment.

    Optional query param: ?usdt_network=usdtbsc  (defaults to user's choice at checkout)
    """
    purchase = db.query(AgentPurchase).filter_by(
        id=purchase_id, user_id=current_user.id
    ).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Purchase not found.")
    if purchase.status != "pending":
        raise HTTPException(status_code=400, detail="Purchase is not in pending state.")
    if purchase.payment_id:
        raise HTTPException(status_code=400, detail="Invoice already created for this purchase.")

    return await create_agent_invoice(
        db=db,
        purchase_id=purchase_id,
        amount_usd=float(AGENT_TIER_PRICES[purchase.agent_tier]),
        agent_tier=purchase.agent_tier,
        usdt_network=usdt_network,
    )


@router.get("/payments/networks")
def usdt_networks():
    """Return supported USDT networks for payment."""
    return get_usdt_networks()


# ── IPN webhook ───────────────────────────────────────────────────────────────

@router.post("/webhooks/nowpayments/ipn", status_code=status.HTTP_200_OK)
async def nowpayments_ipn(
    request: Request,
    db: Session = Depends(get_db),
    x_nowpayments_sig: str | None = Header(default=None, alias="x-nowpayments-sig"),
):
    """
    NOWPayments IPN callback endpoint.

    NOWPayments calls this when payment status changes.
    We verify the HMAC signature, then hand off to the revenue engine via Celery.

    Always returns 200 — NOWPayments will retry on any non-200 response.
    """
    raw_body = await request.body()

    # 1. Verify signature
    if not x_nowpayments_sig:
        logger.warning("[IPN] Missing x-nowpayments-sig header")
        raise HTTPException(status_code=400, detail="Missing signature header")

    if not verify_ipn_signature(raw_body, x_nowpayments_sig):
        logger.error("[IPN] Signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2. Parse payload
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("[IPN] Invalid JSON body")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # 3. Process (synchronous DB + Celery dispatch)
    result = process_ipn_event(db=db, payload=payload)
    logger.info("[IPN] Processed: %s", result)
    return result
