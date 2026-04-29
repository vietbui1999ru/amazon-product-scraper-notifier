import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import Base, get_db
from app.storage.repository import ProductRepository


@pytest.fixture
async def client():
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # app_lifespan=False prevents the scheduler from starting during tests
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, engine

    app.dependency_overrides.clear()
    await engine.dispose()


async def test_list_products_empty(client):
    ac, _ = client
    response = await ac.get("/api/products")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_products_with_data(client):
    ac, engine = client
    async with AsyncSession(engine, expire_on_commit=False) as session:
        repo = ProductRepository(session)
        await repo.get_or_create_product(
            url="https://www.amazon.com/dp/B001234567",
            name="Test Widget",
        )  # return value (product, created) intentionally ignored here
        await session.commit()

    response = await ac.get("/api/products")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Widget"
    assert data[0]["url"] == "https://www.amazon.com/dp/B001234567"
    assert data[0]["asin"] == "B001234567"
    assert "id" in data[0]
    assert "created_at" in data[0]
    assert data[0]["latest_price"] is None


async def test_product_history_not_found(client):
    ac, _ = client
    response = await ac.get("/api/products/9999/history")
    assert response.status_code == 404


async def test_product_history_returns_checks(client):
    ac, engine = client
    async with AsyncSession(engine, expire_on_commit=False) as session:
        repo = ProductRepository(session)
        product, _ = await repo.get_or_create_product(
            url="https://www.amazon.com/dp/B009876543",
            name="Another Widget",
        )
        await repo.record_price_check(
            product=product,
            price=49.99,
            currency="USD",
            success=True,
        )
        await repo.record_price_check(
            product=product,
            price=44.99,
            currency="USD",
            success=True,
        )
        await session.commit()
        product_id = product.id

    response = await ac.get(f"/api/products/{product_id}/history")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 2
    assert all(item["product_id"] == product_id for item in data)
    assert all("price" in item for item in data)
    assert all("scraped_at" in item for item in data)


async def test_product_history_limit(client):
    ac, engine = client
    async with AsyncSession(engine, expire_on_commit=False) as session:
        repo = ProductRepository(session)
        product, _ = await repo.get_or_create_product(
            url="https://www.amazon.com/dp/B00LIMIT999",
            name="Limit Test Widget",
        )
        for i in range(5):
            await repo.record_price_check(
                product=product,
                price=float(10 + i),
                currency="USD",
                success=True,
            )
        await session.commit()
        product_id = product.id

    response = await ac.get(f"/api/products/{product_id}/history?limit=2")
    assert response.status_code == 200
    assert len(response.json()) == 2
