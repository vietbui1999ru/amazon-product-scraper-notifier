# Price Drop Monitor

A small full-stack application that monitors a configurable list of Amazon products on a periodic schedule, persists every observed price, detects drops against the previous observation, and sends a notification (console or Slack webhook) when a drop crosses a configured threshold. A React dashboard renders the price history per product.

---

###  Personal discussion regarding Design choices and how AI helped or failed and Code Analyses (AI generated).
 1. [Design choices](/Design-doc.md)
 2. [AI choices](/AI-doc.md)
 3. [AI-generated Code Analyses](/ANALYSIS.md)

---

# TODO: Add demo images/gif/video

---

## Requirements

- Docker + Docker Compose (recommended)
- OR for manual setup: Python 3.11+, Node 20+, PostgreSQL 16

## Quick Start (Docker)

```bash
git clone <repo-url> price-checker
cd price-checker
cp .env.example .env
docker compose up --build
```

Once the stack is healthy:

- Backend API: http://localhost:8000/api/products
- Dashboard:  http://localhost:3000

The scheduler starts automatically inside the backend container and begins checking prices on the configured interval (default 300 seconds).

To tail logs for just the scraper:

```bash
docker compose logs -f backend
```

To stop the stack and wipe the database volume:

```bash
docker compose down -v
```

## Manual Setup

### Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

# Start Postgres separately (or via `docker compose up postgres`)
export DATABASE_URL=postgresql+asyncpg://pricechecker:pricechecker@localhost:5432/pricechecker
alembic upgrade head

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server proxies `/api/*` to `http://localhost:8000`.

## Configuration

All runtime configuration lives in `config.yaml` at the repo root. Environment variables in `.env` override a subset of these for deployment.

`config.yaml` fields:

| Field | Description |
| --- | --- |
| `products[].url` | Amazon product URL (canonical `/dp/<ASIN>` form preferred) |
| `products[].name` | Display name shown in the dashboard and notifications |
| `scheduler.check_interval_seconds` | Seconds between full check cycles (default 300) |
| `notifications.method` | `console`, `slack`, or `["console", "slack"]` |
| `notifications.slack_webhook_url` | Required when `method = slack` (or use `SLACK_WEBHOOK_URL` env var) |
| `notifications.price_drop_threshold_percent` | Drop must exceed this percentage to notify |
| `notifications.price_drop_threshold_absolute` | Drop must exceed this absolute dollar amount to notify |
| `scraper.proxies` | List of proxy URLs for rotation (`http://user:pass@host:port`) |
| `scraper.headless` | Run Chromium headless (default `true`) |
| `scraper.timeout_ms` | Playwright page timeout in milliseconds (default `30000`) |
| `scraper.min_delay_seconds` | Minimum random delay between requests (default `1.0`) |
| `scraper.max_delay_seconds` | Maximum random delay between requests (default `5.0`) |

Environment overrides (see `.env.example`):

| Variable | Overrides |
| --- | --- |
| `DATABASE_URL` | DB connection string (SQLAlchemy async URL) |
| `SLACK_WEBHOOK_URL` | `notifications.slack_webhook_url` |
| `LOG_LEVEL` | structlog level (`DEBUG`, `INFO`, `WARNING`) |
| `CORS_ORIGINS` | Comma-separated allowed origins (default: localhost:3000,localhost:5173) |
| `API_KEY` | If set, all requests must include `X-API-Key: <value>` header |
| `PROXY_LIST` | Comma-separated proxy URLs; overrides `scraper.proxies` in config.yaml |
| `REDIS_URL` | Redis connection URL (default: `redis://redis:6379`) |

Adding or removing a product is a `config.yaml` edit + restart — no code change required.

## Verifying It Works

The fastest way to confirm a notification fires end-to-end without waiting for a real Amazon price drop:

1. Set a short interval and switch to console notifications:

   ```bash
   echo "CHECK_INTERVAL_SECONDS=10" >> .env
   ```
   In `config.yaml`, set `notifications.method: console` and `price_drop_threshold_percent: 0.1`.

2. Start the stack: `docker compose up --build`.

3. Add a product via the dashboard or API, then wait one scheduler cycle so a real price row exists.

4. Inject a fake price drop and fire the notifier immediately:

   ```bash
   # List products and their current prices
   docker compose exec backend python scripts/demo_drop.py --list

   # Inject a 20% drop on product ID 1 and send a notification
   docker compose exec backend python scripts/demo_drop.py --id 1 --pct 20
   ```

   The injected row has `source=self` and is visible in the dashboard chart with an amber **[self]** badge. Look for the `DROP` log line in `docker compose logs -f backend` or the Slack alert.

5. Confirm the drop surfaces in the dashboard chart at http://localhost:3000.

## Running Tests

