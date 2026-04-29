import asyncio
import random
from decimal import Decimal, InvalidOperation

import structlog
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
from playwright_stealth import Stealth

from app.scraper.base import AbstractScraper, ScrapeResult
from app.scraper.errors import BlockedError, ParseError

log = structlog.get_logger(__name__)

# (user_agent, navigator_platform) pairs — matched so stealth fingerprint is consistent
_USER_AGENTS: list[tuple[str, str]] = [
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "MacIntel"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36", "MacIntel"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "Win32"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36", "Win32"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0", "Win32"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15", "MacIntel"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0", "Win32"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "Linux x86_64"),
]

_PRICE_SELECTORS: list[str] = [
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    ".a-price .a-offscreen",
    "#apex_offerDisplay_desktop .a-price .a-offscreen",
    "span[data-a-color='price'] .a-offscreen",
]

_BLOCK_SIGNALS = ("Robot Check", "Sorry!", "Enter the characters you see below")


def _parse_price(raw: str) -> Decimal:
    cleaned = raw.replace("$", "").replace(",", "").strip()
    return Decimal(cleaned)


def _pick_ua() -> tuple[str, str]:
    return random.choice(_USER_AGENTS)


def _pick_proxy(proxies: list[str]) -> str | None:
    return random.choice(proxies) if proxies else None


class AmazonScraper(AbstractScraper):
    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 30000,
        proxies: list[str] | None = None,
        min_delay: float = 1.0,
        max_delay: float = 5.0,
    ) -> None:
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._proxies = proxies or []
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._semaphore = asyncio.Semaphore(1)  # 1 req/sec rate limit
        self._browser: Browser | None = None
        self._playwright: Playwright | None = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        log.info("amazon_scraper.started", headless=self._headless, proxies=len(self._proxies))

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        log.info("amazon_scraper.stopped")

    async def __aenter__(self) -> "AmazonScraper":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    def supports(self, url: str) -> bool:
        return "amazon." in url

    async def scrape(self, url: str) -> ScrapeResult:
        async with self._semaphore:
            delay = random.uniform(self._min_delay, self._max_delay)
            await asyncio.sleep(delay)
            return await self._scrape_with_context(url)

    async def _scrape_with_context(self, url: str) -> ScrapeResult:
        ua, platform = _pick_ua()
        proxy = _pick_proxy(self._proxies)
        context: BrowserContext | None = None
        try:
            assert self._browser is not None, "Call start() before scrape()"
            context = await self._browser.new_context(
                proxy={"server": proxy} if proxy else None,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/New_York",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            page = await context.new_page()
            await Stealth(
                navigator_user_agent_override=ua,
                navigator_platform_override=platform,
            ).apply_stealth_async(page)
            await page.set_extra_http_headers({"User-Agent": ua})

            log.debug("amazon_scraper.navigating", url=url, proxy=proxy, ua=ua[:40])
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)

            title = await page.title()
            if any(signal in title for signal in _BLOCK_SIGNALS):
                raise BlockedError(f"Blocked: title={title!r}", url=url)

            price, selector = await self._extract_price(page, url)
            log.info("amazon_scraper.price_found", url=url, selector=selector, price=str(price))
            return ScrapeResult(url=url, price=price, currency="USD", success=True, selector_used=selector)

        except Exception as exc:
            log.warning("amazon_scraper.scrape_failed", url=url, error=str(exc))
            return ScrapeResult(url=url, price=None, currency="USD", success=False, error_message=str(exc))
        finally:
            if context:
                await context.close()

    async def _extract_price(self, page, url: str) -> tuple[Decimal, str]:
        for selector in _PRICE_SELECTORS:
            try:
                element = await page.query_selector(selector)
                if element is None:
                    continue
                raw = await element.inner_text()
                price = _parse_price(raw)
                log.debug("amazon_scraper.selector_matched", selector=selector, raw=raw)
                return price, selector
            except (InvalidOperation, ValueError):
                continue
        raise ParseError("No price selector matched", url=url, selector_tried=_PRICE_SELECTORS)
