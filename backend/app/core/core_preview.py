"""
Read-only preview of the Core Agent 60% compression + odd/even split.

Mirrors app.core.pack_payout.compute_pack_split's upline-selection logic exactly
(compression via _highest_active_tier/_is_eligible, odd/even via the recipient's
per-tier User.core_route_count_tierN, keyed by buyer_tier), but only PEEKS at the
counter — never persists — and additionally reports the compression-skipped
uplines for each hop, which compute_pack_split doesn't need since it only cares
about the final recipient.

Used by both the admin "Revenue Engines" page (any username) and the user-
facing Core preview (always the logged-in user), so running this repeatedly
never affects real payouts or the real odd/even alternation.
"""
import json

from sqlalchemy.orm import Session

from app.core.proactive import _highest_active_tier, _is_eligible  # noqa: PLC2701
from app.models.agent import AgentPurchase
from app.models.pack_purchase import PackPurchase, PackPurchaseStatus
from app.models.user import User


def _sponsor_of(db: Session, user: User | None) -> User | None:
    return db.query(User).filter_by(id=user.sponsor_id).first() if user and user.sponsor_id else None


def _get_actual_core_recipients(db: Session, buyer: User, buyer_tier: int) -> list[dict] | None:
    """If `buyer` already owns `buyer_tier` (bought it for real), return the
    ACTUAL recorded Core upline recipients from that settled purchase's stored
    recipients_json, instead of a hypothetical peek. A hypothetical peek of an
    already-owned tier is misleading — it answers "what if this happened again
    right now", which necessarily diverges once anyone else's purchase has
    since advanced the same recipients' odd/even counters, not what actually
    happened. Returns None if the buyer doesn't own this tier (real preview
    territory)."""
    owns_tier = (
        db.query(AgentPurchase.id)
        .filter(AgentPurchase.user_id == buyer.id, AgentPurchase.agent_tier == buyer_tier,
                AgentPurchase.status == "active")
        .first()
    )
    if not owns_tier:
        return None
    record = (
        db.query(PackPurchase)
        .filter_by(buyer_id=buyer.id, agent_tier=buyer_tier, status=PackPurchaseStatus.SUCCESS)
        .order_by(PackPurchase.created_at.desc())
        .first()
    )
    if record is None:
        return None
    recipients = json.loads(record.recipients_json or "[]")
    return [
        {"username": r["username"], "amount": r.get("gross_amount", r.get("amount"))}
        for r in recipients if r.get("role") == "upline"
    ]


def _walk_skip_chain(
    db: Session, start: User | None, buyer_tier: int
) -> tuple[User | None, list[dict]]:
    """Walk up the sponsor chain from `start`, collecting compression-skipped
    uplines (frozen or tier-too-low), and return the first eligible one."""
    current = start
    seen: set[int] = set()
    skipped: list[dict] = []
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if _is_eligible(db, current, buyer_tier):
            return current, skipped
        highest = _highest_active_tier(db, current.id)
        skipped.append({
            "username": current.username,
            "is_active": current.is_active,
            "highest_active_tier": highest,
            "reason": (
                "frozen" if not current.is_active
                else f"highest active tier is {highest or 'none'} (< tier {buyer_tier})"
            ),
        })
        current = _sponsor_of(db, current)
    return None, skipped


def _resolve_half(db: Session, primary: User | None, buyer_tier: int, extra_targetings: int = 0) -> dict:
    """Peek (never mutate) the odd/even outcome for one eligible Core candidate.
    `extra_targetings` accounts for this same candidate already having been
    virtually targeted earlier in this same two-half preview (only possible
    when the sole eligible upline absorbs both halves — see simulate_core_split)
    — since this never persists, that earlier targeting wouldn't otherwise show
    up in primary.core_route_count_tierN when resolving the second half."""
    if primary is None:
        return {
            "candidate": None, "parity": None, "route_count_after": None,
            "recipient": None, "passup_skipped": [], "passup_fallback_to_candidate": False,
        }
    count = primary.get_core_route_count(buyer_tier) + extra_targetings + 1
    if count % 2 == 1:
        return {
            "candidate": primary.username, "parity": "odd", "route_count_after": count,
            "recipient": primary.username, "passup_skipped": [], "passup_fallback_to_candidate": False,
        }
    upline, skipped = _walk_skip_chain(db, _sponsor_of(db, primary), buyer_tier)
    return {
        "candidate": primary.username, "parity": "even", "route_count_after": count,
        "recipient": upline.username if upline else primary.username,
        "passup_skipped": skipped,
        "passup_fallback_to_candidate": upline is None,
    }