```bash
cd backend
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Test suites:

| File | What it covers |
| --- | --- |
| `tests/test_scraper.py` | Selector cascade + price normalization on cached HTML fixtures |
| `tests/test_storage.py` | Repository inserts, history ordering, advisory-lock guard |
| `tests/test_comparison.py` | Drop detector thresholds (percent, absolute, both) |
| `tests/test_notifications.py` | Console + Slack notifier formatting and error handling |
| `tests/test_api.py` | FastAPI route contracts (products, history) |

CI (`.github/workflows/ci.yml`) runs the same `pytest` suite against a live Postgres 16 service container on every push, plus a frontend `tsc --noEmit` typecheck.

## API Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/products` | List all tracked products with latest price |
| `POST` | `/api/products` | Add a product by URL |
| `GET` | `/api/products/{id}/history` | Price history for a product (`?limit=N`, max 1000) |
| `POST` | `/api/products/force-check` | Queue immediate scrape; body: `{"product_ids":[1,2]}` or `{"all":true}` |
| `GET` | `/api/search` | Search Amazon by keyword |
| `POST` | `/api/demo/drop` | Inject a fake price drop and fire the notifier |
| `POST` | `/api/scheduler/prices` | Schedule a future price change; body: `{"product_id":1,"price":39.99,"minutes":5}` |
| `GET` | `/api/scheduler/prices/pending` | List pending scheduled prices |
| `DELETE` | `/api/scheduler/prices/{id}` | Cancel a scheduled price manually |
| `GET` | `/api/logs` | SSE stream of structured log events |

## Scripts

All scripts run inside the backend container (recommended) or locally with the backend virtualenv active and `DATABASE_URL` set.

### simulate_price_walk.py — generate price history for charts

Inserts historical `price_checks` rows backward in time with random walk, source=`simulated`. Simulated points render as a dashed grey line in the chart.

```bash
# List product IDs first
docker compose exec backend python scripts/demo_drop.py --list

# Generate 30 days of history at ±5% volatility per 30-min step (~1440 rows)
docker compose exec backend python scripts/simulate_price_walk.py --id 1 --days 30 --volatility 5

# Higher volatility for a more dramatic chart
docker compose exec backend python scripts/simulate_price_walk.py --id 1 --days 14 --volatility 10
```

Requires at least one real price row to exist (run the scheduler once, or use `demo_drop.py` to seed a price first). The walk starts from the current latest price and goes backward.

### demo_drop.py — inject a price drop and fire notifications

Inserts a `price_checks` row at a lower price (source=`self`) and immediately fires the configured notifier (Slack or console).

```bash
# List tracked products and their current prices
docker compose exec backend python scripts/demo_drop.py --list

# Drop product 1 by 20% and send notification
docker compose exec backend python scripts/demo_drop.py --id 1 --pct 20

# Drop all products by 15% (default)
docker compose exec backend python scripts/demo_drop.py --pct 15
```

The threshold check is bypassed — any positive drop fires the notifier regardless of `price_drop_threshold_percent` in config.

### schedule_price.py — schedule a future price change

Inserts a row into `scheduled_prices`. The scheduler picks it up at the next tick after `scheduled_for`, inserts a `price_checks` row with source=`self`, runs drop detection, then marks it applied. If a real Amazon scrape happens before the scheduled time, the scheduled row is cancelled automatically.

```bash
# Schedule product 1 to drop to $39.99 in 5 minutes
docker compose exec backend python scripts/schedule_price.py --id 1 --price 39.99 --minutes 5

# Same but by URL
docker compose exec backend python scripts/schedule_price.py \
  --url "https://www.amazon.com/dp/B07RW6Z692" --price 39.99 --minutes 10

# Check pending scheduled prices
curl http://localhost:8000/api/scheduler/prices/pending
```

### Manual price edit via psql

To set an exact price directly in the DB (no notification fired):

```bash
docker compose exec postgres psql -U pricechecker -d pricechecker
```

```sql
-- See current prices
SELECT p.id, p.name, pc.price, pc.scraped_at, pc.source
FROM products p
LEFT JOIN price_checks pc ON pc.id = (
  SELECT id FROM price_checks
  WHERE product_id = p.id AND scrape_success = true AND price IS NOT NULL
  ORDER BY scraped_at DESC, id DESC LIMIT 1
);

-- Insert a manual price row (source=self, no notification)
INSERT INTO price_checks (product_id, price, currency, scrape_success, source)
VALUES (1, 49.99, 'USD', true, 'self');
```

To trigger a notification after a manual insert, use `demo_drop.py` instead — it builds and fires the notifier event in the same step.

## Architecture Overview

- **Scraper** — Playwright + playwright-stealth v2, 5-selector cascade per product
- **Storage** — Postgres 16 via async SQLAlchemy 2.0 + asyncpg; Alembic migrations
- **Scheduler** — 4-phase asyncio loop (force queue drain → apply scheduled prices → normal scrape → cleanup); 300s default interval
- **Comparison** — pure function comparing latest two persisted observations
- **Notifications** — pluggable via factory: `console` or `slack` (extensible)
- **API** — FastAPI; see endpoint table above
- **Frontend** — React + Vite dashboard with per-product price history charts; source badges (amazon/self/simulated) in chart tooltip; dashed line for simulated data points
- **Concurrency dedup** — `pg_try_advisory_xact_lock` + `notified` boolean flag prevents duplicate notifications across restarts or parallel workers
- **Migrations** — auto-run at container start via entrypoint; set `RUN_MIGRATIONS=false` to skip

See `DESIGN.md` for the tradeoffs and `AI-NOTES.md` for honest AI-collaboration notes.
