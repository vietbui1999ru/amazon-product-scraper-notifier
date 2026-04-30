import asyncio
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import structlog
from sqlalchemy import text

from app.cache import invalidate_products_list
from app.comparison.detector import PriceDropEvent, PricePoint, detect_price_drop
from app.config import ProductConfig, Settings, get_settings
from app.database import AsyncSessionLocal
from app.notifications.base import AbstractNotifier
from app.notifications.factory import create_notifier
from app.scraper.amazon import AmazonScraper
from app.storage.repository import ProductRepository

log = structlog.get_logger(__name__)

# Event types that get the aligned pretty-print treatment
_PRETTY_EVENTS = {"TICK", "FORCE", "SCRAPE", "DROP", "FAIL", "SCHEDULED", "CANCELLED", "SKIPPED"}


def _logbus_processor(logger, method, event_dict):
    from app.logbus import publish
    publish(event_dict.copy())
    return event_dict


def _pretty_processor(logger, method, event_dict):
    """Format known event types into fixed-width aligned terminal lines."""
    event = event_dict.get("event", "")
    if event not in _PRETTY_EVENTS:
        return event_dict

    ts = event_dict.get("timestamp", "")
    etype = event.ljust(10)  # fixed 10-char event column

    if event == "TICK":
        count = event_dict.get("products", "?")
        nxt = event_dict.get("next", "?")
        line = f"[{ts}]  {etype} {count} products            next={nxt}s"

    elif event == "FORCE":
        name = event_dict.get("product", "?")
        triggered = event_dict.get("triggered", "api")
        line = f"[{ts}]  {etype} {name:<22} triggered={triggered}"

    elif event == "SCRAPE":
        name = event_dict.get("product", "?")
        price = event_dict.get("price", "?")
        currency = event_dict.get("currency", "USD")
        was = event_dict.get("was", "?")
        src = event_dict.get("src", "amazon")
        line = f"[{ts}]  {etype} {name:<22} ${price} {currency:<5}  was=${was}  src={src}"

    elif event == "DROP":
        name = event_dict.get("product", "?")
        old = event_dict.get("old", "?")
        new = event_dict.get("new", "?")
        pct = event_dict.get("pct", "?")
        diff = event_dict.get("diff", "?")
        line = f"[{ts}]  {etype} {name:<22} ${old} -> ${new} {pct}%  -${diff}"

    elif event == "FAIL":
        name = event_dict.get("product", "?")
        reason = event_dict.get("reason", "unknown")
        line = f"[{ts}]  {etype} {name:<22} reason={reason}"

    elif event == "SCHEDULED":
        name = event_dict.get("product", "?")
        price = event_dict.get("price", "?")
        currency = event_dict.get("currency", "USD")
        was = event_dict.get("was", "?")
        line = f"[{ts}]  {etype} {name:<22} ${price} {currency:<5}  was=${was}  src=self"

    elif event == "CANCELLED":
        name = event_dict.get("product", "?")
        reason = event_dict.get("reason", "?")
        line = f"[{ts}]  {etype} {name:<22} reason={reason}"

    elif event == "SKIPPED":
        name = event_dict.get("product", "?")
        reason = event_dict.get("reason", "?")
        line = f"[{ts}]  {etype} {name:<22} reason={reason}"

    else:
        return event_dict

    event_dict["event"] = line
    return event_dict


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))

    pretty = os.environ.get("LOG_FORMAT", "pretty").lower() != "json"

    if pretty:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
        processors = [
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.stdlib.add_log_level,
            _logbus_processor,
            _pretty_processor,
            renderer,
        ]
    else:
        processors = [
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.stdlib.add_log_level,
            _logbus_processor,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(),
    )


# ── Core scrape + notification logic ─────────────────────────────────────────

async def _build_drop_event(
    session,
    repo: ProductRepository,
    product,
    price_check,
    current_price: Decimal,
    current_currency: str,
    settings: Settings,
) -> PriceDropEvent | None:
    """Check for a price drop and mark price_check.notified=True (flushed, not committed).

    Returns the PriceDropEvent if a notification should be sent, None otherwise.
    Caller must: (1) commit the session, (2) call notifier.send(event) after commit.
    This ordering keeps the DB transaction closed before the Slack HTTP call and
    ensures at-most-once delivery (notified=True committed before send is attempted).
    """
    previous = await repo.get_previous_successful_price(product.id, exclude_id=price_check.id)
    if previous is None or previous.price is None:
        return None

    event = detect_price_drop(
        product_id=product.id,
        product_name=product.name,
        product_url=product.url,
        previous=PricePoint(price=Decimal(str(previous.price)), currency=previous.currency),
        current=PricePoint(price=current_price, currency=current_currency),
        threshold_percent=settings.price_drop_threshold_percent,
        threshold_absolute=settings.price_drop_threshold_absolute,
    )

    if event is None:
        return None

    # Advisory lock in the main transaction (not a savepoint) — held until caller commits,
    # preventing concurrent workers from sending duplicate notifications.
    lock_result = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:id)"),
        {"id": product.id},
    )
    if not lock_result.scalar():
        return None

    await session.refresh(price_check)
    if price_check.notified:
        return None

    price_check.notified = True
    await session.flush()

    log.info(
        "DROP",
        product=product.name,
        old=str(previous.price),
        new=str(current_price),
        pct=f"{event.drop_percent:.1f}",
        diff=f"{event.drop_amount:.2f}",
    )
    return event


