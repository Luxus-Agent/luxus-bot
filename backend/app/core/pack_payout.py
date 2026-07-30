"""
Pack-purchase payout split for the on-chain (BEP-20 USDT) rail.

This computes the full 60/30/10 split for a single pack purchase (per the client
"Classification of Agents" spec):

  Core Agent  — 60% of the price, routed to uplines as two equal 30% halves:
      – first  half → first  ELIGIBLE upline
      – second half → next eligible upline above the first, or the first
        upline again if there is no distinct second one (e.g. the buyer's
        direct sponsor is Admin, who has no sponsor of their own) — the sole
        eligible upline absorbs both halves rather than forfeiting the second
        to platform profit
    "Eligible" = compression: the upline is active AND their highest active
    purchased tier >= the buyer's tier (reuses proactive._is_eligible — Admin is
    exempt from the tier-ownership half of that check). Ineligible or missing
    uplines are skipped via compression. Odd/even routing per eligible recipient
    (User.core_route_count_tierN, keyed by the BUYER's tier — a tier-1 purchase
    and a tier-2 purchase targeting the same recipient alternate independently):
    odd → keep, even → pass up to the next eligible upline. A half only folds
    into the platform amount (company profit) when there is no eligible upline
    at all (buyer has no sponsor, or the whole chain above them is
    ineligible/frozen).

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

from app.core.proactive import _is_eligible, _next_eligible_upline  # noqa: PLC2701
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


def _resolve_recipient(
    db: Session, primary: User | None, buyer_tier: int, mutate_counter: bool
) -> User | None:
    """
    Apply the Core odd/even rule to one eligible primary recipient.
    Odd count → primary keeps; even → pass up to the next eligible upline.
    Returns the final beneficiary, or None if there is no eligible recipient.
    """
    if primary is None:
        return None

    if mutate_counter:
        count = primary.increment_core_route_count(buyer_tier)
        db.flush()
    else:
        count = primary.get_core_route_count(buyer_tier) + 1  # peek without persisting

    if count % 2 == 1:
        return primary  # odd → keep

    # even → pass up to the next ELIGIBLE upline above the primary (compressed)
    upline = _next_eligible_upline(db, _sponsor_of(db, primary), buyer_tier)
    return upline if upline is not None else primary  # none above → primary keeps


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

    # First eligible upline: compress from the buyer's direct sponsor upward.
    first = _next_eligible_upline(db, _sponsor_of(db, buyer), buyer_tier)
    # Second eligible upline: compress from the first eligible's sponsor upward.
    second = (
        _next_eligible_upline(db, _sponsor_of(db, first), buyer_tier)
        if first is not None else None
    )
    # No DISTINCT second eligible upline above the first (e.g. the buyer's direct
    # sponsor is Admin, who has no sponsor of their own) → the sole eligible
    # upline absorbs both halves instead of forfeiting the second to platform
    # profit. Runs through its own independent odd/even resolution below, same
    # as any other targeting.
    if first is not None and second is None:
        second = first

    uplines: list[tuple[User, Decimal]] = []
    for primary, amount in ((first, first_half), (second, second_half)):
        recipient = _resolve_recipient(db, primary, buyer_tier, mutate_counter)
        if recipient is None:
            platform_amount += amount   # no eligible upline → platform (per Core rule)
        else:
            uplines.append((recipient, amount))

    return PackSplit(
        uplines=uplines,
        stream_amount=stream_amount,
        boost_amount=boost_amount,
        admin_amount=admin_amount,
        platform_amount=platform_amount,
        core_total=core_total,
    )
