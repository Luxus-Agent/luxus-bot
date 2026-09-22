"""
Core Agent eligibility / compression helpers.

These are the shared rules for who qualifies to receive Core income, used by the
on-chain pack split (`app/core/pack_payout.py`). The deposit-first routing that
once lived here (route_core / wallet credits) was removed when the platform moved
fully on-chain — purchases now pay uplines directly from the buyer's wallet.

Compression format
  An upline only QUALIFIES for Core income from a purchase if their own highest
  active purchased tier is >= the tier the buyer just purchased. Uplines who
  bought a lower tier (or own no active agent, or are frozen) are SKIPPED — the
  income compresses past them up the sponsor chain to the next eligible upline.
    e.g. E buys $100 (tier 4); uplines D ($20), C ($10), B ($10) are skipped;
         income lands on A ($100) and the next eligible upline (Admin, $100).

The odd/even routing rule that pairs with this lives in `pack_payout.py`
(via the recipient's per-tier User.core_route_count_tierN, keyed by buyer_tier).
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.agent import AgentPurchase


def _highest_active_tier(db: Session, user_id: int) -> int:
    """Highest agent tier the user currently owns as an ACTIVE purchase (0 = none)."""
    highest = (
        db.query(func.max(AgentPurchase.agent_tier))
        .filter(
            AgentPurchase.user_id == user_id,
            AgentPurchase.status == "active",
        )
        .scalar()
    )
    return int(highest) if highest else 0


def _is_eligible(db: Session, user: User | None, buyer_tier: int) -> bool:
    """A user qualifies for Core income only if they are active (not frozen) and
    their highest active purchased tier covers the buyer's tier (compression).
    Admin is exempt from the tier-ownership half of this check — seed_admin.py
    never gives the admin account an AgentPurchase, so without this exemption
    admin could never qualify as the root Core recipient at all."""
    if user is None or not user.is_active:
        return False
    if user.is_admin:
        return True
    return _highest_active_tier(db, user.id) >= buyer_tier

