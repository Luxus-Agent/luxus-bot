"""
Agent purchase read endpoints.

Purchases are made on-chain via the TokenPocket / MultiSender DApp rail
(POST /distribution/pack/purchase + /pack/status). The buyer pays the upline
split directly from their connected wallet; the on-chain success handler records
ownership. These endpoints are read-only views of that ownership and the user's
matrix positions.
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.api.deps import get_current_user
from app.database import get_db
from app.models.agent import AgentPurchase
from app.models.user import User
from app.schemas.agent import PurchaseOut

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/purchases", response_model=list[PurchaseOut])
def list_purchases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all agent purchases for the current user."""
    return db.query(AgentPurchase).filter_by(user_id=current_user.id).all()
