# Price Checker — Analysis & Review Report

**Date:** 2026-04-29  
**Scope:** Full backend review — code quality, security, architecture, API correctness, DB operations  
**Agents run:** code-reviewer, security-auditor, design-critic, api-tester/QA  
**Status:** Review-only. No fixes applied. Use this file to prioritise remediation.

---

## Executive Summary

| Category      | Critical | High   | Medium | Low   |
| ------------- | -------- | ------ | ------ | ----- |
| Code Quality  | —        | 5      | 4      | —     |
| Security      | —        | 3      | 5      | 3     |
| Architecture  | —        | 3      | 4      | 1     |
| API / QA Bugs | —        | 2      | 4      | 2     |
| DB Operations | —        | 2      | 1      | 1     |
| **Total**     | **0**    | **15** | **18** | **7** |

No critical findings. The stack is functionally sound for homelab use. Three High-severity issues can combine into real operational failures (Slack notification storm, duplicate scrape charges, incorrect cancellation state). Fix priority: DB correctness → notification ordering → CORS → security hardening.

---

## Part 1 — Code Quality (Code Reviewer)

### [HIGH-1] CORS missing PATCH and DELETE methods

**File:** `backend/app/main.py:36`

```python
allow_methods=["GET", "POST", "OPTIONS"]  # ← PATCH and DELETE missing
```

The `PATCH /api/products/{id}/image` and `DELETE /api/scheduler/prices/{id}` endpoints exist but CORS will block them from browsers. Works in curl/Postman; silently fails in the frontend. Image editing and scheduled-price cancellation are broken for any browser calling the API from a different origin.

**Fix:**
```python
allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
```

---

### [HIGH-2] Advisory lock releases before outer commit — duplicate notification possible

**File:** `backend/app/scheduler/runner.py:155-164`

