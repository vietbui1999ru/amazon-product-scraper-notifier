import urllib.parse
from dataclasses import dataclass

import structlog

from app.scraper.amazon import AmazonScraper, _pick_proxy, _pick_ua
from playwright_stealth import Stealth

log = structlog.get_logger(__name__)

_SEARCH_URL = "https://www.amazon.com/s?k={query}"
_MAX_RESULTS = 8


@dataclass
class SearchResult:
    asin: str
    name: str
    url: str
    price: float | None
    image_url: str | None
    rating: str | None


async def search_amazon(query: str, scraper: AmazonScraper) -> list[SearchResult]:
    ua, platform = _pick_ua()
    proxy = _pick_proxy(scraper._proxies)
    context = None

    try:
        assert scraper._browser is not None, "Call start() before search_amazon()"
        context = await scraper._browser.new_context(
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

        url = _SEARCH_URL.format(query=urllib.parse.quote_plus(query))
        log.debug("search_amazon.navigating", url=url)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        containers = await page.query_selector_all('[data-component-type="s-search-result"]')
        log.info("search_amazon.results_found", count=len(containers), query=query)

        results: list[SearchResult] = []
        for container in containers[:_MAX_RESULTS]:
            asin = await container.get_attribute("data-asin") or ""
            if not asin:
                continue

            name_el = await container.query_selector("h2 a span")
            name = (await name_el.inner_text()).strip() if name_el else ""
            if not name:
                continue

            price: float | None = None
            price_el = await container.query_selector(".a-price .a-offscreen")
            if price_el:
                raw = (await price_el.inner_text()).replace("$", "").replace(",", "").strip()
                try:
                    price = float(raw)
                except ValueError:
                    pass

            image_url: str | None = None
            img_el = await container.query_selector("img.s-image")
            if img_el:
                image_url = await img_el.get_attribute("src")

            rating: str | None = None
            rating_el = await container.query_selector('span[aria-label*="out of 5"]')
            if rating_el:
                rating = await rating_el.get_attribute("aria-label")

            results.append(
                SearchResult(
                    asin=asin,
                    name=name,
                    url=f"https://www.amazon.com/dp/{asin}",
                    price=price,
                    image_url=image_url,
                    rating=rating,
                )
            )

        return results

    finally:
        if context:
            await context.close()
