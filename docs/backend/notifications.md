---
title: "Notifications"
description: "Notifier interface, PriceDropEvent, SlackNotifier, ConsoleNotifier, factory, and dedup semantics."
tags: [backend, notifications, slack]
updated: 2026-04-28
---

# Notifications

`app/notifications/`

---

## PriceDropEvent

`app/comparison/detector.py`

Frozen dataclass passed to all notifiers.

| Field | Type | Description |
|---|---|---|
| `product_id` | `int` | DB primary key |
| `product_name` | `str` | Product name as stored |
| `product_url` | `str` | Canonical Amazon URL |
| `old_price` | `Decimal` | Previous successful price |
| `new_price` | `Decimal` | Current price |
| `drop_amount` | `Decimal` | `old_price - new_price` |
| `drop_percent` | `float` | `(drop_amount / old_price) * 100` |
| `currency` | `str` | Three-letter code (e.g. `"USD"`) |

---

## AbstractNotifier

`app/notifications/base.py`

```python
class AbstractNotifier(ABC):
    @abstractmethod
    async def send(self, event: PriceDropEvent) -> None: ...

    @property
    @abstractmethod
    def name(self) -> str: ...
```

All notifiers implement `send` (async, no return value) and `name` (string identifier). `send` must not raise on network errors — it should raise `NotificationError` from `app/notifications/errors.py` so callers can handle it uniformly.

---

## SlackNotifier

`app/notifications/slack.py`

```python
class SlackNotifier(AbstractNotifier):
    def __init__(self, webhook_url: str) -> None
```

Sends a Block Kit payload to the configured Slack incoming webhook URL.

**HTTP**: `POST {webhook_url}` with JSON body, 10-second total timeout (`aiohttp.ClientTimeout(total=10)`).

**Payload structure**

```json
{
  "blocks": [
    { "type": "header", "text": { "type": "plain_text", "text": "Price Drop Alert 🎉" } },
    {
      "type": "section",
      "text": { "type": "mrkdwn", "text": "*<{url}|{safe_name}>*" },
      "fields": [
        { "type": "mrkdwn", "text": "*Old Price*\nUSD 29.99" },
        { "type": "mrkdwn", "text": "*New Price*\nUSD 19.99" },
        { "type": "mrkdwn", "text": "*Savings*\nUSD 10.00" },
        { "type": "mrkdwn", "text": "*Drop %*\n33.4%" }
      ]
    },
    { "type": "context", "elements": [{ "type": "mrkdwn", "text": "Monitored by Price Drop Monitor" }] }
  ]
}
```

**`safe_name` sanitization**: strips `<`, `>`, and `|` from the product name before embedding it in the Slack mrkdwn link. This prevents malformed Slack links when the name contains those characters.

**Errors**: raises `NotificationError` on non-2xx HTTP status or `aiohttp.ClientError`.

---

## ConsoleNotifier

`app/notifications/console.py`

```python
class ConsoleNotifier(AbstractNotifier)
```

Prints to stdout and emits a structlog event. Used as the default when `notification_method="console"`.

Output format:

```
[PRICE DROP] Echo Dot (4th Gen): $29.99 → $19.99 (33.4% off, save $10.00)
```

Also logs a structured `price_drop_detected` event visible in the SSE log stream.

---

## Factory

`app/notifications/factory.py`

```python
def create_notifier(settings: Settings) -> AbstractNotifier
```

Reads `settings.notification_method` and returns the appropriate notifier:

| `notification_method` | Returns | Raises |
|---|---|---|
| `"console"` | `ConsoleNotifier()` | — |
| `"slack"` | `SlackNotifier(settings.slack_webhook_url)` | `ValueError` if `slack_webhook_url` is empty |
| anything else | — | `ValueError` listing available options |

`create_notifier` is called once at scheduler startup and once per request in `POST /api/demo/drop`.

---

## NotificationError

`app/notifications/errors.py`

```python
class NotificationError(Exception): ...
```

Raised by `SlackNotifier.send()` on delivery failure. Not caught by the scheduler — propagates to `_run_drop_detection_and_notify` and then to the per-product exception handler.

---

## Dedup Semantics

The scheduler uses two complementary mechanisms to prevent duplicate notifications:

1. **`pg_try_advisory_xact_lock(product.id)`** — a Postgres session-level advisory lock held for the duration of the `begin_nested()` savepoint. Only one concurrent caller can hold it at a time per product. The second caller skips the notification silently.

2. **`price_check.notified` flag** — after the lock is acquired, the row is refreshed from DB and `notified` is checked again. If already `True` (set by a previous process), the notification is skipped.

Together these provide **at-least-once** delivery: if the process crashes after `notifier.send()` but before the commit, the notification may fire again on restart. Exactly-once is not guaranteed.
