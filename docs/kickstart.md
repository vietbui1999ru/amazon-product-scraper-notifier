# Kickstart Guide

Quick setup, smoke test, and endpoint reference for the Price Drop Monitor.

---

## 1. Prerequisites

- Docker + Docker Compose
- A Slack incoming webhook URL (optional — console notifications work without it)

---

## 2. Environment setup

```bash
cp .env.example .env
```

Edit `.env`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/pricecheck
REDIS_URL=redis://localhost:6379
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

Slack webhook is optional. If omitted, notifications print to console only.

---

## 3. Start all services

```bash
docker compose up --build
```

Services:
- **postgres** → `localhost:5433`
- **redis** → `localhost:6379`
- **backend** → `http://localhost:8000`
- **frontend** → `http://localhost:3000`

On first run, Alembic migrations run automatically inside the backend container.

---

## 4. Verify backend is up

```bash
curl http://localhost:8000/api/products
```

Expected: `[]` (empty array on a fresh DB).

---

## 5. Endpoint reference with curl examples

### Add a product

```bash
curl -s -X POST http://localhost:8000/api/products \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.amazon.com/dp/B09XWXM8R8",
    "name": "LEGO Speed Champions Aston Martin",
    "initial_price": 39.99
  }' | jq
```

- `url` must be a valid Amazon `/dp/ASIN` URL.
- `initial_price` is optional — sets a starting price record so the chart is not empty.
- Returns the created `Product` object.

---

### List all products

```bash
curl -s http://localhost:8000/api/products | jq
```

---

### Get price history for a product

```bash
# Replace 1 with the actual product ID
curl -s "http://localhost:8000/api/products/1/history?limit=50" | jq
```

---

### Force scrape (queue a live Amazon price check)

```bash
# Specific products
curl -s -X POST http://localhost:8000/api/products/force-check \
  -H "Content-Type: application/json" \
  -d '{"product_ids": [1, 2]}' | jq

# All products
curl -s -X POST http://localhost:8000/api/products/force-check \
  -H "Content-Type: application/json" \
  -d '{"all": true}' | jq
```

Result appears in `/api/logs` SSE stream and updates the chart after the next `refetchInterval`.

---

### Simulate a price drop (demo — triggers notification immediately)

```bash
curl -s -X POST http://localhost:8000/api/demo/drop \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.amazon.com/dp/B09XWXM8R8",
    "price": 29.99
  }' | jq
```

- `url` must match a product already in the DB.
- Sets a fake price record in the DB and fires the notifier if the price is lower than the previous record.
- Returns: `{ product, old_price, new_price, notification_sent }`.

**To trigger Slack:** set `notifications.method: "slack"` (or `["console", "slack"]`) in `config.yaml` and set `SLACK_WEBHOOK_URL` in `.env`. Then call the endpoint above.

---

### Schedule a future price update

```bash
# Price takes effect in 60 seconds
curl -s -X POST http://localhost:8000/api/scheduler/prices \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": 1,
    "price": 24.99,
    "seconds": 60
  }' | jq

# Or use minutes
curl -s -X POST http://localhost:8000/api/scheduler/prices \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": 1,
    "price": 24.99,
    "minutes": 5
  }' | jq
```

The scheduler tick runs every 30s (configurable in `config.yaml`). When `scheduled_for` passes, the price is applied and the notifier fires if it's a drop.

---

### List pending scheduled prices

```bash
curl -s http://localhost:8000/api/scheduler/prices/pending | jq
```

---

### Cancel a scheduled price

```bash
# Replace 3 with the scheduled price ID from the pending list
curl -s -X DELETE http://localhost:8000/api/scheduler/prices/3 | jq
```

---

### Update a product's image URL

```bash
curl -s -X PATCH http://localhost:8000/api/products/1/image \
  -H "Content-Type: application/json" \
  -d '{"image_url": "https://m.media-amazon.com/images/I/example.jpg"}' | jq

# Clear the image
curl -s -X PATCH http://localhost:8000/api/products/1/image \
  -H "Content-Type: application/json" \
  -d '{"image_url": null}' | jq
```

URL must be `http://` or `https://`. Non-http URLs are rejected with 422.

---

### Stream backend logs (SSE)

```bash
# In a separate terminal — streams structured log events in real time
curl -N http://localhost:8000/api/logs
```

Each line is a JSON log event. Useful to watch scraper results, scheduler ticks, and notification delivery live.

---

### Search Amazon (live scrape)

```bash
curl -s "http://localhost:8000/api/search?q=LEGO+speed+champions" | jq
```

Rate-limited to 1/second. Returns scraped search results from Amazon.

---

## 6. Notification setup

### Console only (default)

`config.yaml`:
```yaml
notifications:
  method: "console"
```

Notifications print to the backend container stdout. View with `docker compose logs -f backend`.

### Slack only

```yaml
notifications:
  method: "slack"
  slack_webhook_url: ""   # or set via SLACK_WEBHOOK_URL env var
```

### Both console + Slack simultaneously

```yaml
notifications:
  method: ["console", "slack"]
  slack_webhook_url: ""
```

### Verify Slack is working

1. Add a product with an initial price:
```bash
curl -X POST http://localhost:8000/api/products \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.amazon.com/dp/B09XWXM8R8", "name": "Test", "initial_price": 50.00}'
```

2. Trigger a demo drop below the initial price:
```bash
curl -X POST http://localhost:8000/api/demo/drop \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.amazon.com/dp/B09XWXM8R8", "price": 35.00}'
```

3. Check response: `"notification_sent": true` means the notifier ran. Check Slack channel for the Block Kit message.

**If `notification_sent` is false:** the new price was not lower than the previous record. Use a price strictly lower than the last recorded value.

---

## 7. Running tests

From inside the backend container or with the project venv active:

```bash
cd backend
pytest tests/ -v
```

Tests use SQLite in-memory and do not require Postgres or Redis.

---

## 8. Config reference

Key fields in `config.yaml`:

| Field | Default | Notes |
|---|---|---|
| `scheduler.check_interval_seconds` | `30` | Seconds between scrape cycles. Use `300` for production. |
| `notifications.method` | `"console"` | `"console"`, `"slack"`, or `["console", "slack"]` |
| `notifications.slack_webhook_url` | `""` | Override with `SLACK_WEBHOOK_URL` env var |
| `notifications.price_drop_threshold_percent` | `1.0` | Minimum % drop to trigger alert (0.0 = any drop) |
| `notifications.price_drop_threshold_absolute` | `0.0` | Minimum $ drop to trigger alert |
| `scraper.proxies` | `[]` | Proxy list for rotation. Override with `PROXY_LIST` env var |
