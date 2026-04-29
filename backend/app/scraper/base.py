from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ScrapeResult:
    url: str
    price: Decimal | None
    currency: str
    success: bool
    error_message: str | None = None
    selector_used: str | None = None  # which CSS selector fired


class AbstractScraper(ABC):
    @abstractmethod
    async def scrape(self, url: str) -> ScrapeResult:
        """Scrape price from URL. Must not raise — return ScrapeResult with success=False on error."""
        ...

    @abstractmethod
    def supports(self, url: str) -> bool:
        """Return True if this scraper handles the given URL."""
        ...
