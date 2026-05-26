"""
Payment endpoints:

  GET  /payments/networks
    → supported USDT networks (BEP-20 only)

  POST /webhooks/nowpayments/ipn
    → deposit/purchase payment IPN from NOWPayments

  POST /webhooks/nowpayments/payout-ipn
    → withdrawal payout IPN from NOWPayments
"""
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.nowpayments import (
    get_usdt_networks,
    process_ipn_event,
    process_payout_ipn_event,
    verify_ipn_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payments"])


@router.get("/payments/networks")
def usdt_networks():
    """Return supported USDT networks for payment."""
    return get_usdt_networks()


# ── Deposit / purchase IPN ────────────────────────────────────────────────────

@router.post("/webhooks/nowpayments/ipn", status_code=status.HTTP_200_OK)
async def nowpayments_ipn(
    request: Request,
    db: Session = Depends(get_db),
    x_nowpayments_sig: str | None = Header(default=None, alias="x-nowpayments-sig"),
):
    """
    NOWPayments payment IPN handler.

    Fires when a deposit or (legacy) agent purchase payment changes status.
    Always returns 200 — NOWPayments retries on any non-200.
    """
    raw_body = await request.body()

    if not x_nowpayments_sig:
        logger.warning("[IPN] Missing x-nowpayments-sig header")
        raise HTTPException(status_code=400, detail="Missing signature header")

    if not verify_ipn_signature(raw_body, x_nowpayments_sig):
        logger.error("[IPN] Signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("[IPN] Invalid JSON body")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    result = process_ipn_event(db=db, payload=payload)
    logger.info("[IPN] Processed: %s", result)
    return result


# ── Payout IPN ────────────────────────────────────────────────────────────────

@router.post("/webhooks/nowpayments/payout-ipn", status_code=status.HTTP_200_OK)
async def nowpayments_payout_ipn(
    request: Request,
    db: Session = Depends(get_db),
    x_nowpayments_sig: str | None = Header(default=None, alias="x-nowpayments-sig"),
):
    """
    NOWPayments payout IPN handler.

    Fires when a withdrawal payout transitions to FINISHED (confirmed on-chain)
    or FAILED. On FAILED we refund the amount to the user's MAIN wallet.
    Always returns 200 — NOWPayments retries on any non-200.
    """
    raw_body = await request.body()

    if not x_nowpayments_sig:
        logger.warning("[PayoutIPN] Missing x-nowpayments-sig header")
        raise HTTPException(status_code=400, detail="Missing signature header")

    if not verify_ipn_signature(raw_body, x_nowpayments_sig):
        logger.error("[PayoutIPN] Signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("[PayoutIPN] Invalid JSON body")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    result = process_payout_ipn_event(db=db, payload=payload)
    logger.info("[PayoutIPN] Processed: %s", result)
    return result
