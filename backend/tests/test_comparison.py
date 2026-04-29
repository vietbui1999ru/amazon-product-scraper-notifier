from decimal import Decimal

import pytest

from app.comparison.detector import PriceDropEvent, PricePoint, detect_price_drop, is_meaningful_drop


def _point(price: str, currency: str = "USD") -> PricePoint:
    return PricePoint(price=Decimal(price), currency=currency)


def _detect(old: str, new: str, pct: float = 1.0, absolute: float = 0.0) -> PriceDropEvent | None:
    return detect_price_drop(
        product_id=1,
        product_name="Test",
        product_url="https://example.com",
        previous=_point(old),
        current=_point(new),
        threshold_percent=pct,
        threshold_absolute=absolute,
    )


def test_detect_returns_event_when_drop_exceeds_threshold():
    event = _detect("100.00", "90.00", pct=5.0)
    assert event is not None
    assert event.drop_amount == Decimal("10.00")
    assert event.drop_percent == pytest.approx(10.0)
    assert event.old_price == Decimal("100.00")
    assert event.new_price == Decimal("90.00")


def test_detect_returns_none_when_price_rises():
    event = _detect("90.00", "100.00")
    assert event is None


def test_detect_returns_none_when_price_unchanged():
    event = _detect("100.00", "100.00")
    assert event is None


def test_detect_returns_none_when_drop_below_percent_threshold():
    # 1% drop vs 5% threshold
    event = _detect("100.00", "99.00", pct=5.0, absolute=0.0)
    assert event is None


def test_detect_either_threshold_sufficient_absolute():
    # 2% drop — below 5% pct threshold, but $3 drop exceeds $2 absolute threshold
    event = _detect("100.00", "98.00", pct=5.0, absolute=2.0)
    assert event is not None


def test_detect_either_threshold_sufficient_percent():
    # $0.50 drop — below $1 absolute threshold, but 10% drop exceeds 5% pct threshold
    event = _detect("5.00", "4.50", pct=5.0, absolute=1.0)
    assert event is not None


def test_detect_both_thresholds_disabled_any_drop_triggers():
    event = _detect("100.00", "99.99", pct=0.0, absolute=0.0)
    assert event is not None
    assert event.drop_amount == Decimal("0.01")


def test_detect_event_fields_populated():
    event = detect_price_drop(
        product_id=42,
        product_name="Widget",
        product_url="https://amazon.com/dp/B000000001",
        previous=_point("200.00"),
        current=_point("150.00"),
        threshold_percent=1.0,
    )
    assert event is not None
    assert event.product_id == 42
    assert event.product_name == "Widget"
    assert event.currency == "USD"


# is_meaningful_drop edge cases

def test_is_meaningful_drop_exactly_at_percent_threshold():
    assert is_meaningful_drop(
        drop_amount=Decimal("5"),
        drop_percent=5.0,
        threshold_percent=5.0,
        threshold_absolute=0.0,
    ) is True


def test_is_meaningful_drop_just_below_percent_threshold():
    assert is_meaningful_drop(
        drop_amount=Decimal("4.99"),
        drop_percent=4.99,
        threshold_percent=5.0,
        threshold_absolute=0.0,
    ) is False


def test_is_meaningful_drop_exactly_at_absolute_threshold():
    assert is_meaningful_drop(
        drop_amount=Decimal("2.00"),
        drop_percent=1.0,
        threshold_percent=0.0,
        threshold_absolute=2.0,
    ) is True


def test_is_meaningful_drop_just_below_absolute_threshold():
    assert is_meaningful_drop(
        drop_amount=Decimal("1.99"),
        drop_percent=1.0,
        threshold_percent=0.0,
        threshold_absolute=2.0,
    ) is False


def test_is_meaningful_drop_both_disabled_zero_drop_not_meaningful():
    assert is_meaningful_drop(
        drop_amount=Decimal("0"),
        drop_percent=0.0,
        threshold_percent=0.0,
        threshold_absolute=0.0,
    ) is False
