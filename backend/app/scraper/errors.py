class ScraperError(Exception):
    """Base class for all scraper errors."""


class NetworkError(ScraperError):
    """Network-level failure (timeout, connection refused, DNS)."""


class ParseError(ScraperError):
    """Page loaded but price could not be extracted."""

    def __init__(self, message: str, url: str, selector_tried: list[str]) -> None:
        super().__init__(message)
        self.url = url
        self.selector_tried = selector_tried


class BlockedError(ScraperError):
    """Request was blocked by anti-bot detection."""

    def __init__(self, message: str, url: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class RateLimitError(ScraperError):
    """Too many requests — back off."""
