from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass
class RevenueSplit:
    proactive: Decimal    # 60%
    proportion: Decimal   # 30%
    speculation: Decimal  # 10%


def split_purchase(price: Decimal) -> RevenueSplit:
    """
    Split purchase amount into the three revenue pools.
    Proportion + speculation are rounded first; proactive takes the remainder
    so the three values always sum exactly to price.
    """
    two_places = Decimal("0.01")
    proportion = (price * Decimal("0.30")).quantize(two_places, rounding=ROUND_HALF_UP)
    speculation = (price * Decimal("0.10")).quantize(two_places, rounding=ROUND_HALF_UP)
    proactive = price - proportion - speculation
    return RevenueSplit(proactive=proactive, proportion=proportion, speculation=speculation)
