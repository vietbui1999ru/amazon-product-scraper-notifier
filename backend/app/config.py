import functools
import os
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProductConfig(BaseModel):
    url: str
    name: str


class SchedulerConfig(BaseModel):
    check_interval_seconds: int = 300


class NotificationConfig(BaseModel):
    method: str = "console"
    slack_webhook_url: str = ""
    price_drop_threshold_percent: float = 1.0
    price_drop_threshold_absolute: float = 0.0


def _load_yaml_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    with config_path.open() as f:
        return yaml.safe_load(f) or {}


def _resolve_config_path() -> Path:
    env_path = os.environ.get("CONFIG_PATH")
    if env_path:
        return Path(env_path)
    # Two levels up from this file: app/ -> backend/ -> project root
    return Path(__file__).parent.parent.parent / "config.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # Set via DATABASE_URL env var or .env — never from config.yaml
    database_url: str = "postgresql+asyncpg://pricechecker:pricechecker@localhost:5433/pricechecker"
    slack_webhook_url: str = ""
    check_interval_seconds: int = 300
    log_level: str = "INFO"

    # Populated from config.yaml; not overridable via env directly
    products: list[ProductConfig] = []
    notification_method: str | list[str] = "console"
    price_drop_threshold_percent: float = 1.0
    price_drop_threshold_absolute: float = 0.0
    proxies: list[str] = []

    @classmethod
    def from_yaml_and_env(cls) -> "Settings":
        raw = _load_yaml_config(_resolve_config_path())

        products_raw = raw.get("products", [])
        products = [ProductConfig(**p) for p in products_raw]

        notif_raw = raw.get("notifications", {})
        scheduler_raw = raw.get("scheduler", {})
        db_raw = raw.get("database", {})

        scraper_raw = raw.get("scraper", {})
        proxy_env = os.environ.get("PROXY_LIST", "")
        proxies = [p.strip() for p in proxy_env.split(",") if p.strip()]
        if not proxies:
            proxies = scraper_raw.get("proxies", [])

        defaults: dict = {
            "products": products,
            "notification_method": notif_raw.get("method", "console"),
            "price_drop_threshold_percent": notif_raw.get("price_drop_threshold_percent", 1.0),
            "price_drop_threshold_absolute": notif_raw.get("price_drop_threshold_absolute", 0.0),
            "check_interval_seconds": scheduler_raw.get("check_interval_seconds", 300),
            "proxies": proxies,
        }

        if notif_raw.get("slack_webhook_url"):
            defaults["slack_webhook_url"] = notif_raw["slack_webhook_url"]

        return cls(**defaults)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_yaml_and_env()
