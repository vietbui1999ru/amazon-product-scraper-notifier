"""Mutable runtime configuration overlay.

Initialized from Settings (config.yaml + env) at first access.
Changes via PATCH /api/config take effect on the next scheduler tick
without a restart. scraper_headless and proxies still require restart
(Playwright browser is launched once in run_scheduler).
"""
from dataclasses import asdict, dataclass


@dataclass
class RuntimeConfig:
    check_interval_seconds: int
    notification_method: str | list[str]
    price_drop_threshold_percent: float
    price_drop_threshold_absolute: float
    scraper_headless: bool
    scraper_timeout_ms: int
    scraper_min_delay: float
    scraper_max_delay: float


_runtime_config: RuntimeConfig | None = None


def get_runtime_config() -> RuntimeConfig:
    global _runtime_config
    if _runtime_config is None:
        from app.config import get_settings
        s = get_settings()
        _runtime_config = RuntimeConfig(
            check_interval_seconds=s.check_interval_seconds,
            notification_method=s.notification_method,
            price_drop_threshold_percent=s.price_drop_threshold_percent,
            price_drop_threshold_absolute=s.price_drop_threshold_absolute,
            scraper_headless=s.scraper_headless,
            scraper_timeout_ms=s.scraper_timeout_ms,
            scraper_min_delay=s.scraper_min_delay,
            scraper_max_delay=s.scraper_max_delay,
        )
    return _runtime_config


def runtime_config_as_dict() -> dict:
    return asdict(get_runtime_config())
