from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.agent import AgentPurchase, AGENT_TIER_PRICES
from app.models.matrix import MatrixPosition
from app.models.user import User
from app.schemas.agent import MatrixPositionOut, PurchaseOut, PurchaseRequest

router = APIRouter(prefix="/agents", tags=["agents"])

VALID_TIERS = set(AGENT_TIER_PRICES.keys())


@router.post("/purchase", response_model=PurchaseOut, status_code=status.HTTP_201_CREATED)
def purchase_agent(
    payload: PurchaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.agent_tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail="Invalid agent tier. Choose 1, 2, 3, or 4.")

    existing = db.query(AgentPurchase).filter_by(
        user_id=current_user.id, agent_tier=payload.agent_tier, status="active"
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Agent {payload.agent_tier} already active")

    purchase = AgentPurchase(
        user_id=current_user.id,
        agent_tier=payload.agent_tier,
        price=AGENT_TIER_PRICES[payload.agent_tier],
        status="pending",
    )
    db.add(purchase)
    db.commit()
    db.refresh(purchase)
    return purchase


@router.post("/purchase/{purchase_id}/confirm", response_model=PurchaseOut)
def confirm_purchase(
    purchase_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dev placeholder: manually triggers the revenue engine. Replace with NOWPayments webhook in production."""
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


@router.get("/purchases", response_model=list[PurchaseOut])
def list_purchases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(AgentPurchase).filter_by(user_id=current_user.id).all()


@router.get("/matrix", response_model=list[MatrixPositionOut])
def my_matrix_positions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(MatrixPosition).filter_by(user_id=current_user.id).all()
