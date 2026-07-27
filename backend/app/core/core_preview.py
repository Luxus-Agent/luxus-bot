"""
Read-only preview of the Core Agent 60% compression + odd/even split.

Mirrors app.core.pack_payout.compute_pack_split's upline-selection logic exactly
(compression via _highest_active_tier/_is_eligible, odd/even via
User.core_route_count), but only PEEKS at core_route_count — never persists —
and additionally reports the compression-skipped uplines for each hop, which
compute_pack_split doesn't need since it only cares about the final recipient.

Used by both the admin "Revenue Engines" page (any username) and the user-
facing Core preview (always the logged-in user), so running this repeatedly
never affects real payouts or the real odd/even alternation.
"""
from sqlalchemy.orm import Session

from app.core.proactive import _highest_active_tier  # noqa: PLC2701
from app.models.user import User


def _sponsor_of(db: Session, user: User | None) -> User | None:
    return db.query(User).filter_by(id=user.sponsor_id).first() if user and user.sponsor_id else None


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
        highest = _highest_active_tier(db, current.id)
        if current.is_active and highest >= buyer_tier:
            return current, skipped
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


def _resolve_half(db: Session, primary: User | None, buyer_tier: int) -> dict:
    """Peek (never mutate) the odd/even outcome for one eligible Core candidate."""
    if primary is None:
        return {
            "candidate": None, "parity": None, "route_count_after": None,
            "recipient": None, "passup_skipped": [], "passup_fallback_to_candidate": False,
        }
    count = (primary.core_route_count or 0) + 1
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
    """Full two-half Core routing preview for `buyer` purchasing `buyer_tier`."""
    first_candidate, first_skip = _walk_skip_chain(db, _sponsor_of(db, buyer), buyer_tier)
    second_candidate, second_skip = (
        _walk_skip_chain(db, _sponsor_of(db, first_candidate), buyer_tier)
        if first_candidate is not None else (None, [])
    )

    half1 = _resolve_half(db, first_candidate, buyer_tier)
    half1["compression_skipped"] = first_skip
    half2 = _resolve_half(db, second_candidate, buyer_tier)
    half2["compression_skipped"] = second_skip

    return {"buyer": buyer.username, "buyer_tier": buyer_tier, "half1": half1, "half2": half2}


def get_downline_odd_even(db: Session, sponsor: User) -> dict:
    """
    Read-only: `sponsor`'s DIRECT downline (people they personally referred), split
    into a left/odd and right/even column by join order — 1st, 3rd, 5th... referral
    on the left (odd), 2nd, 4th... on the right (even). Per the client's Core-agent
    table request: "Their downline will be occupying the left and right column or
    odd and even column."

    This is a different axis from simulate_core_split above: that walks UP the
    sponsor chain to find who RECEIVES a given buyer's commission (keyed off
    User.core_route_count, incremented per targeting). This instead lists a
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
