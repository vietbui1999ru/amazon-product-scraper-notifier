import pytest
from unittest.mock import AsyncMock


@pytest.fixture(autouse=True)
def mock_cache(monkeypatch):
    """Prevent Redis connections in all tests by mocking cache functions in routes."""
    monkeypatch.setattr("app.api.routes.cache_product", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.routes.get_cached_products_list", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.routes.set_cached_products_list", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.routes.invalidate_products_list", AsyncMock(return_value=None))
    monkeypatch.setattr("app.api.routes.get_product_id_by_url", AsyncMock(return_value=None))
