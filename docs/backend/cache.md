---
title: "Redis Cache"
description: "All Redis operations — key naming, TTLs, and fail-safe patterns."
tags: [backend, cache, redis]
updated: 2026-04-28
---

# Redis Cache

`app/cache.py`

All cache operations are async and use `redis.asyncio`. The Redis client is a lazy module-level singleton.

---

## Key Reference

| Key pattern | TTL | Purpose |
|---|---|---|
| `product:{id}` | none (persists) | Hash storing `url` and `name` for a product |
| `product_url:{url}` | none (persists) | String mapping a product URL to its integer `id` |
| `cache:products` | 30s | Serialized JSON of the full `GET /api/products` response |
| `force_lock:{product_id}` | 60s | Mutex preventing duplicate force-scrapes |

---

## Functions

### `get_redis`

```python
def get_redis() -> Redis
```

Returns the singleton `redis.asyncio.Redis` client. Initializes on first call using `REDIS_URL` env var (default: `redis://localhost:6379`). Responses are decoded as strings (`decode_responses=True`).

---

### `cache_product`

```python
async def cache_product(product_id: int, url: str, name: str) -> None
```

Writes two keys:
- `HSET product:{product_id}` with fields `url` and `name`
- `SET product_url:{url}` = `product_id`

Called by `POST /api/products` after creating or retrieving a product.

---

### `get_cached_product`

```python
async def get_cached_product(product_id: int) -> dict | None
```

Returns `{"url": ..., "name": ...}` from `HGETALL product:{product_id}`, or `None` if the key does not exist.

---

### `get_product_id_by_url`

```python
async def get_product_id_by_url(url: str) -> int | None
```

Returns the integer product ID for a URL from `GET product_url:{url}`, or `None` on cache miss.

Used by `POST /api/demo/drop` to avoid a Postgres lookup when the product is already cached.

---

### `get_cached_products_list`

```python
async def get_cached_products_list() -> str | None
```

Returns the raw JSON string stored at `cache:products`, or `None` on cache miss. The caller (`GET /api/products`) deserializes and returns it directly without touching Postgres.

---

### `set_cached_products_list`

```python
async def set_cached_products_list(data: str) -> None
```

Writes `data` to `cache:products` with a 30-second TTL (`SET cache:products {data} EX 30`).

---

### `invalidate_products_list`

```python
async def invalidate_products_list() -> None
```

Deletes `cache:products`. Called after any operation that changes product data or prices: product creation, demo drop, and every scheduler commit.

---

### `acquire_force_lock`

```python
async def acquire_force_lock(product_id: int) -> bool
```

Attempts `SET force_lock:{product_id} 1 NX EX 60`. Returns `True` if the lock was acquired (safe to proceed with scrape), `False` if already held.

The 60-second TTL ensures stale locks self-expire. The scheduler's phase 1 checks this before each force-scrape.

---

## Fail-Safe Pattern

All cache calls in routes and the scheduler are wrapped in `try/except Exception`. If Redis is down or raises any error:
- The exception is caught and logged as a warning (`cache.error` or `cache.invalidate_failed`).
- The request continues against Postgres.
- No HTTP error is returned to the client.

This means Redis is advisory — the application is correct without it, just slower.
