from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PricePoint:
    price: Decimal
    currency: str


@dataclass(frozen=True)
class PriceDropEvent:
    product_id: int
    product_name: str
    product_url: str
    old_price: Decimal
    new_price: Decimal
    drop_amount: Decimal
    drop_percent: float
    currency: str


def detect_price_drop(
    product_id: int,
    product_name: str,
    product_url: str,
    previous: PricePoint,
    current: PricePoint,
    threshold_percent: float = 1.0,
    threshold_absolute: float = 0.0,
) -> PriceDropEvent | None:
    """
    Returns PriceDropEvent if current < previous AND drop exceeds at least one threshold.
    Returns None if no meaningful drop.
    threshold_percent: minimum % drop required (0 = disabled)
    threshold_absolute: minimum absolute drop required (0 = disabled)
    Logic: drop must exceed EITHER threshold (not both). If both are 0, any drop triggers.
    """
    if current.price >= previous.price:
        return None

    drop_amount = previous.price - current.price
    drop_percent = float(drop_amount / previous.price * 100)

    if not is_meaningful_drop(drop_amount, drop_percent, threshold_percent, threshold_absolute):
        return None

    return PriceDropEvent(
        product_id=product_id,
        product_name=product_name,
        product_url=product_url,
        old_price=previous.price,
        new_price=current.price,
        drop_amount=drop_amount,
        drop_percent=drop_percent,
        currency=current.currency,
    )


def is_meaningful_drop(
    drop_amount: Decimal,
    drop_percent: float,
    threshold_percent: float,
    threshold_absolute: float,
) -> bool:
    """
    True if drop meets at least one enabled threshold.
    A threshold is "disabled" if it is <= 0.
    If both disabled, any positive drop is meaningful.
    """
    both_disabled = threshold_percent <= 0 and threshold_absolute <= 0
    if both_disabled:
        return drop_amount > Decimal(0)

    if threshold_percent > 0 and drop_percent >= threshold_percent:
        return True
    if threshold_absolute > 0 and drop_amount >= Decimal(str(threshold_absolute)):
        return True

    return False
