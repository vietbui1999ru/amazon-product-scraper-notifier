# Price Checker

A personal homelab tool that scrapes Amazon product prices on a schedule, detects drops relative to the last known price, and fires notifications when thresholds are met.

## Language

**Price Drop**:
A price decrease relative to the most recently recorded successful scrape of the same product. Not compared to lowest-ever price, initial price, or any external baseline. If a product goes $100 → $80 → $90, then $89 would be flagged as a drop (from $90, the last recorded price).
_Avoid_: sale, discount, deal

**Threshold**:
The minimum drop magnitude required to fire a notification. Two independent thresholds: `threshold_percent` (% decrease) and `threshold_absolute` (dollar decrease). A drop fires if it meets EITHER. If both are 0, any positive drop fires.
_Avoid_: sensitivity, trigger level

**Comparison Baseline**:
The price used as "previous" when detecting a drop. Always the last successful **Amazon scrape** — demo drops and scheduled prices never become the baseline. This prevents injected prices from polluting future Amazon comparisons. If no Amazon scrape exists yet, no comparison is made (no notification).
_Avoid_: last price, previous price (too ambiguous about source)

**Price Entry**:
Three distinct ways a price enters the system, with different source values and behaviors:
1. **Live scrape** (`source="amazon"`) — Playwright hits Amazon; respects configured thresholds; cancels pending scheduled prices for that product
2. **Scheduled price** (`source="self"`) — user-created `ScheduledPrice` row, fired by scheduler Phase 2; respects configured thresholds
3. **Demo drop** (`source="self"`) — immediate injection via `/api/demo/drop`; bypasses configured thresholds (any positive drop notifies); used to test the notification pipeline
_Avoid_: fake price, injected price (use "demo drop" specifically)

**Notification Guard**:
The mechanism preventing double-sends when two concurrent scrapes of the same product both detect a drop. Implemented via `pg_try_advisory_xact_lock(product_id)` — a PostgreSQL transaction-scoped advisory lock. Only one concurrent writer wins; the other skips notification silently.
_Avoid_: notification_lock (removed dead DB column), mutex
