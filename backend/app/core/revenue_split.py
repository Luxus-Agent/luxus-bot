from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass
class RevenueSplit:
    core: Decimal    # 60% — Core Agent
    stream: Decimal  # 30% — Stream Agent
    boost: Decimal   # 10% — Boost Agent


def split_purchase(price: Decimal) -> RevenueSplit:
    """
    Split purchase amount into the three revenue pools.
    Stream + boost are rounded first; core takes the remainder
    so the three values always sum exactly to price.
    """
    two_places = Decimal("0.01")
    stream = (price * Decimal("0.30")).quantize(two_places, rounding=ROUND_HALF_UP)
    boost  = (price * Decimal("0.10")).quantize(two_places, rounding=ROUND_HALF_UP)
    core   = price - stream - boost
    return RevenueSplit(core=core, stream=stream, boost=boost)
