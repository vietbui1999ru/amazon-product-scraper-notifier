import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import Settings, get_settings
from app.database import Base, get_db

API_KEY = "test-secret-key"
WRONG_KEY = "wrong-key"

TEST_PRODUCT = {
    "url": "https://www.amazon.com/dp/B001234567",
    "name": "Test Widget",
}


def _make_settings(api_key: str) -> Settings:
    return Settings(database_url="sqlite+aiosqlite:///:memory:", api_key=api_key)


@pytest.fixture
async def auth_client():
    """App with API key auth enabled (key = API_KEY)."""
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_db():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: _make_settings(API_KEY)

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
async def open_client():
    """App with auth disabled (api_key is empty string)."""
    from app.main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_db():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: _make_settings("")

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


# --- POST /api/products ---

async def test_add_product_missing_key_returns_403(auth_client):
    response = await auth_client.post("/api/products", json=TEST_PRODUCT)
    assert response.status_code == 403


async def test_add_product_wrong_key_returns_403(auth_client):
    response = await auth_client.post(
        "/api/products", json=TEST_PRODUCT, headers={"X-API-Key": WRONG_KEY}
    )
    assert response.status_code == 403


async def test_add_product_valid_key_succeeds(auth_client):
    response = await auth_client.post(
        "/api/products", json=TEST_PRODUCT, headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 201


# --- POST /api/products/force-check ---

async def test_force_check_missing_key_returns_403(auth_client):
    response = await auth_client.post("/api/products/force-check", json={"all": True})
    assert response.status_code == 403


async def test_force_check_valid_key_succeeds(auth_client):
    response = await auth_client.post(
        "/api/products/force-check", json={"all": True}, headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 202


# --- POST /api/scheduler/prices ---

async def test_schedule_price_missing_key_returns_403(auth_client):
    response = await auth_client.post(
        "/api/scheduler/prices",
        json={"product_id": 1, "price": 29.99, "minutes": 1},
    )
    assert response.status_code == 403


# --- DELETE /api/scheduler/prices/{id} ---

async def test_cancel_scheduled_price_missing_key_returns_403(auth_client):
    response = await auth_client.delete("/api/scheduler/prices/1")
    assert response.status_code == 403


# --- PATCH /api/products/{id}/image ---

async def test_patch_image_missing_key_returns_403(auth_client):
    response = await auth_client.patch(
        "/api/products/1/image", json={"image_url": "https://example.com/img.jpg"}
    )
    assert response.status_code == 403


# --- PATCH /api/config ---

async def test_patch_config_missing_key_returns_403(auth_client):
    response = await auth_client.patch(
        "/api/config", json={"check_interval_seconds": 60}
    )
    assert response.status_code == 403


# --- POST /api/demo/drop ---

async def test_demo_drop_missing_key_returns_403(auth_client):
    response = await auth_client.post(
        "/api/demo/drop",
        json={"url": "https://www.amazon.com/dp/B001234567", "price": 19.99},
    )
    assert response.status_code == 403


# --- Read endpoints stay open ---

async def test_list_products_no_auth_required(auth_client):
    response = await auth_client.get("/api/products")
    assert response.status_code == 200


async def test_health_no_auth_required(auth_client):
    response = await auth_client.get("/api/health")
    assert response.status_code == 200


async def test_get_config_no_auth_required(auth_client):
    response = await auth_client.get("/api/config")
    assert response.status_code == 200


# --- Auth disabled when api_key is empty ---

async def test_add_product_no_key_needed_when_auth_disabled(open_client):
    response = await open_client.post("/api/products", json=TEST_PRODUCT)
    assert response.status_code in (200, 201)


async def test_force_check_no_key_needed_when_auth_disabled(open_client):
    response = await open_client.post(
        "/api/products/force-check", json={"all": True}
    )
    assert response.status_code == 202


# --- Happy-path: valid key reaches handler, not blocked at auth ---

async def test_cancel_scheduled_price_valid_key_returns_404(auth_client):
    response = await auth_client.delete(
        "/api/scheduler/prices/999", headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 404


async def test_patch_image_valid_key_returns_404(auth_client):
    response = await auth_client.patch(
        "/api/products/999/image",
        json={"image_url": "https://example.com/img.jpg"},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 404


async def test_patch_config_valid_key_returns_200(auth_client):
    response = await auth_client.patch(
        "/api/config",
        json={"check_interval_seconds": 60},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200


async def test_demo_drop_valid_key_returns_404(auth_client):
    response = await auth_client.post(
        "/api/demo/drop",
        json={"url": "https://www.amazon.com/dp/B001234567", "price": 19.99},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 404


async def test_schedule_price_valid_key_returns_404(auth_client):
    response = await auth_client.post(
        "/api/scheduler/prices",
        json={"product_id": 999, "price": 29.99, "minutes": 1},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 404
