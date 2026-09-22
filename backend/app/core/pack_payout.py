"""
Pack-purchase payout split for the on-chain (BEP-20 USDT) rail.

This computes the full 60/30/10 split for a single pack purchase (per the client
"Classification of Agents" spec):

  Core Agent  — 60% of the price, routed to uplines as two equal 30% halves via
    a SINGLE continuous walk up the sponsor chain per half:
      – first  half → walk up from the buyer's direct sponsor, skipping anyone
        ineligible (compression) AND anyone whose per-tier turn lands even
        (their counter still advances; the amount keeps climbing to the next
        eligible upline) — the first eligible upline whose turn lands ODD
        keeps it. If the chain runs out first (nobody above is eligible), the
        last eligible upline seen keeps it regardless of parity ("no eligible
        upline for an even pass-up -> recipient keeps it").
      – second half → the SAME walk, run again, but starting one level above
        wherever the first half's walk actually ended up (not back at the
        direct sponsor, and not back at the first half's original compression
        candidate if that candidate's own turn was even and passed the money
        further up). If that walk finds no one at all (the first half's
        recipient has no eligible upline above them whatsoever), the sole
        eligible upline absorbs the second half too, via its OWN fresh,
        independent odd/even targeting — rather than forfeiting it to
        platform profit.
    "Eligible" = compression: the upline is active AND their highest active
    purchased tier >= the buyer's tier (reuses proactive._is_eligible — Admin is
    exempt from the tier-ownership half of that check). Odd/even is keyed by
    User.core_route_count_tierN, keyed by the BUYER's tier — a tier-1 purchase
    and a tier-2 purchase targeting the same recipient alternate independently.
    A half only folds into the platform amount (company profit) when the FIRST
    half's walk finds no eligible upline at all (buyer has no sponsor, or the
    whole chain above them is ineligible/frozen) — in that case there is by
    definition no one for the second half to reach either, so both fold.

  Stream Agent — 30% of the price → the Stream matrix pool (per tier).
  Boost Agent  — 10% of the price → 9% to the Boost matrix pool (global, drawn down
    by the Boost engine) + 1% to the admin income wallet.

So the full price is allocated 60 / 30 / 9 / 1 (Core / Stream / Boost / admin);
there is NO flat 40% platform fee anymore — the platform earns from the 10%
software fees and matrix residuals instead. The Stream/Boost amounts are PARKED in
platform-held pools here; the matrix engines (separate) distribute them later.

The amounts here are the FULL on-chain amounts (they sum to the pack price) — the
internal 70/20/10 wallet deductions are NOT applied on this rail, because nothing
is credited to internal wallets; the buyer pays each recipient directly on-chain.

This module never writes Wallet/Transaction rows. It optionally mutates the
recipient's per-tier User.core_route_count_tierN (when mutate_counter=True) to
advance that tier's odd/even alternation.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.proactive import _is_eligible  # noqa: PLC2701
from app.models.user import User

CORE_RATE = Decimal("0.60")    # 60% → uplines (two 30% halves)
STREAM_RATE = Decimal("0.30")  # 30% → Stream matrix pool (per tier)
ADMIN_RATE = Decimal("0.01")   # 1%  → admin income wallet (part of the Boost 10%)
# Boost gets the remaining 9% (10% Boost allocation − 1% admin); computed as the
# residual so the four parts sum exactly to the price.
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")


@dataclass
class PackSplit:
    # Ordered upline beneficiaries: [(user, amount), ...] — index 0 = level 1.
    uplines: list[tuple[User, Decimal]] = field(default_factory=list)
    stream_amount: Decimal = Decimal("0")    # 30% → Stream pool (per tier)
    boost_amount: Decimal = Decimal("0")     # 9%  → Boost pool (global)
    admin_amount: Decimal = Decimal("0")     # 1%  → admin income wallet
    platform_amount: Decimal = Decimal("0")  # unroutable Core halves only (usually 0)
    core_total: Decimal = Decimal("0")       # 60% (informational)


def _sponsor_of(db: Session, user: User | None) -> User | None:
    if user is None or not user.sponsor_id:
        return None
    return db.query(User).filter_by(id=user.sponsor_id).first()


def _walk_core_half(
    db: Session, start: User | None, buyer_tier: int, mutate_counter: bool
) -> User | None:
    """
    Walk UP the sponsor chain from `start` (inclusive) for ONE Core half,
    combining compression and odd/even into a single continuous pass:
      – skip anyone ineligible (compression: inactive, or tier too low)
      – for each eligible upline, advance their per-tier odd/even counter;
        an ODD count stops the walk here (they keep it); an EVEN count
        continues the walk further up (the amount keeps climbing)
    Returns the first eligible-and-odd upline found, or — if the chain runs
    out while every eligible upline seen was even — the LAST eligible upline
    seen (they keep it: "no eligible upline for an even pass-up -> recipient
    keeps it"). Returns None only if no one in the chain from `start` upward
    is eligible at all.
    """
    current = start
    seen: set[int] = set()  # cycle guard
    last_eligible: User | None = None
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if _is_eligible(db, current, buyer_tier):
            last_eligible = current
            if mutate_counter:
                count = current.increment_core_route_count(buyer_tier)
                db.flush()
            else:
                count = current.get_core_route_count(buyer_tier) + 1  # peek without persisting
            if count % 2 == 1:
                return current  # odd → keep, walk stops here
            # even → keep walking up past this recipient
        current = (
            db.query(User).filter_by(id=current.sponsor_id).first()
            if current.sponsor_id else None
        )
    return last_eligible  # None if nobody eligible was ever found


def compute_pack_split(
    db: Session,
    buyer: User,
    buyer_tier: int,
    price: Decimal,
    *,
    mutate_counter: bool,
) -> PackSplit:
    """
    Compute the upline split for `buyer` purchasing a pack of `buyer_tier` at `price`.
    See module docstring for the rule. Amounts sum exactly to `price`.
    """
    core_total = (price * CORE_RATE).quantize(_TWO, rounding=ROUND_HALF_UP)
    stream_amount = (price * STREAM_RATE).quantize(_TWO, rounding=ROUND_HALF_UP)
    admin_amount = (price * ADMIN_RATE).quantize(_FOUR, rounding=ROUND_HALF_UP)
    # Boost (9%) is the residual so Core + Stream + Boost + admin == price exactly.
    boost_amount = price - core_total - stream_amount - admin_amount

    first_half = (core_total / 2).quantize(_FOUR, rounding=ROUND_HALF_UP)
    second_half = core_total - first_half  # exact sum
    platform_amount = Decimal("0")         # only unroutable Core halves land here

    uplines: list[tuple[User, Decimal]] = []

    # First half: one continuous walk from the buyer's direct sponsor upward.
    first_recipient = _walk_core_half(db, _sponsor_of(db, buyer), buyer_tier, mutate_counter)
    if first_recipient is None:
        # No eligible upline anywhere in the chain → nothing for the second
        # half to reach either — both fold to platform profit.
        platform_amount += first_half + second_half
    else:
        uplines.append((first_recipient, first_half))
        # Second half: the SAME walk, continuing from one level above wherever
        # the first half actually landed (not the first half's original
        # pre-parity candidate).
        second_recipient = _walk_core_half(
            db, _sponsor_of(db, first_recipient), buyer_tier, mutate_counter
        )
        if second_recipient is None:
            # No distinct eligible upline above the first recipient → the sole
            # eligible upline absorbs the second half too, via its OWN fresh,
            # independent odd/even targeting (not a copy of the first result).
            second_recipient = _walk_core_half(db, first_recipient, buyer_tier, mutate_counter)
        uplines.append((second_recipient, second_half))

    return PackSplit(
        uplines=uplines,
        stream_amount=stream_amount,
        boost_amount=boost_amount,
        admin_amount=admin_amount,
        platform_amount=platform_amount,
        core_total=core_total,
    )
