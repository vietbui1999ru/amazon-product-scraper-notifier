"""Tests for the Amazon scraper layer.

All Playwright I/O is mocked — no real browser is launched.
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.scraper.amazon import AmazonScraper
from app.scraper.errors import ParseError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page(title: str = "Amazon Product", selector_text: str | None = None) -> MagicMock:
    """Return a mock Playwright Page.

    selector_text: if given, query_selector returns an element whose inner_text()
                   yields this value; if None, query_selector returns None.
    """
    page = MagicMock()
    page.is_closed = MagicMock(return_value=False)
    page.title = AsyncMock(return_value=title)
    page.set_extra_http_headers = AsyncMock()
    page.goto = AsyncMock()
    page.close = AsyncMock()

    if selector_text is not None:
        element = MagicMock()
        element.inner_text = AsyncMock(return_value=selector_text)
        page.query_selector = AsyncMock(return_value=element)
    else:
        page.query_selector = AsyncMock(return_value=None)

    return page


def _make_scraper_with_page(page: MagicMock) -> AmazonScraper:
    """Return an AmazonScraper whose browser is pre-wired via context → page."""
    scraper = AmazonScraper()
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    scraper._browser = browser
    return scraper


# ---------------------------------------------------------------------------
# 1. supports()
# ---------------------------------------------------------------------------

def test_supports_amazon_url():
    scraper = AmazonScraper()
    assert scraper.supports("https://www.amazon.com/dp/B08N5WRWNW") is True


def test_supports_rejects_non_amazon():
    scraper = AmazonScraper()
    assert scraper.supports("https://www.ebay.com/itm/123456") is False


# ---------------------------------------------------------------------------
# 2. Happy path — price extracted via .a-price .a-offscreen
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_returns_price_on_success():
    page = _make_page(title="Amazon Product", selector_text="$29.99")
    scraper = _make_scraper_with_page(page)

    with patch("app.scraper.amazon.Stealth") as mock_stealth_cls, \
         patch("app.scraper.amazon.asyncio.sleep", new_callable=AsyncMock):
        mock_stealth_cls.return_value.apply_stealth_async = AsyncMock()
        result = await scraper.scrape("https://www.amazon.com/dp/B000001")

    assert result.success is True
    assert result.price == Decimal("29.99")
    assert result.currency == "USD"
    assert result.selector_used is not None


# ---------------------------------------------------------------------------
# 3. Block detection — "Robot Check" in title
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_returns_failure_on_robot_check():
    page = _make_page(title="Robot Check")
    scraper = _make_scraper_with_page(page)

    with patch("app.scraper.amazon.Stealth") as mock_stealth_cls, \
         patch("app.scraper.amazon.asyncio.sleep", new_callable=AsyncMock):
        mock_stealth_cls.return_value.apply_stealth_async = AsyncMock()
        result = await scraper.scrape("https://www.amazon.com/dp/B000002")

    assert result.success is False
    assert result.error_message is not None
    assert "blocked" in result.error_message.lower() or "Robot Check" in result.error_message


# ---------------------------------------------------------------------------
# 4. No selector matches — all return None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_returns_failure_when_no_selector_matches():
    page = _make_page(title="Amazon Product", selector_text=None)
    scraper = _make_scraper_with_page(page)

    with patch("app.scraper.amazon.Stealth") as mock_stealth_cls, \
         patch("app.scraper.amazon.asyncio.sleep", new_callable=AsyncMock):
        mock_stealth_cls.return_value.apply_stealth_async = AsyncMock()
        result = await scraper.scrape("https://www.amazon.com/dp/B000003")

    assert result.success is False
    assert result.price is None


# ---------------------------------------------------------------------------
# 5. Price with commas parses correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_parses_price_with_commas():
    page = _make_page(title="Amazon Product", selector_text="$1,299.00")
    scraper = _make_scraper_with_page(page)

    with patch("app.scraper.amazon.Stealth") as mock_stealth_cls, \
         patch("app.scraper.amazon.asyncio.sleep", new_callable=AsyncMock):
        mock_stealth_cls.return_value.apply_stealth_async = AsyncMock()
        result = await scraper.scrape("https://www.amazon.com/dp/B000004")

    assert result.success is True
    assert result.price == Decimal("1299.00")


# ---------------------------------------------------------------------------
# 6. ParseError stores selector_tried list
# ---------------------------------------------------------------------------

def test_parse_error_stores_selector_tried():
    selectors = ["#priceblock_ourprice", ".a-price .a-offscreen"]
    err = ParseError("could not parse", url="https://www.amazon.com/dp/B000005", selector_tried=selectors)

    assert err.url == "https://www.amazon.com/dp/B000005"
    assert err.selector_tried == selectors
    assert str(err) == "could not parse"
