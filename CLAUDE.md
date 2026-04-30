# Price Checker — Claude Project Context

## Architecture

**2-LXC Proxmox homelab:**
- CT 200 (10.0.0.50/vmbr0, 10.20.0.2/vmbr1): Caddy TLS reverse proxy → domain `amazonscraper.viet.bui`
- CT 201 (10.20.0.3/vmbr1 only): Docker app stack (no public exposure)
- Proxmox host NAT: vmbr1 → vmbr0 for CT 201 internet access (docker pulls, Playwright → Amazon)

**Docker services on CT 201 (`docker-compose.prod.yml`):**
| Service | Role | Port |
|---|---|---|
| `frontend` | React/Vite SPA served by nginx | 10.20.0.3:80 |
| `backend` | FastAPI + async scheduler + Playwright | 10.20.0.3:8000 |
| `postgres` | PostgreSQL 16 — primary DB | internal |
| `redis` | Redis 7 — cache + force-check queue | internal |
| `docs` | Static docs site | internal |

## Key Design Decisions

- **Scheduler runs inside backend process** as an `asyncio.Task` (not separate container). Trade-off: simpler deploy, but scheduler dies if backend crashes.
- **Redis for products list cache** — invalidated on every write. Key: `products:list`. TTL not set; manual invalidation only.
- **PostgreSQL advisory lock** (`pg_try_advisory_xact_lock`) prevents double-send notifications on concurrent scrapes of the same product.
- **Semaphore(1)** in `AmazonScraper` serializes Playwright I/O. Bump to allow more concurrency when using proxies.
- **`source` field** on `PriceCheck`: `"amazon"` = scraped, `"self"` = scheduled/demo. Demo drops never cancel pending scheduled prices.
- **Settings cached** via `lru_cache` — loaded once at startup from `config.yaml` + env. To reload: restart backend.

## Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, structlog, slowapi, Playwright
- **Frontend**: React 18, TypeScript, Vite, Recharts
- **DB**: PostgreSQL 16 (asyncpg driver)
- **Cache/Queue**: Redis 7

## File Map

```
backend/app/
  main.py              # FastAPI app + lifespan (starts scheduler task)
  api/routes.py        # All REST endpoints + SSE log stream
  scheduler/runner.py  # 4-phase tick loop (force → scheduled → normal → cleanup)
  scheduler/queue.py   # asyncio.Queue for force-check IDs
  scraper/amazon.py    # Playwright Amazon scraper
  scraper/search.py    # Amazon search scraping
  notifications/
    factory.py         # create_notifier() — console | slack | multi
    slack.py           # Slack Block Kit webhook
    base.py            # AbstractNotifier
  comparison/detector.py  # detect_price_drop() — OR logic on thresholds
  storage/repository.py   # ProductRepository — all DB queries
  models.py            # Product, PriceCheck, ScheduledPrice (SQLAlchemy mapped)
  cache.py             # Redis helpers (products list, force lock, product URL map)
  config.py            # Settings (pydantic-settings + config.yaml merge)
  database.py          # AsyncSessionLocal, Base, wait_for_db()
  logbus.py            # In-process pub/sub for SSE log stream

frontend/src/
  api/client.ts        # All fetch calls — single source of truth for API shape
  components/          # ProductList, ProductDetail, PriceChart, PriceEditor, SearchBar, SearchResults, Toast
  hooks/               # useProducts, useHistory, useSearch
  types.ts             # Shared TypeScript types
```

## API Reference

All endpoints prefixed `/api`. Backend at `http://10.20.0.3:8000` (CT 201) or via Caddy TLS.

### Products

```bash
# List all tracked products (Redis-cached)
GET  /api/products

# Add product by Amazon URL
POST /api/products
Body: { "url": "https://www.amazon.com/dp/ASINXXXXXX", "name": "...", "image_url": "...", "rating": "...", "initial_price": 49.99 }

# Get price history
GET  /api/products/{id}/history?limit=100

# Update product image
PATCH /api/products/{id}/image
Body: { "image_url": "https://..." }

# Force immediate scrape (adds to Redis queue, scheduler drains on next tick)
POST /api/products/force-check
Body: { "product_ids": [1, 2] }   # or { "all": true }
```

### Search

```bash
# Live Amazon search (rate limit: 1/s per IP)
GET  /api/search?q=lego+technic
```

### Scheduler

```bash
# Schedule a future price entry (triggers notification if it's a drop)
POST /api/scheduler/prices
Body: { "product_id": 1, "price": 29.99, "seconds": 60 }  # or "minutes": N

# List pending scheduled prices
GET  /api/scheduler/prices/pending

# Cancel a scheduled price
DELETE /api/scheduler/prices/{id}
```

### Demo / Dev

```bash
# Inject fake price drop and fire real notification
POST /api/demo/drop
Body: { "url": "https://www.amazon.com/dp/ASIN", "price": 19.99 }

# SSE log stream (structured log events, real-time)
GET  /api/logs
```

## Scheduler Tick Phases

```
Phase 1 → Drain force-check queue (Redis-locked dedup, concurrent Playwright scrapes)
Phase 2 → Apply due scheduled prices (source="self", fires notifier if drop detected)
Phase 3 → Normal scrape cycle (all products in config.yaml, concurrent, skip already-done IDs)
Phase 4 → Cleanup (delete applied/cancelled ScheduledPrice rows older than 30 days)
Interval → config.yaml scheduler.check_interval_seconds (default 300s, demo uses 30s)
```

## Notification System

```
config.yaml notifications.method: "console" | "slack" | ["console", "slack"]
Threshold: drop_percent >= threshold_percent OR drop_amount >= threshold_absolute (OR logic)
Both 0 → any positive drop fires
Slack: Block Kit webhook, 10s timeout
Double-send guard: pg_try_advisory_xact_lock(product_id) per commit
```

## Common curl Commands

```bash
BASE=http://10.20.0.3:8000

# List products
curl $BASE/api/products | jq

# Add product
curl -X POST $BASE/api/products \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B09XWXM8R8","name":"LEGO Aston Martin","initial_price":49.99}'

# Force scrape all
curl -X POST $BASE/api/products/force-check \
  -H "Content-Type: application/json" \
  -d '{"all":true}'

# Demo price drop (fires real Slack notification if configured)
curl -X POST $BASE/api/demo/drop \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B09XWXM8R8","price":29.99}'

# Schedule price in 60s
curl -X POST $BASE/api/scheduler/prices \
  -H "Content-Type: application/json" \
  -d '{"product_id":1,"price":25.00,"seconds":60}'

# Live log stream
curl -N $BASE/api/logs

# Search Amazon
curl "$BASE/api/search?q=lego+speed+champions" | jq
```

## Development Notes

- **Local dev postgres**: exposed on port `5433` (not 5432) to avoid host conflicts
- **Alembic**: `alembic upgrade head` — run via `deploy.sh` or manually inside backend container
- **config.yaml**: mounted read-only into backend container — restart required to pick up changes
- **`shm_size: '256m'`**: required in backend service for Playwright/Chromium renderer
- **`keyctl=1`**: required in CT 201 LXC features for Docker kernel keyring support
- **CORS**: only allows `localhost:3000` and `localhost:5173` — no production wildcard needed (Caddy routes traffic internally)

## Deployment

```bash
# Full deploy (build + migrate + start)
./deploy.sh

# Skip rebuild
./deploy.sh --no-build

# View logs
docker compose -f docker-compose.prod.yml logs -f backend

# Run migrations manually
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
```
