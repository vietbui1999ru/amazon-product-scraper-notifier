---
title: "API Reference"
description: "All REST endpoints — method, path, request shape, response shape, status codes, and cache behaviour."
tags: [backend, api, rest]
updated: 2026-04-28
---

# API Reference

Base prefix: `/api`

Rate limiting via `slowapi` (key: remote IP). Exceeding a limit returns HTTP 429.

---

## Products

### `GET /api/products`

Returns all tracked products with their latest successful price.

**Response** — `200 OK`

```json
[
  {
    "id": 1,
    "url": "https://www.amazon.com/dp/B07RW6Z692",
    "name": "Echo Dot (4th Gen)",
    "asin": "B07RW6Z692",
    "created_at": "2026-04-01T12:00:00Z",
    "image_url": "https://...",
    "rating": "4.7 out of 5 stars",
    "latest_price": 29.99
  }
]
```

`latest_price` is `null` if no successful price check exists for the product.

**Cache behaviour**

- On hit: reads from Redis key `cache:products` (TTL 30s) and returns without touching Postgres.
- On miss: queries Postgres, assembles response, writes to `cache:products` with 30s TTL.
- Cache is invalidated (key deleted) by: `POST /api/products`, `POST /api/demo/drop`, and any scheduler commit that records a new price.
- If Redis is unavailable, the cache read/write is skipped silently — request proceeds against Postgres.

---

### `POST /api/products`

Add a product to tracking.

**Request body**

```json
{
  "url": "https://www.amazon.com/dp/B07RW6Z692",
  "name": "Echo Dot (4th Gen)",
  "image_url": "https://...",
  "rating": "4.7 out of 5 stars",
  "initial_price": 29.99
}
```

| Field | Required | Notes |
|---|---|---|
| `url` | yes | Must match `https?://(www\.)?amazon\.[a-z.]+/(?:.+/)?dp/[A-Z0-9]{10}` — product slug before `/dp/` is optional |
| `name` | yes | |
| `image_url` | no | |
| `rating` | no | |
| `initial_price` | no | If provided and product is newly created, writes one `PriceCheck` row with `source="self"` |

The URL is normalized to `https://www.amazon.com/dp/{ASIN}` before storage. If the URL already exists, the existing product is returned (idempotent).

**Response** — `201 Created`

Same shape as a single element from `GET /api/products`.

**Errors**

| Status | Condition |
|---|---|
| `400` | URL does not match Amazon ASIN pattern |

**Side effects**: invalidates `cache:products`, writes product URL+name to Redis index.

---

### `GET /api/products/{product_id}/history`

Returns price check history for a product.

**Path param**: `product_id` — integer product ID.

**Query params**

| Param | Default | Constraints | Notes |
|---|---|---|---|
| `limit` | `100` | 1–1000 | Max rows returned, ordered newest first |

**Response** — `200 OK`

```json
[
  {
    "id": 42,
    "product_id": 1,
    "price": 24.99,
    "currency": "USD",
    "scraped_at": "2026-04-28T10:00:00Z",
    "scrape_success": true,
    "error_message": null,
    "notified": false,
    "source": "amazon"
  }
]
```

Includes rows where `scrape_success=False`. `price` is `null` on failed scrapes.

**Errors**

| Status | Condition |
|---|---|
| `404` | Product ID not found |

---

### `POST /api/products/force-check`

Queue one or more products for an immediate scrape on the next scheduler drain.

**Rate limit**: 10 per minute.

**Request body**

```json
{ "product_ids": [1, 2, 3] }
```

or

```json
{ "all": true }
```

`product_ids` and `all` are mutually exclusive. Providing neither returns 400.

**Response** — `202 Accepted`

```json
{
  "queued": 2,
  "message": "Scrape queued. Watch /api/logs for results.",
  "not_found": [99]
}
```

`not_found` is omitted when `all=true`. IDs that could not be queued because the asyncio queue (maxsize 500) was full are reported in the message.

**Errors**

| Status | Condition |
|---|---|
| `400` | Neither `product_ids` nor `all` provided |

**Dedup**: the scheduler acquires a Redis lock `force_lock:{product_id}` (SET NX EX 60) before scraping each queued ID. If the lock is already held, that product is skipped for this drain cycle.

---

## Search

### `GET /api/search`

Search Amazon and return up to 8 results.

**Rate limit**: 1 per second.

**Query params**

| Param | Required | Constraints |
|---|---|---|
| `q` | yes | 2–100 characters |

**Response** — `200 OK`

```json
[
  {
    "asin": "B07RW6Z692",
    "name": "Echo Dot (4th Gen)",
    "url": "https://www.amazon.com/dp/B07RW6Z692",
    "price": 29.99,
    "image_url": "https://...",
    "rating": "4.7 out of 5 stars, 200,000 ratings"
  }
]
```

`price` and `image_url` and `rating` can be `null` if the search result page did not render them. Results are capped at 8 items.

---

## Demo

### `POST /api/demo/drop`

Inject a fake price and fire the configured notifier. Bypasses the normal drop threshold (any price lower than the previous triggers a notification).

**Rate limit**: 10 per minute.

**Request body**

```json
{
  "url": "https://www.amazon.com/dp/B07RW6Z692",
  "price": 19.99
}
```

`price` must be `> 0`.

