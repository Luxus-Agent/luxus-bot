"""
ProActive income routing — updated per Luxus.docx spec.

Split: 60% of purchase price → two equal halves
  • First  30%  → Sponsor         (direct upline)
  • Second 30%  → Supreme Sponsor (sponsor's sponsor)

Odd / Even rule — applied independently at each recipient:
  • Count how many PROACTIVE_INCOME credits the recipient has already received.
  • Next incoming credit will be count + 1.
    – Odd  → credit goes to recipient's wallet
    – Even → credit passes to recipient's sponsor's wallet instead
  • If the recipient has no upline when the pass-up fires, the amount stays
    with the recipient.
  • If a target (sponsor / supreme) does not exist, the amount is credited
    back to the buyer so no money is lost.
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models.user import User
from app.models.transaction import Transaction, TransactionType
from app.core.wallet_ops import credit_wallet


def _proactive_income_count(db: Session, user_id: int) -> int:
    """Return the number of PROACTIVE_INCOME credits this user has received so far."""
    return (
        db.query(Transaction)
        .filter_by(user_id=user_id, transaction_type=TransactionType.PROACTIVE_INCOME)
        .count()
    )


def _route_half(
    db: Session,
    buyer: User,
    primary_recipient: User | None,
    agent_tier: int,
    amount: Decimal,
    label: str,
) -> None:
    """
    Route one half (30%) of the proactive amount.

    Odd income  → primary_recipient's wallet
    Even income → primary_recipient's sponsor's wallet
    No recipient or inactive recipient → falls back to buyer's wallet
    """
    # Treat inactive users the same as missing — skip them
    if primary_recipient is not None and not primary_recipient.is_active:
        primary_recipient = None

    if primary_recipient is None:
        # No sponsor chain — credit stays with the buyer
        credit_wallet(
            db=db,
            user_id=buyer.id,
            agent_tier=agent_tier,
            gross_amount=amount,
            tx_type=TransactionType.PROACTIVE_INCOME,
            reference_id=f"proactive_{buyer.id}_{label}",
            notes=f"ProActive {label} — no sponsor, credited to buyer",
        )
        return

    # Determine odd/even: next income number = current_count + 1
    next_count = _proactive_income_count(db, primary_recipient.id) + 1

    if next_count % 2 == 1:
        # Odd → primary recipient keeps it
        beneficiary_id = primary_recipient.id
        notes = f"ProActive {label} — odd income #{next_count}"
    else:
        # Even → pass to primary recipient's sponsor (if active)
        upline: User | None = (
            db.query(User).filter_by(id=primary_recipient.sponsor_id).first()
            if primary_recipient.sponsor_id else None
        )
        if upline is not None and not upline.is_active:
            upline = None

        if upline is not None:
            beneficiary_id = upline.id
            notes = f"ProActive {label} — even income #{next_count}, passed to upline"
        else:
            # No active upline to pass to — recipient keeps it
            beneficiary_id = primary_recipient.id
            notes = f"ProActive {label} — even income #{next_count}, no active upline, kept"

    # Record outgoing side on buyer
    db.add(Transaction(
        user_id=buyer.id,
        agent_tier=agent_tier,
        transaction_type=TransactionType.PROACTIVE_SENT,
        amount=amount,
        reference_id=f"proactive_{buyer.id}_{label}",
        notes=f"ProActive {label} sent (buyer position in sponsor downline: {buyer.sponsor_position})",
    ))

    credit_wallet(
        db=db,
        user_id=beneficiary_id,
        agent_tier=agent_tier,
        gross_amount=amount,
        tx_type=TransactionType.PROACTIVE_INCOME,
        reference_id=f"proactive_{buyer.id}_{label}",
        notes=notes,
    )


def route_proactive(
    db: Session,
    buyer: User,
    agent_tier: int,
    amount: Decimal,  # This is 60% of the purchase price
) -> None:
    """
    Route the ProActive portion of a purchase.

    amount (60% of purchase) is split into two equal halves:
      • First  half → buyer's direct Sponsor
      • Second half → buyer's Supreme Sponsor (sponsor's sponsor)

    Each recipient's odd/even income count determines whether they wallet
    the amount or pass it up one more level.
    """
    four_places = Decimal("0.0001")
    first_half  = (amount / 2).quantize(four_places, rounding=ROUND_HALF_UP)
    second_half = amount - first_half  # Ensures exact sum

    # Load sponsor — skip if inactive or missing
    sponsor: User | None = (
        db.query(User).filter_by(id=buyer.sponsor_id).first()
        if buyer.sponsor_id else None
    )
    if sponsor is not None and not sponsor.is_active:
        sponsor = None

    # Load supreme sponsor — use sponsor's sponsor (or skip if inactive)
    supreme: User | None = (
        db.query(User).filter_by(id=sponsor.sponsor_id).first()
        if (sponsor and sponsor.sponsor_id) else None
    )
    if supreme is not None and not supreme.is_active:
        supreme = None

    _route_half(db, buyer, sponsor,  agent_tier, first_half,  "sponsor")
    _route_half(db, buyer, supreme, agent_tier, second_half, "supreme")