async def _check_product_by_id(
    product_id: int,
    scraper: AmazonScraper,
    notifier: AbstractNotifier,
    settings: Settings,
    source: str = "amazon",
) -> None:
    """Scrape a single product by DB id and record result."""
    try:
        async with AsyncSessionLocal() as session:
            repo = ProductRepository(session)
            product = await repo.get_product_by_id(product_id)
            if product is None:
                log.warning("SKIPPED", product=f"id={product_id}", reason="not-found")
                return

            result = await scraper.scrape(product.url)

            price_check = await repo.record_price_check(
                product=product,
                price=float(result.price) if result.price is not None else None,
                currency=result.currency,
                success=result.success,
                error_message=result.error_message,
                source=source,
            )

            if result.success and result.price is not None:
                # Cancel pending scheduled prices since amazon gave us a fresh price
                now = datetime.now(timezone.utc)
                await repo.cancel_pending_scheduled_prices(product.id, "amazon_scrape", now)

                pending_event = await _build_drop_event(
                    session, repo, product, price_check,
                    result.price, result.currency, settings,
                )

                log.info(
                    "SCRAPE",
                    product=product.name,
                    price=str(result.price),
                    currency=result.currency,
                    was="?",
                    src=source,
                )
            else:
                log.warning("FAIL", product=product.name, reason=result.error_message or "unknown")
                pending_event = None

            await session.commit()
            try:
                await invalidate_products_list()
            except Exception as e:
                log.warning("cache.invalidate_failed", error=str(e))

            if pending_event is not None:
                try:
                    await notifier.send(pending_event)
                except Exception as e:
                    log.warning("notifier.send_failed", product=product.name, error=str(e))

    except Exception:
        log.exception("price_check.failed", product=f"id={product_id}")


async def _check_product_config(
    product_config: ProductConfig,
    scraper: AmazonScraper,
    notifier: AbstractNotifier,
    settings: Settings,
    skip_product_ids: set[int] | None = None,
) -> None:
    """Scrape a product defined in config (normal cycle)."""
    try:
        async with AsyncSessionLocal() as session:
            repo = ProductRepository(session)

            product, _ = await repo.get_or_create_product(
                url=product_config.url,
                name=product_config.name,
            )

            if skip_product_ids and product.id in skip_product_ids:
                log.info("SKIPPED", product=product.name, reason="applied-this-tick")
                return

            result = await scraper.scrape(product_config.url)

            price_check = await repo.record_price_check(
                product=product,
                price=float(result.price) if result.price is not None else None,
                currency=result.currency,
                success=result.success,
                error_message=result.error_message,
                source="amazon",
            )

            if result.success and result.price is not None:
                now = datetime.now(timezone.utc)
                await repo.cancel_pending_scheduled_prices(product.id, "amazon_scrape", now)

                pending_event = await _build_drop_event(
                    session, repo, product, price_check,
                    result.price, result.currency, settings,
                )

                log.info(
                    "SCRAPE",
                    product=product.name,
                    price=str(result.price),
                    currency=result.currency,
                    was="?",
                    src="amazon",
                )
                await repo.prune_price_history(product.id, keep=500)
            else:
                log.warning("FAIL", product=product.name, reason=result.error_message or "unknown")
                pending_event = None

            await session.commit()
            try:
                await invalidate_products_list()
            except Exception as e:
                log.warning("cache.invalidate_failed", error=str(e))

            if pending_event is not None:
                try:
                    await notifier.send(pending_event)
                except Exception as e:
                    log.warning("notifier.send_failed", product=product.name, error=str(e))

    except Exception:
        log.exception("price_check.failed", product=product_config.name)


# ── Tick phases ───────────────────────────────────────────────────────────────

