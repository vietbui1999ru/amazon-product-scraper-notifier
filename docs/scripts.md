---
title: "Demo Scripts"
description: "CLI scripts for seeding price history, simulating drops, and scheduling prices."
tags: [scripts, demo, cli]
updated: 2026-04-28
---

# Demo Scripts

Located in `scripts/` at the project root.

All scripts read `DATABASE_URL` from the environment. In Docker Compose, this is set automatically. For local dev, set it in `backend/.env` (note: the local Postgres port is 5433, not the default 5432).

---

## `simulate_price_walk.py`

Inserts synthetic historical price data backward in time for a product.

### Flags

| Flag | Required | Default | Description |
|---|---|---|---|
| `--id` | yes | — | Product ID to generate history for |
| `--days` | no | `30` | How many days back to generate |
| `--volatility` | no | `5` | Max percentage change per 30-minute interval |

### Behaviour

- Looks up the product's most recent successful price check. Exits if none exists.
- Generates `days × 48` rows (one per 30-minute interval, walking backward from now).
- Each step applies a random price change in `[-volatility%, +volatility%]`.
- Price is clamped to a minimum of `$1.00`.
- Rows are inserted with `source="simulated"`, `scrape_success=True`, `notified=False`.
- All rows are committed in a single transaction.
- **No notifications fired.**

### Prerequisites

At least one real `PriceCheck` row must exist for the product (run the scheduler once first).

### Example commands

```bash
# Docker Compose
docker compose exec backend python scripts/simulate_price_walk.py --id 1 --days 30 --volatility 5

# Local (from project root)
cd backend && python ../scripts/simulate_price_walk.py --id 1 --days 30
```

### What it writes to DB

`price_checks` rows only. Source = `simulated`. Approximately `days × 48` rows per run.

---

## `demo_drop.py`

Injects a single fake price drop and fires the configured notifier unconditionally.

### Flags

| Flag | Required | Default | Description |
|---|---|---|---|
| `--list` | no | — | Print all tracked products with latest price, then exit |
| `--id` | no | — | Product ID to target; if omitted, drops all products with price data |
| `--pct` | no | `15` | Drop percentage |

### Behaviour

**`--list` mode**: queries all products and their latest successful price, prints a table, exits without writing anything.

**Drop mode**:
1. Computes `new_price = latest_price × (1 - pct/100)`, rounded to 2 decimal places.
2. Inserts a `PriceCheck` row with `source="self"`, `scrape_success=True`.
3. Constructs a `PriceDropEvent` directly (bypasses `detect_price_drop` thresholds — any amount triggers).
4. Calls `notifier.send(event)` unconditionally.
5. Commits.

The notifier used is whatever is configured in `config.yaml` / env (console or Slack).

### Example commands

```bash
# Docker Compose
docker compose exec backend python scripts/demo_drop.py --list
docker compose exec backend python scripts/demo_drop.py --id 1 --pct 20

# Local
cd backend && python ../scripts/demo_drop.py --list
cd backend && python ../scripts/demo_drop.py --id 1 --pct 15
```

### What it writes to DB

One `PriceCheck` row per targeted product, `source="self"`.

### Side effects

Notification fired via the configured notifier. Unlike the scheduler, this script does NOT use `pg_try_advisory_xact_lock` — if run concurrently, duplicate notifications are possible.

---

## `schedule_price.py`

Inserts a `ScheduledPrice` row. The scheduler applies it at the next tick after `scheduled_for`.

### Flags

| Flag | Required | Default | Description |
|---|---|---|---|
| `--id` | one of | — | Product ID |
| `--url` | one of | — | Product URL (exact match) |
| `--price` | yes | — | Target price (must be > 0) |
| `--minutes` | yes | — | Minutes from now when the price should be applied |

Exactly one of `--id` or `--url` must be provided.

### Behaviour

1. Looks up the product by ID or URL. Exits if not found.
2. Computes `scheduled_for = now(UTC) + timedelta(minutes=minutes)`.
3. Inserts a `ScheduledPrice` row with `currency="USD"`.
4. Commits.

The scheduler's phase 2 picks this up at the next tick after `scheduled_for`.

**Automatic cancellation**: when a real Amazon scrape succeeds for the same product before `scheduled_for`, `cancel_pending_scheduled_prices` is called with `reason="amazon_scrape"`, cancelling this row.

### Example commands

```bash
# Docker Compose
docker compose exec backend python scripts/schedule_price.py --id 1 --price 39.99 --minutes 5
docker compose exec backend python scripts/schedule_price.py --url "https://www.amazon.com/dp/B07RW6Z692" --price 39.99 --minutes 10

# Local
cd backend && python ../scripts/schedule_price.py --id 1 --price 39.99 --minutes 5
```

### What it writes to DB

One `ScheduledPrice` row. No `PriceCheck` row is written until the scheduler applies it.

### Side effects

None at insert time. The scheduler applies the price (writing a `PriceCheck`) and may fire the notifier at `scheduled_for`.

---

## Raw Price Injection (psql)

To inject a price directly without triggering any notification:

```sql
INSERT INTO price_checks (product_id, price, currency, scrape_success, source)
VALUES (1, 49.99, 'USD', true, 'self');
```

`scraped_at` defaults to `now()` server-side. `notified` defaults to `false`. The scheduler will not re-notify for this row unless a subsequent scrape detects a drop against it.
