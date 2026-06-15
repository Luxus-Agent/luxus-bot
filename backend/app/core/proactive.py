"""
Core Agent income routing (formerly ProActive).

Split: 60% of purchase price → two equal halves
  • First  30%  → first  eligible upline
  • Second 30%  → second eligible upline (next eligible above the first)

Two rules apply together in the Core Agent (and ONLY here):

1. Compression format
   An upline only QUALIFIES for Core income from a purchase if their own
   highest active purchased tier is >= the tier the buyer just purchased.
   Uplines who bought a lower tier (or own no active agent, or are frozen)
   are SKIPPED — the income compresses past them up the sponsor chain to the
   next eligible upline.
     e.g. E buys $100 (tier 4); uplines D ($20), C ($10), B ($10) are skipped;
          income lands on A ($100) and the next eligible upline (Admin, $100).
   The two 30% halves go to the first eligible upline and the next eligible
   upline above it. If no eligible upline exists for a half, it is retained by
   the platform (realized profit) — it is NOT credited back to the buyer.

2. Odd / Even rule — applied independently at each eligible recipient
   • Each recipient has a targeting counter (User.core_route_count) that is
     incremented every time they are targeted — whether they keep the amount
     (odd) or pass it up (even). This guarantees strict alternation; counting
     only kept credits left a recipient stuck on "even" forever after their
     first pass-up.
       – Odd  count → credit goes to recipient's wallet
       – Even count → credit passes UP to the next ELIGIBLE upline above the
                      recipient (the pass-up is compressed too).
   • If no eligible upline exists for an even pass-up, the amount stays with
     the recipient.
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.agent import AgentPurchase
from app.models.transaction import Transaction, TransactionType
from app.core.wallet_ops import credit_wallet


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
    their highest active purchased tier covers the buyer's tier (compression)."""
    if user is None or not user.is_active:
        return False
    return _highest_active_tier(db, user.id) >= buyer_tier


def _next_eligible_upline(
    db: Session, start: User | None, buyer_tier: int
) -> User | None:
    """Walk UP the sponsor chain from `start` (inclusive) and return the first
    eligible user, skipping ineligible / inactive ones (compression)."""
    current = start
    seen: set[int] = set()  # cycle guard
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if _is_eligible(db, current, buyer_tier):
            return current
        current = (
            db.query(User).filter_by(id=current.sponsor_id).first()
            if current.sponsor_id else None
        )
    return None


def _route_half(
    db: Session,
    buyer: User,
    primary_recipient: User | None,
    agent_tier: int,
    amount: Decimal,
    label: str,
) -> None:
    """
    Route one half (30%) of the Core Agent amount.

    `primary_recipient` is an already-resolved ELIGIBLE upline (or None).
    Odd income  → primary_recipient's wallet
    Even income → next eligible upline above primary_recipient (compressed)
    No eligible recipient → amount retained by platform (company profit)
    """
    if primary_recipient is None:
        # No eligible upline → amount is retained by the platform (realized profit).
        db.add(Transaction(
            user_id=buyer.id,
            agent_tier=agent_tier,
            transaction_type=TransactionType.PLATFORM_PROFIT,
            amount=amount,
            reference_id=f"core_retained_{buyer.id}_{label}",
            notes=f"Core {label} — no eligible upline, retained by platform",
        ))
        return

    # Determine odd/even by this recipient's TARGETING counter. Increment on
    # every targeting (kept or passed) so the alternation never gets stuck.
    primary_recipient.core_route_count = (primary_recipient.core_route_count or 0) + 1
    next_count = primary_recipient.core_route_count
    db.flush()

    if next_count % 2 == 1:
        # Odd → primary recipient keeps it
        beneficiary_id = primary_recipient.id
        notes = f"Core {label} — odd income #{next_count}"
    else:
        # Even → pass to the next ELIGIBLE upline above the recipient (compressed)
        upline = _next_eligible_upline(
            db,
            (db.query(User).filter_by(id=primary_recipient.sponsor_id).first()
             if primary_recipient.sponsor_id else None),
            agent_tier,
        )

        if upline is not None:
            beneficiary_id = upline.id
            notes = f"Core {label} — even income #{next_count}, passed to eligible upline"
        else:
            # No eligible upline to pass to — recipient keeps it
            beneficiary_id = primary_recipient.id
            notes = f"Core {label} — even income #{next_count}, no eligible upline, kept"

    # Record outgoing side on buyer
    db.add(Transaction(
        user_id=buyer.id,
        agent_tier=agent_tier,
        transaction_type=TransactionType.CORE_SENT,
        amount=amount,
        reference_id=f"core_{buyer.id}_{label}",
        notes=f"Core {label} sent",
    ))

    credit_wallet(
        db=db,
        user_id=beneficiary_id,
        agent_tier=agent_tier,
        gross_amount=amount,
        tx_type=TransactionType.CORE_INCOME,
        reference_id=f"core_{buyer.id}_{label}",
        notes=notes,
    )


def route_core(
    db: Session,
    buyer: User,
    agent_tier: int,
    amount: Decimal,  # This is 60% of the purchase price
) -> None:
    """
    Route the Core Agent portion of a purchase.

    amount (60% of purchase) is split into two equal halves and routed up the
    sponsor chain with COMPRESSION — ineligible uplines (lower tier / inactive)
    are skipped:
      • First  half → first  eligible upline
      • Second half → next eligible upline above the first

    Each recipient's odd/even income count then determines whether they wallet
    the amount or pass it up to the next eligible upline.
    """
    four_places = Decimal("0.0001")
    first_half  = (amount / 2).quantize(four_places, rounding=ROUND_HALF_UP)
    second_half = amount - first_half  # Ensures exact sum

    # First eligible upline: compress from the buyer's direct sponsor upward.
    first = _next_eligible_upline(
        db,
        (db.query(User).filter_by(id=buyer.sponsor_id).first()
         if buyer.sponsor_id else None),
        agent_tier,
    )

    # Second eligible upline: compress from the first eligible's sponsor upward.
    second = _next_eligible_upline(
        db,
        (db.query(User).filter_by(id=first.sponsor_id).first()
         if (first and first.sponsor_id) else None),
        agent_tier,
    ) if first is not None else None

    _route_half(db, buyer, first,  agent_tier, first_half,  "sponsor")
    _route_half(db, buyer, second, agent_tier, second_half, "supreme")
