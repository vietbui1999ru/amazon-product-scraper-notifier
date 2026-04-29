import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base
from app.storage.repository import ProductRepository


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s
    await engine.dispose()


async def test_get_or_create_product_creates_new(session):
    repo = ProductRepository(session)
    product, created = await repo.get_or_create_product(
        url="https://amazon.com/dp/B08N5WRWNW", name="Test Product"
    )
    assert created is True
    assert product.id is not None
    assert product.name == "Test Product"
    assert product.url == "https://amazon.com/dp/B08N5WRWNW"


async def test_get_or_create_product_idempotent(session):
    repo = ProductRepository(session)
    url = "https://amazon.com/dp/B08N5WRWNW"
    first, created_first = await repo.get_or_create_product(url=url, name="Test Product")
    second, created_second = await repo.get_or_create_product(url=url, name="Test Product")
    assert first.id == second.id
    assert created_first is True
    assert created_second is False


async def test_get_or_create_product_extracts_asin(session):
    repo = ProductRepository(session)
    product, _ = await repo.get_or_create_product(
        url="https://www.amazon.com/some-title/dp/B08N5WRWNW/ref=sr_1_1",
        name="ASIN Test",
    )
    assert product.asin == "B08N5WRWNW"


async def test_get_or_create_product_no_asin(session):
    repo = ProductRepository(session)
    product, _ = await repo.get_or_create_product(
        url="https://example.com/product/123", name="No ASIN"
    )
    assert product.asin is None


async def test_record_price_check_success(session):
    repo = ProductRepository(session)
    product, _ = await repo.get_or_create_product(
        url="https://amazon.com/dp/B000000001", name="Widget"
    )
    check = await repo.record_price_check(
        product=product, price=29.99, currency="USD", success=True
    )
    assert check.id is not None
    assert float(check.price) == pytest.approx(29.99)
    assert check.currency == "USD"
    assert check.scrape_success is True
    assert check.error_message is None


async def test_record_price_check_failure(session):
    repo = ProductRepository(session)
    product, _ = await repo.get_or_create_product(
        url="https://amazon.com/dp/B000000002", name="Widget 2"
    )
    check = await repo.record_price_check(
        product=product,
        price=None,
        currency="USD",
        success=False,
        error_message="Scrape timeout",
    )
    assert check.scrape_success is False
    assert check.price is None
    assert check.error_message == "Scrape timeout"


async def test_get_last_successful_price_returns_most_recent(session):
    repo = ProductRepository(session)
    product, _ = await repo.get_or_create_product(
        url="https://amazon.com/dp/B000000003", name="Widget 3"
    )
    await repo.record_price_check(product=product, price=50.00, currency="USD", success=True)
    await repo.record_price_check(product=product, price=None, currency="USD", success=False)
    last = await repo.record_price_check(
        product=product, price=45.00, currency="USD", success=True
    )

    result = await repo.get_last_successful_price(product.id)
    assert result is not None
    assert result.id == last.id
    assert float(result.price) == pytest.approx(45.00)


async def test_get_last_successful_price_ignores_failures(session):
    repo = ProductRepository(session)
    product, _ = await repo.get_or_create_product(
        url="https://amazon.com/dp/B000000004", name="Widget 4"
    )
    success = await repo.record_price_check(
        product=product, price=30.00, currency="USD", success=True
    )
    await repo.record_price_check(
        product=product, price=None, currency="USD", success=False, error_message="err"
    )

    result = await repo.get_last_successful_price(product.id)
    assert result is not None
    assert result.id == success.id


async def test_get_price_history_ordered_and_limited(session):
    repo = ProductRepository(session)
    product, _ = await repo.get_or_create_product(
        url="https://amazon.com/dp/B000000005", name="Widget 5"
    )
    for price in [10.0, 20.0, 30.0, 40.0, 50.0]:
        await repo.record_price_check(
            product=product, price=price, currency="USD", success=True
        )

    history = await repo.get_price_history(product.id, limit=3)
    assert len(history) == 3
    # most recent first
    prices = [float(c.price) for c in history]
    assert prices == sorted(prices, reverse=True)


async def test_mark_notified(session):
    repo = ProductRepository(session)
    product, _ = await repo.get_or_create_product(
        url="https://amazon.com/dp/B000000006", name="Widget 6"
    )
    check = await repo.record_price_check(
        product=product, price=99.99, currency="USD", success=True
    )
    assert check.notified is False

    await repo.mark_notified(check.id)

    # re-fetch to confirm persistence within session
    from sqlalchemy import select
    from app.models import PriceCheck
    result = await session.execute(select(PriceCheck).where(PriceCheck.id == check.id))
    updated = result.scalar_one()
    assert updated.notified is True
