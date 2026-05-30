"""
Agent purchase endpoints.

Purchase flow (deposit-first model):
  1. User must have sufficient account balance (deposited via POST /deposit)
  2. POST /agents/purchase  → deducts from account balance, creates AgentPurchase (pending),
                               queues Celery activation task immediately
  3. Celery activate_purchase → revenue split → matrix placement → payouts → email

The old checkout / NOWPayments-per-purchase flow is no longer used for new purchases.
"""
import logging
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.api.deps import get_current_user, require_platform_active
from app.core.wallet_ops import debit_account, get_account_balance
from app.database import get_db
from app.models.agent import AgentPurchase, AGENT_TIER_PRICES
from app.models.matrix import MatrixPosition
from app.models.transaction import TransactionType
from app.models.user import User
from app.schemas.agent import MatrixPositionOut, PurchaseOut, PurchaseRequest

router = APIRouter(prefix="/agents", tags=["agents"])

VALID_TIERS = set(AGENT_TIER_PRICES.keys())


@router.post("/purchase", response_model=PurchaseOut, status_code=status.HTTP_201_CREATED)
def purchase_agent(
    payload: PurchaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_active),
):
    """
    Purchase an AI Agent tier using your account balance.

    Requirements:
      - Account balance must be >= agent price
      - Each tier can be purchased only once
      - Tiers must be purchased in order: 1 → 2 → 3 → 4 (cannot skip ahead)

    On success the purchase is queued for immediate activation via Celery.
    """
    if payload.agent_tier not in VALID_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid agent tier. Choose from: {sorted(VALID_TIERS)}",
        )

    # One purchase per tier, and tiers must be bought in order (1 → 2 → 3 → 4).
    # A tier counts as "owned" the moment it is purchased (pending or active).
    # NOTE: this gate applies only to manual purchases. Auto-repurchase calls
    # activate_purchase directly (not this endpoint), so it is intentionally exempt.
    owned_tiers = {
        row.agent_tier
        for row in db.query(AgentPurchase.agent_tier)
        .filter(AgentPurchase.user_id == current_user.id)
        .all()
    }

    if payload.agent_tier in owned_tiers:
        raise HTTPException(
            status_code=400,
            detail=f"You already own Agent {payload.agent_tier}. Each agent tier can only be purchased once.",
        )

    missing_lower = [t for t in range(1, payload.agent_tier) if t not in owned_tiers]
    if missing_lower:
        next_tier = missing_lower[0]
        raise HTTPException(
            status_code=400,
            detail=(
                f"Agents must be purchased in order. "
                f"Purchase Agent {next_tier} before Agent {payload.agent_tier}."
            ),
        )

    price = Decimal(str(AGENT_TIER_PRICES[payload.agent_tier]))

    # Verify balance (informational — debit_account will also enforce)
    balance = get_account_balance(db, current_user.id)
    if balance < price:
        logger.warning(
            "AGENT purchase_failed: insufficient balance user_id=%d username=%s tier=%d required=$%.2f available=$%.2f",
            current_user.id, current_user.username, payload.agent_tier, price, balance,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient account balance. "
                f"Required: ${price:.2f}, Available: ${balance:.2f}. "
                f"Please deposit funds first via POST /deposit."
            ),
        )

    # Create purchase record
    purchase = AgentPurchase(
        user_id=current_user.id,
        agent_tier=payload.agent_tier,
        price=AGENT_TIER_PRICES[payload.agent_tier],
        status="pending",
    )
    db.add(purchase)
    db.flush()  # get purchase.id

    # Deduct from account balance
    debit_account(
        db=db,
        user_id=current_user.id,
        amount=price,
        tx_type=TransactionType.AGENT_PURCHASE,
        reference_id=f"purchase_{purchase.id}",
        notes=f"Agent {payload.agent_tier} purchase (${float(price):.2f})",
    )

    db.commit()
    db.refresh(purchase)

    # Queue revenue engine activation
    from app.workers.tasks import activate_purchase
    activate_purchase.delay(purchase.id)

    logger.info(
        "AGENT purchase_queued: purchase_id=%d user_id=%d username=%s tier=%d price=$%.2f",
        purchase.id, current_user.id, current_user.username, payload.agent_tier, float(price),
    )
    return purchase


@router.get("/purchases", response_model=list[PurchaseOut])
def list_purchases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all agent purchases for the current user."""
    return db.query(AgentPurchase).filter_by(user_id=current_user.id).all()


@router.get("/matrix", response_model=list[MatrixPositionOut])
def my_matrix_positions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all matrix positions (Stream + Boost) for the current user."""
    return db.query(MatrixPosition).filter_by(user_id=current_user.id).all()


# ── Dev-only ──────────────────────────────────────────────────────────────────

@router.post("/purchase/{purchase_id}/confirm", response_model=PurchaseOut)
def confirm_purchase_dev(
    purchase_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    DEV ONLY — manually trigger the revenue engine for a pending purchase
    without requiring payment. Remove or protect this endpoint in production.
    """
    purchase = db.query(AgentPurchase).filter_by(
        id=purchase_id, user_id=current_user.id
    ).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Purchase not found")
    if purchase.status != "pending":
        raise HTTPException(status_code=400, detail="Purchase already processed")

    from app.workers.tasks import activate_purchase
    activate_purchase.delay(purchase_id)

    db.refresh(purchase)
    return purchase
