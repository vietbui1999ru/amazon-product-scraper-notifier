---
title: "Scheduler"
description: "Tick loop architecture, three execution phases, force queue, scheduled price application, and logging format."
tags: [backend, scheduler, background-tasks]
updated: 2026-04-28
---

# Scheduler

`app/scheduler/runner.py`

The scheduler runs as a background asyncio task started in the FastAPI lifespan (`app/main.py`). It loops indefinitely with a sleep of `CHECK_INTERVAL_SECONDS` between ticks.

**Single-replica assumption**: the scheduler is embedded in the FastAPI process. Running multiple replicas will cause duplicate scrapes and duplicate notifications. There is no distributed lock on the tick itself.

---

## Entry Point

```python
async def run_scheduler() -> None
```

Called once by `asyncio.create_task(run_scheduler())` at application startup. Initialises logging, creates a single shared `AmazonScraper` and notifier, then enters the tick loop.

Tick loop pseudocode:

```
while True:
    force_ids  = await _drain_force_queue(...)       # Phase 1
    applied_ids = await _apply_due_scheduled_prices(...)  # Phase 2
    await _run_normal_cycle(..., skip=force_ids | applied_ids)  # Phase 3
    await asyncio.sleep(CHECK_INTERVAL_SECONDS)
```

---

## Configuration

| Env var | Default | Notes |
|---|---|---|
| `CHECK_INTERVAL_SECONDS` | `300` | Overridable via `config.yaml` `scheduler.check_interval_seconds` or env |
| `LOG_FORMAT` | `pretty` | Set to `json` for machine-readable output |

---

## Phase 1: `_drain_force_queue`

```python
async def _drain_force_queue(
    scraper: AmazonScraper,
    notifier: AbstractNotifier,
    settings: Settings,
) -> set[int]
```

Drains all product IDs currently in the asyncio force queue (`maxsize=500`). Deduplicates while preserving order (first occurrence wins).

For each unique product ID:
1. Attempts to acquire `force_lock:{product_id}` via Redis SET NX EX 60.
2. If lock is not acquired (another scrape is already in progress for this ID), logs `SKIPPED reason=already_queued` and continues.
3. If acquired, logs `FORCE`, calls `_check_product_by_id`, then sleeps 1.5s before the next ID (except after the last one).

Returns the set of product IDs that were actually scraped. The normal cycle uses this set to avoid double-scraping.

---

## Phase 2: `_apply_due_scheduled_prices`

```python
async def _apply_due_scheduled_prices(
    notifier: AbstractNotifier,
    settings: Settings,
) -> set[int]
```

Fetches all pending `ScheduledPrice` rows where `scheduled_for <= now`. Snapshots them into memory, then closes the fetch session.

For each due row, opens a fresh session and:
1. Records a `PriceCheck` with `source="self"` and `scrape_success=True`.
2. Runs `_run_drop_detection_and_notify`.
3. Sets `applied_at = now` on the `ScheduledPrice` row.
4. Commits the session.
5. Calls `invalidate_products_list()` to flush the Redis cache.

Each item is committed in its own session — a failure on one item does not roll back already-applied rows.

Returns the set of product IDs processed. The normal cycle skips these to avoid double-notifications in the same tick.

---

## Phase 3: `_run_normal_cycle`

```python
async def _run_normal_cycle(
    scraper: AmazonScraper,
    notifier: AbstractNotifier,
    settings: Settings,
    skip_product_ids: set[int] | None = None,
) -> None
```

Iterates over `settings.products` (the list of configured products from `config.yaml`). For each, calls `_check_product_config`.

Products whose IDs are in `skip_product_ids` (union of phase 1 and phase 2 results) are skipped with `SKIPPED reason=applied-this-tick`.

If `settings.products` is empty, logs `scheduler.no_products_configured` and returns.

---

## Drop Detection and Notification: `_run_drop_detection_and_notify`

```python
async def _run_drop_detection_and_notify(
    session,
    repo: ProductRepository,
    product,
    price_check,
    current_price: Decimal,
    current_currency: str,
    notifier: AbstractNotifier,
    settings: Settings,
) -> bool
```

Called after every successful scrape (all three phases). Steps:

1. Fetches the previous successful price (excluding the just-recorded check ID).
2. Calls `detect_price_drop` with configured thresholds.
3. If a drop event is detected:
   - Acquires `pg_try_advisory_xact_lock(product.id)` within a `begin_nested()` savepoint.
   - Re-fetches `price_check` (refresh) to read the current `notified` flag.
   - If `notified=False`, calls `notifier.send(event)` and sets `notified=True`.
4. Returns `True` if a notification was sent.

The advisory lock prevents duplicate notifications in hypothetical concurrent execution. Combined with the `notified` flag check, this provides at-least-once delivery (not exactly-once — if the process dies after `notifier.send()` but before the commit, the event may be sent again on restart).

---

## Force Queue

`app/scheduler/queue.py`

```python
_force_queue: asyncio.Queue[int] = asyncio.Queue(maxsize=500)

def get_force_queue() -> asyncio.Queue[int]
```

Module-level singleton. `POST /api/products/force-check` calls `q.put_nowait(product_id)` to enqueue IDs. The scheduler drains this queue at the start of every tick (phase 1).

If the queue is full (`QueueFull`), the API returns a message indicating how many IDs were skipped.

---

## Cache Invalidation

`invalidate_products_list()` is called after `session.commit()` in each phase:
- Phase 1: after each product scrape in `_check_product_by_id`
- Phase 2: after each scheduled price application
- Phase 3: after each product scrape in `_check_product_config`

If Redis is unavailable, the `invalidate_products_list()` call raises an exception which is caught and logged as a warning — it does not abort the commit.

---

## Logging

The scheduler configures `structlog` at startup via `_configure_logging`. Two output modes:

**Pretty (default, `LOG_FORMAT` != `json`)**

Events with recognized names are formatted into fixed-width aligned terminal lines. The event name column is always 10 characters wide (left-padded).

| Event | Format |
|---|---|
| `TICK` | `[HH:MM:SS]  TICK       N products            next=Ns` |
| `FORCE` | `[HH:MM:SS]  FORCE      {name:<22} triggered=api` |
| `SCRAPE` | `[HH:MM:SS]  SCRAPE     {name:<22} ${price} {currency}  was=${was}  src={src}` |
| `DROP` | `[HH:MM:SS]  DROP       {name:<22} ${old} -> ${new} {pct}%  -${diff}` |
| `FAIL` | `[HH:MM:SS]  FAIL       {name:<22} reason={reason}` |
| `SCHEDULED` | `[HH:MM:SS]  SCHEDULED  {name:<22} ${price} {currency}  was=${was}  src=self` |
| `CANCELLED` | `[HH:MM:SS]  CANCELLED  {name:<22} reason={reason}` |
| `SKIPPED` | `[HH:MM:SS]  SKIPPED    {name:<22} reason={reason}` |

**JSON (`LOG_FORMAT=json`)**

Each log call emits a JSON object on stdout. All event fields are included as top-level keys. Use for log aggregation pipelines.

All log events are also published to the in-memory `logbus` (see `app/logbus.py`), which fans them out to connected SSE clients on `GET /api/logs`.
