---
title: "Repository Layer (ProductRepository)"
description: "Full method reference for ProductRepository — the only data-access layer between the app and Postgres."
tags: [backend, repository, database]
updated: 2026-04-28
---

# Repository Layer (ProductRepository)

`app/storage/repository.py`

`ProductRepository` wraps an `AsyncSession`. It never calls `session.commit()` — callers own the transaction boundary. All writes are flushed with `session.flush()` to populate auto-generated IDs without committing.

```python
repo = ProductRepository(session)
```

---

## Product Methods

### `get_or_create_product`

```python
async def get_or_create_product(
    self,
    url: str,
    name: str,
    image_url: str | None = None,
    rating: str | None = None,
) -> tuple[Product, bool]
```

Looks up a product by exact `url`. If found, returns `(product, False)`. If not found, creates a new row (extracting `asin` from the URL via `_extract_asin`), flushes, and returns `(product, True)`.

`image_url` and `rating` are only written on creation — existing products are not updated so the method is idempotent on repeat calls.

**SQL**: `SELECT ... WHERE url = :url`, then `INSERT` on miss.

---

### `record_price_check`

```python
async def record_price_check(
    self,
    product: Product,
    price: float | None,
    currency: str,
    success: bool,
    error_message: str | None = None,
    source: str = "amazon",
) -> PriceCheck
```

Inserts a `PriceCheck` row and flushes. Returns the new ORM object with its `id` populated.

Call this after every scrape attempt, whether successful or not. Pass `success=False` and `price=None` on scrape errors.

---

### `get_last_successful_price`

```python
async def get_last_successful_price(self, product_id: int) -> PriceCheck | None
```

Returns the most recent `PriceCheck` where `scrape_success=True` and `price IS NOT NULL`, ordered by `scraped_at DESC, id DESC`. Returns `None` if no successful check exists.

Used to determine the product's current price for display and notification comparison.

---

### `get_previous_successful_price`

```python
async def get_previous_successful_price(
    self, product_id: int, exclude_id: int
) -> PriceCheck | None
```

Same filter as `get_last_successful_price` but excludes one specific row by `id`. Used during drop detection — pass the ID of the just-recorded check to get the one before it.

---

### `get_price_history`

```python
async def get_price_history(self, product_id: int, limit: int = 100) -> list[PriceCheck]
```

Returns up to `limit` `PriceCheck` rows for a product, ordered `scraped_at DESC, id DESC`. Includes failed rows (where `scrape_success=False`). The API endpoint accepts `limit` values from 1 to 1000.

---

### `get_all_products`

```python
async def get_all_products(self) -> list[Product]
```

Returns all `Product` rows ordered by `created_at ASC`. Used by `GET /api/products` and the scheduler's normal cycle.

---

### `get_product_by_id`

```python
async def get_product_by_id(self, product_id: int) -> Product | None
```

Point lookup by primary key. Returns `None` if not found.

---

### `get_product_by_url`

```python
async def get_product_by_url(self, url: str) -> Product | None
```

Point lookup by exact `url`. Returns `None` if not found. Used as fallback in `POST /api/demo/drop` when Redis cache misses.

---

### `mark_notified`

```python
async def mark_notified(self, price_check_id: int) -> None
```

Sets `notified=True` on a `PriceCheck` row and flushes. Raises `sqlalchemy.exc.NoResultFound` if the row does not exist (uses `scalar_one()`).

---

## ScheduledPrice Methods

### `_pending_filter`

```python
def _pending_filter(self) -> sqlalchemy.sql.elements.BooleanClauseList
```

Internal helper. Returns the SQLAlchemy filter expression `applied_at IS NULL AND cancelled_at IS NULL`. Used by all methods that operate on pending scheduled prices to centralise the pending definition.

---

### `create_scheduled_price`

```python
async def create_scheduled_price(
    self,
    product_id: int,
    price: Decimal,
    currency: str,
    scheduled_for: datetime,
) -> ScheduledPrice
```

Inserts a new `ScheduledPrice` row and flushes. Returns the new ORM object.

---

### `get_pending_scheduled_prices_due`

```python
async def get_pending_scheduled_prices_due(self, now: datetime) -> list[ScheduledPrice]
```

Returns all pending rows where `scheduled_for <= now`. Called by the scheduler's phase 2 (`_apply_due_scheduled_prices`) at each tick.

---

### `get_pending_scheduled_prices`

```python
async def get_pending_scheduled_prices(self) -> list[ScheduledPrice]
```

Returns all pending rows ordered by `scheduled_for ASC`. Used for internal listing without join.

---

### `get_pending_scheduled_prices_with_products`

```python
async def get_pending_scheduled_prices_with_products(
    self,
) -> list[tuple[ScheduledPrice, Product]]
```

Returns all pending rows joined with their `Product` in a single query, ordered by `scheduled_for ASC`. Used by `GET /api/scheduler/prices/pending` to avoid N+1 lookups.

---

### `get_scheduled_price_by_id`

```python
async def get_scheduled_price_by_id(self, scheduled_id: int) -> ScheduledPrice | None
```

Point lookup by primary key. Returns `None` if not found.

---

### `cancel_pending_scheduled_prices`

```python
async def cancel_pending_scheduled_prices(
    self, product_id: int, reason: str, now: datetime
) -> None
```

Bulk-cancels all pending scheduled prices for a product using a single `UPDATE` statement. Sets `cancelled_at=now` and `cancel_reason=reason` on all matching rows.

Called automatically when a real Amazon scrape succeeds — reason will be `"amazon_scrape"`.

---

### `cancel_scheduled_price`

```python
async def cancel_scheduled_price(
    self, scheduled_id: int, reason: str, now: datetime
) -> bool
```

Cancels a single pending scheduled price by ID. Returns `False` if the row is not found, or if it is already settled (`applied_at` or `cancelled_at` is set). Returns `True` on success and flushes.

Used by `DELETE /api/scheduler/prices/{id}` with reason `"manual"`.