async def _drain_force_queue(
    scraper: AmazonScraper,
    notifier: AbstractNotifier,
    settings: Settings,
) -> set[int]:
    """Phase 1: drain force-check queue.

    Acquires Redis locks sequentially (fast), then scrapes concurrently as
    worker tasks. The scraper's Semaphore(1) serialises actual I/O.
    Returns the set of product IDs that were scraped so phase 3 can skip them.
    """
    from app.cache import acquire_force_lock
    from app.scheduler.queue import get_force_queue

    q = get_force_queue()
    product_ids: list[int] = []
    while not q.empty():
        try:
            product_ids.append(q.get_nowait())
        except asyncio.QueueEmpty:
            break

    product_ids = list(dict.fromkeys(product_ids))  # dedup, preserve order

    # Lock acquisition is fast (Redis SET NX) — keep sequential.
    to_scrape: list[int] = []
    for pid in product_ids:
        if await acquire_force_lock(pid):
            log.info("FORCE", product=f"id={pid}", triggered="api")
            to_scrape.append(pid)
        else:
            log.info("SKIPPED", product=f"id={pid}", reason="already_queued")

    if not to_scrape:
        return set()

    # Fan out as concurrent worker tasks; scraper semaphore controls parallelism.
    tasks = [
        asyncio.create_task(
            _check_product_by_id(pid, scraper, notifier, settings, source="amazon")
        )
        for pid in to_scrape
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    scraped_ids: set[int] = set()
    for pid, result in zip(to_scrape, results):
        if isinstance(result, Exception):
            log.error("force_worker.failed", product_id=pid, error=str(result))
        else:
            scraped_ids.add(pid)

    return scraped_ids


async def _apply_due_scheduled_prices(
    notifier: AbstractNotifier,
    settings: Settings,
) -> set[int]:
    """Phase 2: apply any scheduled prices whose scheduled_for has passed.

    Returns the set of product IDs that were processed so phase 3 can skip them
    and avoid double-notifications in the same tick.

    Each item is committed in its own session so a failure on one item does not
    roll back already-applied rows.
    """
    now = datetime.now(timezone.utc)
    applied_product_ids: set[int] = set()

    # Fetch due rows in a short-lived session, then close it before per-item work.
    async with AsyncSessionLocal() as session:
        repo = ProductRepository(session)
        due = await repo.get_pending_scheduled_prices_due(now)
        due_snapshot = [(sp.id, sp.product_id, sp.price, sp.currency) for sp in due]

    for sp_id, product_id, price, currency in due_snapshot:
        try:
            async with AsyncSessionLocal() as session:
                repo = ProductRepository(session)

                product = await repo.get_product_by_id(product_id)
                if product is None:
                    continue

                price_check = await repo.record_price_check(
                    product=product,
                    price=float(price),
                    currency=currency,
                    success=True,
                    source="self",
                )

                pending_event = await _build_drop_event(
                    session, repo, product, price_check,
                    price, currency, settings,
                )

                log.info(
                    "SCHEDULED",
                    product=product.name,
                    price=str(price),
                    currency=currency,
                    was="?",
                )

                # Re-fetch the ScheduledPrice row in this session to mark applied.
                sp_row = await repo.get_scheduled_price_by_id(sp_id)
                if sp_row is not None:
                    sp_row.applied_at = now

                await session.commit()
                try:
                    await invalidate_products_list()
                except Exception as e:
                    log.warning("cache.invalidate_failed", error=str(e))
                applied_product_ids.add(product_id)

                if pending_event is not None:
                    try:
                        await notifier.send(pending_event)
                    except Exception as e:
                        log.warning("notifier.send_failed", product=product.name, error=str(e))

        except Exception:
            log.exception("scheduled_price.failed", product_id=product_id)

    return applied_product_ids


async def _run_normal_cycle(
    scraper: AmazonScraper,
    notifier: AbstractNotifier,
    settings: Settings,
    skip_product_ids: set[int] | None = None,
) -> None:
    """Phase 3: scrape all configured products as concurrent worker tasks.

    The scraper's Semaphore(1) serialises actual I/O — bump it to allow
    more concurrent scrapes (e.g. when using proxies).
    Products in skip_product_ids were processed this tick; skipped to avoid
    double-notifications.
    """
    if not settings.products:
        log.info("scheduler.no_products_configured")
        return

    skip = skip_product_ids or set()
    tasks = [
        asyncio.create_task(
            _check_product_config(product_config, scraper, notifier, settings, skip_product_ids=skip)
        )
        for product_config in settings.products
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for product_config, result in zip(settings.products, results):
        if isinstance(result, Exception):
            log.error("normal_worker.failed", product=product_config.name, error=str(result))


# ── Maintenance ──────────────────────────────────────────────────────────────

async def _cleanup_settled_prices() -> None:
    """Phase 4: delete applied/cancelled scheduled prices older than 30 days."""
    try:
        async with AsyncSessionLocal() as session:
            repo = ProductRepository(session)
            deleted = await repo.delete_settled_scheduled_prices(older_than_days=30)
            await session.commit()
            if deleted:
                log.info("cleanup.settled_prices", deleted=deleted)
    except Exception as e:
        log.warning("cleanup.settled_prices_failed", error=str(e))


# ── Main loop ─────────────────────────────────────────────────────────────────

async def run_scheduler() -> None:
    settings = get_settings()
    _configure_logging(settings.log_level if hasattr(settings, "log_level") else "INFO")

    log.info(
        "scheduler.starting",
        interval=settings.check_interval_seconds,
        products=len(settings.products),
    )

    notifier = create_notifier(settings)

    async with AmazonScraper(proxies=settings.proxies) as scraper:
        while True:
            try:
                log.info(
                    "TICK",
                    products=len(settings.products),
                    next=settings.check_interval_seconds,
                )

                force_ids = await _drain_force_queue(scraper, notifier, settings)
                applied_ids = await _apply_due_scheduled_prices(notifier, settings)
                await _run_normal_cycle(scraper, notifier, settings, skip_product_ids=force_ids | applied_ids)
                await _cleanup_settled_prices()

                await asyncio.sleep(settings.check_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("scheduler.crashed")
                await asyncio.sleep(30)