`pg_try_advisory_xact_lock` is a **transaction-scoped** lock. It releases when the `begin_nested()` savepoint exits (line 164), not at the outer `session.commit()` (line 227). Between savepoint exit and outer commit, a concurrent worker calling `session.refresh(price_check)` sees `notified=False` (outer transaction hasn't committed), acquires the lock, and sends a duplicate Slack notification.

**Fix:** Move the advisory lock call outside the savepoint, directly inside the main transaction. Or replace with an atomic `UPDATE price_checks SET notified=true WHERE id=? AND notified=false RETURNING id` — send notification only if 1 row returned.

---

### [HIGH-3] Scheduled price TOCTOU — row can be both applied and cancelled

**File:** `scheduler/runner.py:375-413` and `storage/repository.py:232-244`

`_apply_due_scheduled_prices` snapshots due rows, closes the session, then applies each in a fresh session. Concurrently, `DELETE /api/scheduler/prices/{id}` can cancel the row after the snapshot but before `applied_at` is set. No DB constraint prevents `applied_at IS NOT NULL AND cancelled_at IS NOT NULL` simultaneously.

**Fix:** Use `SELECT ... FOR UPDATE SKIP LOCKED` in `get_pending_scheduled_prices_due`, or add a DB check constraint: `CHECK (applied_at IS NULL OR cancelled_at IS NULL)`.

---

### [HIGH-4] N+1 query on `GET /api/products`

**File:** `backend/app/api/routes.py:101-115`

On every cache miss: `get_all_products()` runs 1 query, then `get_last_successful_price(product.id)` runs 1 per product. 20 products = 21 round-trips. With a 30-second cache TTL and the scheduler invalidating the cache on every price write, this runs frequently.

**Fix:** Add a single repository method using `DISTINCT ON (product_id)` or a lateral join to fetch all latest prices in one query.

---

### [HIGH-5] Settings `lru_cache` prevents config changes from taking effect

**File:** `backend/app/config.py:94-96`

`get_settings()` is cached forever after first call. New products added to `config.yaml`, Slack webhook rotation, or threshold changes are never reflected without a restart. This is undocumented.

**Fix (minimal):** Document "restart required on config change" clearly in CLAUDE.md and README.  
**Fix (robust):** Add a `SIGHUP` handler that calls `get_settings.cache_clear()` and reinitializes the notifier.

**Also:** `Settings` is mutable (Pydantic v2 default). Add `frozen=True` to `SettingsConfigDict` to prevent accidental mutation of the cached singleton.

---

### [MEDIUM-1] Currency mismatch silently ignored in price drop detection

**File:** `backend/app/comparison/detector.py:39-57`

If a product's previous price was scraped in CAD and the current scrape returns USD, `detect_price_drop` compares raw numbers across currencies and may fire a false notification. Currency is not compared.

**Fix:**
```python
if previous.currency != current.currency:
    return None  # and log a warning
```

---

### [MEDIUM-2] Demo drop endpoint bypasses advisory lock guard

**File:** `backend/app/api/routes.py:279-294`

`/api/demo/drop` calls `detect_price_drop` + `notifier.send()` directly without `_run_drop_detection_and_notify`. There is no `pg_try_advisory_xact_lock` and no `session.refresh` check. Two concurrent demo-drop requests on the same product can both read `notified=False` and both send Slack messages before either commits.

**Fix:** Route through `_run_drop_detection_and_notify` like the scheduler does, or add the advisory lock around the check.

---

### [MEDIUM-3] `get_or_create_product` rollback is session-wide

**File:** `backend/app/storage/repository.py:51-55`

On `IntegrityError`, `await self._session.rollback()` rolls back the entire session transaction (not a savepoint). Any other unflushed work in the same session before this call is silently discarded.

**Fix:** Wrap the insert+flush in `async with session.begin_nested()` so the rollback scope is limited to the nested savepoint.

---

### [MEDIUM-4] N+1 in force-check ID validation

**File:** `backend/app/api/routes.py:335-339`

When `product_ids` is provided, one `get_product_by_id` query runs per ID in a Python loop. 50 IDs = 50 sequential queries.

**Fix:** Add `get_products_by_ids(ids: list[int])` using `WHERE id = ANY(:ids)`.

---

## Part 2 — Security Audit

### [HIGH-S1] No authentication — full API is open

**File:** All routes in `api/routes.py`, `main.py`

If Caddy is bound to a public IP without an IP allowlist or basic-auth, anyone can:
- Spam Slack via `/api/demo/drop` (rate-limited, but per-IP; distributed callers bypass it)
- Force Amazon scrapes via `force-check` (burns proxy quota, risks Amazon IP ban)
- Enumerate all watched products and their price history
- Tail live runtime logs via `/api/logs`

**Fix (choose one):**
- Add IP allowlist in Caddy config (allowlist your home IP)
- Add FastAPI middleware with `X-API-Key: <secret>` header using `secrets.compare_digest`

Document which protection is in place.

---

### [HIGH-S2] SSRF surface on `image_url` field

**File:** `backend/app/api/routes.py:205-239`

`image_url` validator only checks `^https?://` scheme. Any URL is accepted and stored. The backend does not currently fetch image URLs, but:
- The frontend will load the URL (tracking pixel / CSRF vector against internal hosts the user's browser can reach)
- Any future server-side image proxying / dimension-checking would become full SSRF against the internal 10.20.x.x network

**Fix:** Validate host against RFC1918/loopback/link-local denylist, or restrict to an Amazon image CDN allowlist:
```python
ALLOWED_IMAGE_HOSTS = {
    "m.media-amazon.com", "images-na.ssl-images-amazon.com",
    "images-amazon.com", "example.com",  # add your CDN hosts
}
```

---

### [HIGH-S3] Force-check and product-add endpoints have no global rate limit

**File:** `backend/app/api/routes.py:154-202` (POST /api/products), `:315-361` (force-check)

`POST /api/products` has no rate limit at all. `force-check` is limited 10/minute per IP, but with `all=true` a single caller can queue all products 10× per minute continuously. Both can be used to amplify Amazon scraping costs.

**Fix:**
- Add `@limiter.limit("20/minute")` to `POST /api/products`
- Add `Field(max_length=200)` to `AddProductRequest.name`
- Add a global cap on `force-check all=true` (e.g. max 1 `all=true` per 5 minutes)

---

### [MEDIUM-S1] Slack notification message injection

**File:** `backend/app/notifications/slack.py:31`

Current sanitisation strips `<`, `>`, `|` from product names but does NOT neutralise `@channel`, `@here`, `*bold*`, `_italic_`, or `&lt;!channel&gt;` Slack mentions. Product names are user-controlled via `POST /api/products`.

**Fix:** Switch the product name text block from `mrkdwn` to `plain_text`:
```python
{"type": "section", "text": {"type": "plain_text", "text": safe_name, "emoji": False}}
```
Or add Slack's recommended entity encoding: `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;` before building the mrkdwn link.

---

### [MEDIUM-S2] CORS localhost origins shipped to production

**File:** `backend/app/main.py:33-38`

`allow_origins=["http://localhost:3000", "http://localhost:5173"]` in production means any locally-running page (Electron app, dev server, sidecar) can make cross-origin requests to the API. Combined with no auth, this is exploitable for Slack spam or product injection.

**Fix:** Set `allow_origins` to the actual production frontend host (e.g. `https://amazonscraper.viet.bui`). Gate localhost origins behind an env flag for dev only.

---

### [MEDIUM-S3] `/api/logs` SSE stream leaks operational state unauthenticated

**File:** `backend/app/api/routes.py:470-494`

Anyone who can reach the API can `curl -N /api/logs` and stream every structlog event in real time. Leaks: product URLs (watched-product list), proxy errors (may include proxy hostnames/auth), scrape prices, scheduler internals.

**Fix:** Gate `/api/logs` behind the same auth as the rest of the API. Add a scrubber in `_logbus_processor` to strip URL fields that may contain credentials.

---

### [MEDIUM-S4] Verbose scraper errors persisted to DB and returned to clients

**File:** `backend/app/scraper/amazon.py`, surfaced via `GET /api/products/{id}/history`

Raw exception messages from Playwright (browser paths, proxy host:port, network errors) are stored in `PriceCheck.error_message` and returned unauthenticated via the history endpoint.

**Fix:** Map exception types to short generic codes before persisting: `"blocked"`, `"timeout"`, `"parse_failed"`, `"network"`. Log the full message to structlog for operators.

---

### [MEDIUM-S5] `POST /api/products` missing `name` field length bound

**File:** `backend/app/api/routes.py:75-80`

`name: str` has no `max_length` validator. Arbitrarily large names end up in Redis cache JSON, structlog output, and Slack messages.

**Fix:** `name: str = Field(max_length=200)` on `AddProductRequest`.

---

### [LOW-S1] Amazon TLD regex allows `amazon.evil.com`

**File:** `backend/app/api/routes.py:38-40`

`amazon\.[a-z.]+` matches `amazon.attacker.tld` (the `[a-z.]+` allows dots). An attacker could submit a URL from a domain they control, potentially serving a malicious page to the Playwright scraper.

**Fix:** Use an explicit TLD allowlist: `amazon\.(?:com|co\.uk|de|fr|it|es|ca|com\.au|co\.jp|in|nl|pl|se|sg|com\.mx|com\.br)`.

---

### [LOW-S2] `asyncio.TimeoutError` not caught in `SlackNotifier`

**File:** `backend/app/notifications/slack.py:17-25`

`aiohttp.ClientError` does not cover `asyncio.TimeoutError`. A network timeout bubbles up uncaught, is caught by the outer `except Exception` in `_check_product_config`, and is logged as `price_check.failed` — misleading since the price check succeeded; only the notification failed.

**Fix:**
```python
except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
    raise NotificationError(f"Failed to reach Slack webhook: {type(exc).__name__}") from None
```

---

### [LOW-S3] Slack webhook URL could appear in chained exception

**File:** `backend/app/notifications/slack.py:25`

`raise NotificationError(...) from exc` keeps the chained `aiohttp.ClientResponseError` which may include the webhook URL in `request_info.url`. Future log capture could expose the secret.

**Fix:** Use `from None` to drop the chain: `raise NotificationError(...) from None`.

---

## Part 3 — Architecture / Design Critique

### [HIGH-A1] `notifier.send()` called inside open DB transaction

**File:** `backend/app/scheduler/runner.py:161-163`

`await notifier.send(event)` is called inside `begin_nested()` (which is inside the outer session). The outer `session.commit()` runs at line 227, after the entire `_run_drop_detection_and_notify` call. This means:

1. A Postgres connection is held open across a potentially 10-second Slack HTTP call
2. If Slack is flaky: `send` raises `NotificationError` → `notified=False` never committed → next tick re-detects the same drop → **Slack notification storm**

**Fix:** Set `notified=True` / commit the price check *before* calling `send`. Accept at-most-once delivery (miss one alert is better than spam). ~10 line change.

---

### [HIGH-A2] Scheduler process death is silent

**File:** `backend/app/scheduler/runner.py:486-498`

`run_scheduler()` is a `while True` loop with no top-level `try/except`. An unhandled exception in phase 1-4 exits the task. `asyncio.Task` exceptions are not re-raised until the task is awaited (only at shutdown in `main.py:23`). The API stays up; scraping silently stops; no alert fires.

**Fix:**
```python
async def run_scheduler() -> None:
    while True:
        try:
            ...tick phases...
        except Exception:
            log.exception("scheduler.crashed")
            await asyncio.sleep(30)  # back off before retry
```

---

### [HIGH-A3] Force-check queue is process-local — items lost on restart

**File:** `backend/app/scheduler/queue.py`

`asyncio.Queue` lives in the backend process. A restart (deploy, OOM, crash) drops all queued force-check IDs. Users click "force check," see no confirmation of success/failure, and have to try again.

**Fix (minimal):** Return a queue-depth count in the 202 response so clients know items were accepted. Document that queued items are lost on restart.  
**Fix (robust):** Replace `asyncio.Queue` with a Redis list (`LPUSH`/`LRANGE`). The Redis key already exists for the force lock; using it as a durable queue is a natural extension. Also enables future scheduler/API process split.

---

### [MEDIUM-A1] External I/O inside DB transaction (notification before commit)

Already covered in HIGH-A1 above. The fix also resolves the open-connection risk.

---

### [MEDIUM-A2] Failed notification causes Slack spam on next tick

Already covered in HIGH-A1. Setting `notified=True` before `send()` resolves it.

---

### [MEDIUM-A3] Redis products list cache adds complexity for marginal benefit

**File:** `backend/app/cache.py`

The 30-second TTL plus per-write invalidation means the cache barely stays warm. The scheduler invalidates it on every price check (N products × 1 invalidation per tick). A DB query for 20 products with indexed lookups is ~5ms — cheaper than the cache round-trip on miss (N+1 queries). The `try/except` around every cache call adds noise.

**Recommendation:** Drop the products list cache. Keep the per-product ID→URL Redis map (used for force-lock dedup). If caching is re-added, invalidate only on product add/update/delete — not on price history writes.

---

### [MEDIUM-A4] `Settings` object is mutable but globally cached

**File:** `backend/app/config.py:41-96`

`BaseSettings` in Pydantic v2 is mutable by default. Any code that mutates `get_settings().products` corrupts the shared singleton permanently with no error.

**Fix:**
```python
model_config = SettingsConfigDict(frozen=True, ...)
```

---

### [LOW-A1] Frontend `ApiError` too generic for branching UI logic

**File:** `frontend/src/api/client.ts:5-11`

`throw new Error(\`API error ${res.status}\`)` gives components no way to distinguish 404 (product not found) from 429 (rate limited) from 500 (server error). Each shows "something went wrong."

**Fix:**
```typescript
class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`API error ${status}`)
  }
}
```
Then UI can branch: `catch(e) { if (e instanceof ApiError && e.status === 429) showRateLimitToast() }`.

---

## Part 4 — API / QA Bugs & Test Suite

### [HIGH-Q1] `cancel_scheduled_price` has ORM TOCTOU race

**File:** `backend/app/storage/repository.py:218-232`

SELECT → check `applied_at` → ORM mutation → flush. The scheduler can apply and commit the row between SELECT and flush. The ORM mutation issues a blind `UPDATE WHERE id=?` without a conditional, overwriting the scheduler's `applied_at` with `NULL`.

**Fix:** Replace SELECT+mutate with an atomic conditional UPDATE:
```sql
UPDATE scheduled_prices
SET cancelled_at = :now, cancel_reason = :reason
WHERE id = :id AND applied_at IS NULL AND cancelled_at IS NULL
RETURNING id
```
Return `True` only if 1 row returned.

---

### [HIGH-Q2] `get_or_create_product` re-fetch uses `scalar_one()` — can 500 on tight race

**File:** `backend/app/storage/repository.py:54`

After IntegrityError rollback, `scalar_one()` raises `NoResultFound` if the concurrent inserter hasn't committed yet (extremely tight window). The result is an unhandled 500 to the client.

**Fix:** Change to `scalar_one_or_none()` and retry once with a short sleep, or return an error the client can retry.

---

### [MEDIUM-Q1] Duplicate `POST /api/products` always returns 201

**File:** `backend/app/api/routes.py:154`

`status_code=201` is hardcoded on the decorator. When `get_or_create_product` returns `created=False` (existing product), the response is still 201. Should be 200 for an existing resource.

**Fix:**
```python
from fastapi import Response

async def add_product(body, session, response: Response):
    product, created = await repo.get_or_create_product(...)
    if not created:
        response.status_code = 200
    ...
```

---

### [MEDIUM-Q2] Empty `product_ids=[]` gives misleading 400 error message

**File:** `backend/app/api/routes.py:341`

`elif body.product_ids:` — an empty list is falsy. Client receives `"Provide product_ids or all=true"` even though they did provide the field.

**Fix:** `elif body.product_ids is not None:` then `if not body.product_ids: raise HTTPException(400, "product_ids must not be empty")`.

---

### [MEDIUM-Q3] `demo/drop` skips Amazon URL validation

**File:** `backend/app/api/routes.py:250`

`add_product` validates with `_AMAZON_ASIN_URL_RE`. `demo/drop` skips validation — a bad URL returns 404 instead of 400. Incorrect error semantics.

**Fix:** Add the same `_AMAZON_ASIN_URL_RE` check at the top of `demo_drop`.

---

### [MEDIUM-Q4] Rate limiter uses client IP — broken behind reverse proxy

**File:** `backend/app/api/routes.py:35` (`get_remote_address`)

Behind Caddy, all requests may appear from the proxy's IP. All users share one rate-limit bucket, making the rate limiter either too restrictive (1 user trips it for everyone) or ineffective (limits don't apply per-user).

**Fix:** Configure slowapi to trust the `X-Forwarded-For` header:
```python
from slowapi.util import get_remote_address
# or use a custom key func that reads X-Forwarded-For
```
Also configure Caddy to set `X-Forwarded-For`.

---

## Complete Curl Test Suite

Copy-paste reference. Set `BASE` to your backend URL.

```bash
BASE="http://10.20.0.3:8000"

# ── Products ─────────────────────────────────────────────────────────────────

# Add valid product → 201
curl -s -w "\n%{http_code}" -X POST "$BASE/api/products" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B08N5WRWNW","name":"Echo Dot","initial_price":49.99}'

# Add same product again → BUG: 201 (should be 200)
curl -s -w "\n%{http_code}" -X POST "$BASE/api/products" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B08N5WRWNW","name":"Echo Dot"}'

# Non-Amazon URL → 400
curl -s -w "\n%{http_code}" -X POST "$BASE/api/products" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.ebay.com/itm/123","name":"eBay item"}'

# Amazon URL without ASIN → 400
curl -s -w "\n%{http_code}" -X POST "$BASE/api/products" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/s?k=headphones","name":"Search"}'

# Slug URL normalised → 201, stored as https://www.amazon.com/dp/B08N5WRWNW
curl -s -w "\n%{http_code}" -X POST "$BASE/api/products" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/Echo-Dot/dp/B08N5WRWNW?ref=pd","name":"Slug test"}'

# Missing required field → 422
curl -s -w "\n%{http_code}" -X POST "$BASE/api/products" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B08N5WRWNW"}'

# List products → 200
curl -s -w "\n%{http_code}" "$BASE/api/products" | jq

# Price history → 200
curl -s -w "\n%{http_code}" "$BASE/api/products/1/history?limit=10" | jq

# History non-existent product → 404
curl -s -w "\n%{http_code}" "$BASE/api/products/99999/history"

# History limit=0 → 422
curl -s -w "\n%{http_code}" "$BASE/api/products/1/history?limit=0"

# Update image (valid https) → 200
curl -s -w "\n%{http_code}" -X PATCH "$BASE/api/products/1/image" \
  -H "Content-Type: application/json" \
  -d '{"image_url":"https://m.media-amazon.com/images/I/test.jpg"}'

# Update image (javascript: scheme) → 422
curl -s -w "\n%{http_code}" -X PATCH "$BASE/api/products/1/image" \
  -H "Content-Type: application/json" \
  -d '{"image_url":"javascript:alert(1)"}'

# Clear image → 200
curl -s -w "\n%{http_code}" -X PATCH "$BASE/api/products/1/image" \
  -H "Content-Type: application/json" \
  -d '{"image_url":null}'

# ── Force Check ───────────────────────────────────────────────────────────────

# Force specific IDs → 202
curl -s -w "\n%{http_code}" -X POST "$BASE/api/products/force-check" \
  -H "Content-Type: application/json" \
  -d '{"product_ids":[1,2]}'

# Force all → 202
curl -s -w "\n%{http_code}" -X POST "$BASE/api/products/force-check" \
  -H "Content-Type: application/json" \
  -d '{"all":true}'

# Empty body → 400
curl -s -w "\n%{http_code}" -X POST "$BASE/api/products/force-check" \
  -H "Content-Type: application/json" \
  -d '{}'

# Empty list → BUG: 400 with misleading message
curl -s -w "\n%{http_code}" -X POST "$BASE/api/products/force-check" \
  -H "Content-Type: application/json" \
  -d '{"product_ids":[]}'

# Non-existent IDs → 202 with not_found list
curl -s -w "\n%{http_code}" -X POST "$BASE/api/products/force-check" \
  -H "Content-Type: application/json" \
  -d '{"product_ids":[99999]}'

# ── Demo Drop ─────────────────────────────────────────────────────────────────

# Drop below previous price → 200, notification_sent: true
curl -s -w "\n%{http_code}" -X POST "$BASE/api/demo/drop" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B08N5WRWNW","price":29.99}'

# Drop on product with no prior price → 200, notification_sent: false
curl -s -w "\n%{http_code}" -X POST "$BASE/api/demo/drop" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B09NEWPRODUCT","price":19.99}'

# Price HIGHER than previous → 200, notification_sent: false
curl -s -w "\n%{http_code}" -X POST "$BASE/api/demo/drop" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B08N5WRWNW","price":199.99}'

# Non-existent product → 404
curl -s -w "\n%{http_code}" -X POST "$BASE/api/demo/drop" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B00000FAKE","price":9.99}'

# price=0 → 422
curl -s -w "\n%{http_code}" -X POST "$BASE/api/demo/drop" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B08N5WRWNW","price":0}'

# ── Scheduled Prices ──────────────────────────────────────────────────────────

# Schedule 60s → 201
curl -s -w "\n%{http_code}" -X POST "$BASE/api/scheduler/prices" \
  -H "Content-Type: application/json" \
  -d '{"product_id":1,"price":39.99,"seconds":60}'

# Schedule via URL + minutes → 201
curl -s -w "\n%{http_code}" -X POST "$BASE/api/scheduler/prices" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B08N5WRWNW","price":35.00,"minutes":5}'

# No time unit → 400
curl -s -w "\n%{http_code}" -X POST "$BASE/api/scheduler/prices" \
  -H "Content-Type: application/json" \
  -d '{"product_id":1,"price":39.99}'

# Non-existent product → 404
curl -s -w "\n%{http_code}" -X POST "$BASE/api/scheduler/prices" \
  -H "Content-Type: application/json" \
  -d '{"product_id":99999,"price":39.99,"seconds":60}'

# price=0 → 422
curl -s -w "\n%{http_code}" -X POST "$BASE/api/scheduler/prices" \
  -H "Content-Type: application/json" \
  -d '{"product_id":1,"price":0,"seconds":60}'

# List pending → 200
curl -s -w "\n%{http_code}" "$BASE/api/scheduler/prices/pending" | jq

# Cancel → 200 (replace 1 with actual ID)
curl -s -w "\n%{http_code}" -X DELETE "$BASE/api/scheduler/prices/1"

# Cancel already-settled → 404
curl -s -w "\n%{http_code}" -X DELETE "$BASE/api/scheduler/prices/1"

# Cancel non-existent → 404
curl -s -w "\n%{http_code}" -X DELETE "$BASE/api/scheduler/prices/99999"

# ── Search ────────────────────────────────────────────────────────────────────

# Valid search → 200
curl -s -w "\n%{http_code}" "$BASE/api/search?q=echo+dot" | jq

# Too short (1 char) → 422
curl -s -w "\n%{http_code}" "$BASE/api/search?q=a"

# Missing param → 422
curl -s -w "\n%{http_code}" "$BASE/api/search"

# Rate limit test (run quickly) → second should be 429
curl -s "$BASE/api/search?q=kindle" &
curl -s -w "\n%{http_code}" "$BASE/api/search?q=kindle"

# ── SSE Logs ──────────────────────────────────────────────────────────────────

# Connect and watch for 5s → 200, Content-Type: text/event-stream
curl -s -N --max-time 5 "$BASE/api/logs"

# ── Errors ────────────────────────────────────────────────────────────────────

# Wrong endpoint → 404
curl -s -w "\n%{http_code}" "$BASE/api/nonexistent"

# Wrong method → 405
curl -s -w "\n%{http_code}" "$BASE/api/products/force-check"

# Malformed JSON → 422
curl -s -w "\n%{http_code}" -X POST "$BASE/api/products" \
  -H "Content-Type: application/json" \
  -d '{bad json here}'

# Raise backend logs — trigger a scrape error by force-checking a bad product ID
curl -s -X POST "$BASE/api/products/force-check" \
  -H "Content-Type: application/json" \
  -d '{"product_ids":[99999]}' && curl -s -N --max-time 5 "$BASE/api/logs"
```

---

## Priority Fix Order

| Priority | Issue | File | Effort |
|---|---|---|---|
| 1 | CORS missing PATCH + DELETE (breaks frontend) | `main.py:36` | 1 line |
| 2 | `asyncio.TimeoutError` not caught in SlackNotifier | `notifications/slack.py:25` | 2 lines |
| 3 | Commit before notify (fixes transaction + spam) | `scheduler/runner.py:155-227` | ~10 lines |
| 4 | Advisory lock — move outside savepoint | `scheduler/runner.py:155` | ~15 lines |
| 5 | `cancel_scheduled_price` atomic UPDATE | `storage/repository.py:218` | ~10 lines |
| 6 | `scalar_one()` → `scalar_one_or_none()` after rollback | `storage/repository.py:54` | 1 line |
| 7 | Freeze `Settings` | `config.py:41` | 1 line |
| 8 | Currency mismatch guard in `detect_price_drop` | `comparison/detector.py:39` | 3 lines |
| 9 | CORS origins locked to prod hostname | `main.py:33` | 2 lines |
| 10 | Rate limit `POST /api/products` + name length bound | `routes.py:154` | 3 lines |
| 11 | Amazon TLD regex allowlist | `routes.py:38` | 1 line |
| 12 | Slack name → `plain_text` block | `notifications/slack.py:31` | 3 lines |
| 13 | N+1 on `GET /api/products` | `routes.py:101` + `repository.py` | ~20 lines |
| 14 | Scheduler crash recovery loop | `scheduler/runner.py:486` | ~5 lines |
| 15 | Auth middleware (API key or Caddy IP allowlist) | `main.py` or Caddy config | varies |

---

## Setup Changes Made This Session

### New: `CLAUDE.md` at project root

Created `/price-checker/CLAUDE.md` — full project context for future sessions:
- Architecture overview (2-LXC topology, Docker services)
- API reference with all endpoints
- Scheduler tick phases
- Common curl commands
- Deployment notes

### New: `~/.claude/skills/price-checker-context/SKILL.md`

Project-specific skill. Invoke with `/price-checker-context` to load full project context at session start without re-explaining the architecture.

### Recommended Hooks (not yet applied)

Add to `.claude/settings.local.json` under `"hooks"`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{
          "type": "command",
          "command": "cd /Users/vietquocbui/repos/VsCode/vietbui1999ru/Portfolio/price-checker/backend && .venv/bin/python -m ruff check app/ --quiet 2>&1 | tail -5"
        }]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{
          "type": "command",
          "command": "python3 -c \"import sys,json,os; d=json.load(sys.stdin); f=d.get('file_path',''); sys.exit(1 if '.env' in os.path.basename(f) and 'example' not in f else 0)\""
        }]
      }
    ]
  }
}
```

---

*Report generated by: code-reviewer + security-auditor + design-critic + api-tester agents, synthesised 2026-04-29*
