"""
Read-only preview of the Core Agent 60% compression + odd/even split.

Mirrors app.core.pack_payout.compute_pack_split's upline-selection logic exactly
— a single continuous walk up the sponsor chain per half, combining compression
(_is_eligible) and odd/even (the recipient's per-tier User.core_route_count_tierN,
keyed by buyer_tier) into one pass; the second half's walk continues from one
level above wherever the first half's walk actually landed — but only PEEKS at
the counter (never persists), and additionally reports a step-by-step trail of
every hop (skipped-ineligible or skipped-even) for display, which
compute_pack_split doesn't need since it only cares about the final recipient.

Used by both the admin "Revenue Engines" page (any username) and the user-
facing Core preview (always the logged-in user), so running this repeatedly
never affects real payouts or the real odd/even alternation.
"""
import json
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.proactive import _highest_active_tier, _is_eligible  # noqa: PLC2701
from app.models.agent import AGENT_TIER_PRICES, AgentPurchase
from app.models.pack_purchase import PackPurchase, PackPurchaseStatus
from app.models.user import User

# Each Core half is 30% of the tier's base price (60% split two ways) — same
# CORE_RATE math as app.core.pack_payout, quantized to cents since this is a
# display-only preview amount, not an on-chain payment.
_CORE_HALF_RATE = Decimal("0.30")
_CENTS = Decimal("0.01")


def _half_amount(buyer_tier: int) -> str:
    price = Decimal(str(AGENT_TIER_PRICES[buyer_tier]))
    return str((price * _CORE_HALF_RATE).quantize(_CENTS, rounding=ROUND_HALF_UP))


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
    # "upline" = actually paid on-chain. "core_unpaid" = the recipient the routing
    # decided on but who had no wallet address to pay (folded into platform_fee at
    # settlement) — included here so the preview still names them, not just the
    # dollar amount that ended up as platform profit.
    return [
        {"username": r["username"], "amount": r.get("gross_amount", r.get("amount"))}
        for r in recipients if r.get("role") in ("upline", "core_unpaid")
    ]


def _walk_core_half_peek(
    db: Session, start: User | None, buyer_tier: int, virtual_targetings: dict[int, int]
) -> tuple[User | None, list[dict]]:
    """
    Peek-only mirror of pack_payout._walk_core_half: walk up the sponsor chain
    from `start` (inclusive), combining compression and odd/even into one
    continuous pass, but never persisting the counter. Returns (recipient,
    trail) — trail is an ordered list of every hop, each either a compression
    skip (ineligible) or an eligible-but-even skip, ending with the final
    stop (odd, or the last-eligible fallback if the chain ran out).

    `virtual_targetings` accumulates {user_id: times already peeked this same
    two-half preview} — only relevant when the sole eligible upline absorbs
    both halves (see simulate_core_split): since nothing persists, an earlier
    virtual targeting of the same candidate wouldn't otherwise show up in
    their core_route_count_tierN when resolving the second half.
    """
    current = start
    seen: set[int] = set()
    trail: list[dict] = []
    last_eligible: User | None = None
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if _is_eligible(db, current, buyer_tier):
            last_eligible = current
            extra = virtual_targetings.get(current.id, 0)
            count = current.get_core_route_count(buyer_tier) + extra + 1
            virtual_targetings[current.id] = extra + 1
            if count % 2 == 1:
                trail.append({
                    "username": current.username, "eligible": True,
                    "parity": "odd", "route_count_after": count, "kept": True,
                })
                return current, trail
            trail.append({
                "username": current.username, "eligible": True,
                "parity": "even", "route_count_after": count, "kept": False,
            })
        else:
            highest = _highest_active_tier(db, current.id)
            trail.append({
                "username": current.username, "eligible": False, "kept": False,
                "reason": (
                    "frozen" if not current.is_active
                    else f"highest active tier is {highest or 'none'} (< tier {buyer_tier})"
                ),
            })
        current = _sponsor_of(db, current)
    return last_eligible, trail


def _half_result(recipient: User | None, amount: str, trail: list[dict]) -> dict:
    return {"recipient": recipient.username if recipient else None, "amount": amount, "trail": trail}


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

    amount = _half_amount(buyer_tier)
    virtual_targetings: dict[int, int] = {}

    first_recipient, first_trail = _walk_core_half_peek(
        db, _sponsor_of(db, buyer), buyer_tier, virtual_targetings
    )
    half1 = _half_result(first_recipient, amount, first_trail)

    if first_recipient is None:
        half2 = _half_result(None, amount, [])
    else:
        second_recipient, second_trail = _walk_core_half_peek(
            db, _sponsor_of(db, first_recipient), buyer_tier, virtual_targetings
        )
        if second_recipient is None:
            # No distinct eligible upline above the first recipient → the sole
            # eligible upline absorbs the second half too, via its own fresh
            # (virtually tracked) targeting — mirrors compute_pack_split.
            second_recipient, second_trail = _walk_core_half_peek(
                db, first_recipient, buyer_tier, virtual_targetings
            )
        half2 = _half_result(second_recipient, amount, second_trail)

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