Product lookup: Redis URL index first (`product_url:{url}`), then Postgres fallback.

**Response** — `200 OK`

```json
{
  "product": "Echo Dot (4th Gen)",
  "old_price": 29.99,
  "new_price": 19.99,
  "notification_sent": true
}
```

`notification_sent` is `false` if there was no previous successful price to compare against.

**Errors**

| Status | Condition |
|---|---|
| `404` | Product not found |

**Side effects**: writes a `PriceCheck` row with `source="self"`, invalidates `cache:products`.

---

## Scheduler

### `POST /api/scheduler/prices`

Schedule a future price injection.

**Rate limit**: 20 per minute.

**Request body**

```json
{
  "product_id": 1,
  "price": 19.99,
  "minutes": 30
}
```

or use `url` instead of `product_id`:

```json
{
  "url": "https://www.amazon.com/dp/B07RW6Z692",
  "price": 19.99,
  "minutes": 30
}
```

| Field | Required | Constraints |
|---|---|---|
| `product_id` or `url` | one required | mutually exclusive |
| `price` | yes | `> 0` |
| `minutes` | one required | `1–525600` (max 1 year) |
| `seconds` | one required | `1–86400` (max 24 hours) |

Provide either `minutes` or `seconds`, not both.

`scheduled_for` is computed as `now (UTC) + delay`.

**Response** — `201 Created`

```json
{
  "id": 7,
  "product": "Echo Dot (4th Gen)",
  "price": 19.99,
  "scheduled_for": "2026-04-28T11:30:00Z"
}
```

**Errors**

| Status | Condition |
|---|---|
| `400` | Neither `product_id` nor `url` provided, or invalid `minutes` |
| `404` | Product not found |

---

### `GET /api/scheduler/prices/pending`

List all pending (unapplied, uncancelled) scheduled prices.

**Response** — `200 OK`

```json
[
  {
    "id": 7,
    "product_id": 1,
    "product": "Echo Dot (4th Gen)",
    "price": 19.99,
    "currency": "USD",
    "scheduled_for": "2026-04-28T11:30:00Z",
    "created_at": "2026-04-28T11:00:00Z"
  }
]
```

Ordered by `scheduled_for ASC`. Uses a single joined query (no N+1).

---

### `DELETE /api/scheduler/prices/{scheduled_id}`

Cancel a pending scheduled price.

**Rate limit**: 30 per minute.

**Path param**: `scheduled_id` — integer scheduled price ID.

**Response** — `200 OK`

```json
{ "cancelled": 7 }
```

**Errors**

| Status | Condition |
|---|---|
| `404` | Row not found, or already applied or cancelled |

---

## Logs

### `GET /api/logs`

Server-Sent Events stream of structured log events from the scheduler.

**Response** — `200 OK` with `Content-Type: text/event-stream`

Each event is a JSON object serialized as an SSE `data:` line:

```
retry: 2000

data: {"event": "SCRAPE", "product": "Echo Dot", "price": "24.99", ...}

data: {"event": "DROP", ...}

: keepalive
```

- A `retry: 2000` directive is sent on connection, instructing clients to reconnect after 2s on disconnect.
- A `: keepalive` comment is sent every 15s when no events arrive, to prevent proxy timeouts.
- New subscribers receive up to the last 100 log events immediately (replay from in-memory `deque`).
- `Cache-Control: no-cache` and `X-Accel-Buffering: no` headers are set to prevent proxy buffering.

No authentication. No rate limit on this endpoint.

---

## Config

### `GET /api/config`

Returns the current runtime configuration (mutable, no restart required to change).

**Response** — `200 OK`

```json
{
  "check_interval_seconds": 300,
  "notification_method": "console",
  "price_drop_threshold_percent": 1.0,
  "price_drop_threshold_absolute": 0.0,
  "scraper_headless": true,
  "scraper_timeout_ms": 30000,
  "scraper_min_delay": 1.0,
  "scraper_max_delay": 5.0
}
```

`scraper_headless` is read-only (requires backend restart to change — Playwright browser is launched once at startup).

---

### `PATCH /api/config`

Update one or more runtime config fields. Changes take effect on the next scheduler tick.

**Rate limit**: 30 per minute.

**Request body** — all fields optional:

```json
{
  "check_interval_seconds": 60,
  "notification_method": ["console", "slack"],
  "price_drop_threshold_percent": 5.0,
  "price_drop_threshold_absolute": 2.0,
  "scraper_timeout_ms": 45000,
  "scraper_min_delay": 2.0,
  "scraper_max_delay": 8.0
}
```

| Field | Constraints |
|---|---|
| `check_interval_seconds` | 10–86400 |
| `notification_method` | `"console"`, `"slack"`, or `["console", "slack"]` |
| `price_drop_threshold_percent` | `>= 0.0` |
| `price_drop_threshold_absolute` | `>= 0.0` |
| `scraper_timeout_ms` | 1000–120000 |
| `scraper_min_delay` | `>= 0.0`, must not exceed `scraper_max_delay` |
| `scraper_max_delay` | `>= 0.0`, must not be less than `scraper_min_delay` |

**Response** — `200 OK` — full updated config (same shape as `GET /api/config`).

**Errors**

| Status | Condition |
|---|---|
| `400` | `scraper_min_delay > scraper_max_delay` |
