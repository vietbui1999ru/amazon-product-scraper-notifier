---
title: "Scraper"
description: "AmazonScraper architecture, price selector cascade, stealth configuration, search function, ScrapeResult, and error types."
tags: [backend, scraper, playwright, amazon]
updated: 2026-04-28
---

# Scraper

`app/scraper/`

---

## ScrapeResult

`app/scraper/base.py`

Frozen dataclass returned by every `scrape()` call.

| Field | Type | Description |
|---|---|---|
| `url` | `str` | The URL that was scraped |
| `price` | `Decimal \| None` | Extracted price, or `None` on failure |
| `currency` | `str` | Always `"USD"` for Amazon US |
| `success` | `bool` | `True` only when price was extracted |
| `error_message` | `str \| None` | Set when `success=False` |
| `selector_used` | `str \| None` | Which CSS selector matched the price |

`scrape()` must not raise — all errors are returned as `ScrapeResult(success=False, ...)`.

---

## AbstractScraper

`app/scraper/base.py`

```python
class AbstractScraper(ABC):
    @abstractmethod
    async def scrape(self, url: str) -> ScrapeResult: ...

    @abstractmethod
    def supports(self, url: str) -> bool: ...
```

`supports(url)` returns `True` if this scraper handles the given URL. For `AmazonScraper`: any URL containing `"amazon."`.

---

## AmazonScraper

`app/scraper/amazon.py`

Playwright-based scraper with stealth fingerprint evasion. Manages a single shared Chromium browser instance.

### Constructor

```python
AmazonScraper(
    headless: bool = True,
    timeout_ms: int = 30000,
    proxies: list[str] | None = None,
    min_delay: float = 1.0,
    max_delay: float = 5.0,
)
```

| Param | Default | Notes |
|---|---|---|
| `headless` | `True` | Launch browser without a visible window |
| `timeout_ms` | `30000` | Page navigation timeout in milliseconds |
| `proxies` | `[]` | List of proxy server URLs; one is chosen at random per request |
| `min_delay` | `1.0` | Minimum random delay between requests (seconds) |
| `max_delay` | `5.0` | Maximum random delay between requests (seconds) |

A semaphore (`asyncio.Semaphore(1)`) ensures at most one in-flight request at a time.

### Usage

Use as an async context manager:

```python
async with AmazonScraper(proxies=settings.proxies) as scraper:
    result = await scraper.scrape(url)
```

Or manage lifecycle manually with `await scraper.start()` / `await scraper.stop()`.

### Per-Request Context

Each call to `scrape()` creates a new Playwright `BrowserContext` (isolated cookies, storage) and closes it after the page finishes. Context options:

- Viewport: 1920×1080
- Locale: `en-US`
- Timezone: `America/New_York`
- `Accept-Language: en-US,en;q=0.9` header

A user-agent and platform pair is chosen at random from a pool of 8 (Chrome macOS/Windows, Firefox, Edge, Safari macOS, Chrome Linux). The chosen UA and platform are passed to `playwright-stealth` so the reported `navigator.userAgent` and `navigator.platform` are consistent.

### Stealth

Uses `playwright-stealth` v2 API:

```python
await Stealth(
    navigator_user_agent_override=ua,
    navigator_platform_override=platform,
).apply_stealth_async(page)
```

> **Note**: `playwright-stealth` v2 changed the API from v1. The v1 call was `stealth_async(page)` (a module-level function). The v2 API requires instantiating `Stealth(...)` and calling `.apply_stealth_async(page)`. If you see `AttributeError` on `stealth_async`, check that you are on v2.

### Price Selector Cascade

Selectors tried in order. First match that parses to a valid `Decimal` wins:

| Priority | Selector |
|---|---|
| 1 | `#priceblock_ourprice` |
| 2 | `#priceblock_dealprice` |
| 3 | `.a-price .a-offscreen` |
| 4 | `#apex_offerDisplay_desktop .a-price .a-offscreen` |
| 5 | `span[data-a-color='price'] .a-offscreen` |

Price text is cleaned with `replace("$", "").replace(",", "").strip()` before parsing.

If no selector matches, raises `ParseError` internally. This is caught by `_scrape_with_context` and returned as `ScrapeResult(success=False)`.

### Bot Detection

After navigation, the page title is checked for the following strings:

- `"Robot Check"`
- `"Sorry!"`
- `"Enter the characters you see below"`

If any match, `BlockedError` is raised and caught, returning `ScrapeResult(success=False)`.

---

## Error Types

`app/scraper/errors.py`

| Class | Parent | Description |
|---|---|---|
| `ScraperError` | `Exception` | Base class for all scraper errors |
| `NetworkError` | `ScraperError` | Network-level failure (timeout, DNS, connection refused) |
| `ParseError` | `ScraperError` | Page loaded but no price selector matched. Fields: `url`, `selector_tried: list[str]` |
| `BlockedError` | `ScraperError` | Bot detection page. Fields: `url`, `status_code: int \| None` |
| `RateLimitError` | `ScraperError` | Too many requests — reserved for future backoff logic |

All errors are caught inside `_scrape_with_context` and converted to `ScrapeResult(success=False, error_message=str(exc))`. They do not propagate to callers.

---

## Search

`app/scraper/search.py`

```python
async def search_amazon(query: str, scraper: AmazonScraper) -> list[SearchResult]
```

Navigates to `https://www.amazon.com/s?k={url-encoded-query}` using the same Playwright browser as the scraper (reuses `scraper._browser`, opens a new context). Returns up to 8 results.

**SearchResult fields**

| Field | Type | Description |
|---|---|---|
| `asin` | `str` | Amazon ASIN |
| `name` | `str` | Product title |
| `url` | `str` | `https://www.amazon.com/dp/{asin}` |
| `price` | `float \| None` | From `.a-price .a-offscreen`; `None` if not rendered |
| `image_url` | `str \| None` | From `img.s-image`; `None` if missing |
| `rating` | `str \| None` | From `span[aria-label*="out of 5"]`; `None` if missing |

Results are filtered to items with a non-empty ASIN and non-empty title. The context is closed after the search regardless of success or error.

Requires `scraper.start()` to have been called (or the scraper to be used as a context manager) — asserts `scraper._browser is not None`.