def simulate_core_split(db: Session, buyer: User, buyer_tier: int) -> dict:
    """Two-half Core routing preview for `buyer` purchasing `buyer_tier` — or,
    if `buyer` already owns `buyer_tier`, the ACTUAL recorded result from that
    real purchase (see _get_actual_core_recipients)."""
    actual_recipients = _get_actual_core_recipients(db, buyer, buyer_tier)
    if actual_recipients is not None:
        return {
            "buyer": buyer.username, "buyer_tier": buyer_tier,
            "actual": True, "recipients": actual_recipients,
        }

    first_candidate, first_skip = _walk_skip_chain(db, _sponsor_of(db, buyer), buyer_tier)
    second_candidate, second_skip = (
        _walk_skip_chain(db, _sponsor_of(db, first_candidate), buyer_tier)
        if first_candidate is not None else (None, [])
    )
    # No DISTINCT second eligible upline above the first → mirrors
    # compute_pack_split: the sole eligible upline absorbs both halves instead
    # of the second forfeiting to platform profit.
    if first_candidate is not None and second_candidate is None:
        second_candidate = first_candidate

    half1 = _resolve_half(db, first_candidate, buyer_tier)
    half1["compression_skipped"] = first_skip
    same_candidate = (
        first_candidate is not None and second_candidate is not None
        and second_candidate.id == first_candidate.id
    )
    half2 = _resolve_half(db, second_candidate, buyer_tier, extra_targetings=1 if same_candidate else 0)
    half2["compression_skipped"] = second_skip

    return {
        "buyer": buyer.username, "buyer_tier": buyer_tier,
        "actual": False, "half1": half1, "half2": half2,
    }


def get_downline_odd_even(db: Session, sponsor: User) -> dict:
    """
    Read-only: `sponsor`'s DIRECT downline (people they personally referred), split
    into a left/odd and right/even column by join order — 1st, 3rd, 5th... referral
    on the left (odd), 2nd, 4th... on the right (even). Per the client's Core-agent
    table request: "Their downline will be occupying the left and right column or
    odd and even column."

    This is a different axis from simulate_core_split above: that walks UP the
    sponsor chain to find who RECEIVES a given buyer's commission (keyed off the
    recipient's per-tier User.core_route_count_tierN, incremented per targeting).
    This instead lists a
    sponsor's own DOWNLINE, ordered by when each one joined (User.sponsor_position,
    falling back to a live-recomputed rank so members re-parented after an admin
    deletion — which clears sponsor_position — still land in a column).
    """
    members = (
        db.query(User)
        .filter(User.sponsor_id == sponsor.id)
        .order_by(User.sponsor_position.asc().nulls_last(), User.created_at.asc())
        .all()
    )

    left_odd: list[dict] = []
    right_even: list[dict] = []
    for rank, member in enumerate(members, start=1):
        row = {
            "username": member.username,
            "position": rank,
            "sponsor_position": member.sponsor_position,
            "is_active": member.is_active,
            "highest_active_tier": _highest_active_tier(db, member.id),
            "joined_at": member.created_at.isoformat() if member.created_at else None,
        }
        (left_odd if rank % 2 == 1 else right_even).append(row)

    return {
        "sponsor": sponsor.username,
        "total": len(members),
        "left_odd": left_odd,
        "right_even": right_even,
    }
