---
title: "Price Drop Monitor — Documentation Index"
description: "Entry point for all project documentation — backend, frontend, and scripts."
sidebar_position: 1
tags: [index]
updated: 2026-04-28
---

# Price Drop Monitor — Documentation Index

Reference documentation for the Price Drop Monitor project. Covers backend models, API, scheduler, cache, notifications, scraper, frontend components/hooks, and CLI scripts.

---

## Backend

| File | Description |
|---|---|
| [models.md](backend/models.md) | `Product`, `PriceCheck`, `ScheduledPrice` — all fields, constraints, Alembic migration chain |
| [repository.md](backend/repository.md) | `ProductRepository` — every method, SQL behaviour, return type, when to call it |
| [api.md](backend/api.md) | All REST endpoints — request/response shapes, status codes, cache and rate-limit behaviour |
| [scheduler.md](backend/scheduler.md) | Tick loop phases, force queue, scheduled price application, logging format |
| [cache.md](backend/cache.md) | Redis key reference, all cache functions, fail-safe pattern |
| [notifications.md](backend/notifications.md) | `AbstractNotifier`, `PriceDropEvent`, Slack/Console implementations, factory, dedup semantics |
| [scraper.md](backend/scraper.md) | `AmazonScraper`, stealth config, price selector cascade, search function, error types |

## Frontend

| File | Description |
|---|---|
| [components.md](frontend/components.md) | Props, state, rendering behaviour for `ProductList`, `ProductDetail`, `PriceChart`, `SearchBar`, `SearchResults` |
| [hooks.md](frontend/hooks.md) | `useProducts`, `useHistory`, `useSearch` — query keys, refetch intervals, return shapes; full `api/client.ts` function reference |

## Scripts

| File | Description |
|---|---|
| [scripts.md](scripts.md) | `simulate_price_walk.py`, `demo_drop.py`, `schedule_price.py` — flags, examples, DB side effects |

## Kickstart & Deploy

| File | Description |
|---|---|
| [kickstart.md](kickstart.md) | Full setup guide + curl reference for all endpoints including Slack notification verification |
| [deploy/homelab.md](deploy/homelab.md) | LXC vs VM decision, Proxmox setup, DNS, Caddy TLS, UFW firewall, security checklist |

---

## How to update these docs

These docs track the actual code. Update the relevant file whenever:

- **A model field is added or changed** → update `docs/backend/models.md` and the migration chain section
- **A new endpoint is added or a response shape changes** → update `docs/backend/api.md`
- **A repository method is added, renamed, or changes SQL behaviour** → update `docs/backend/repository.md`
- **Scheduler phases or cache invalidation logic changes** → update `docs/backend/scheduler.md`
- **Redis keys or TTLs change** → update `docs/backend/cache.md`
- **A new notifier is added or the factory changes** → update `docs/backend/notifications.md`
- **Scraper selectors, stealth config, or error types change** → update `docs/backend/scraper.md`
- **A component's props, hooks, or rendering logic changes** → update `docs/frontend/components.md`
- **A hook's query key or refetch interval changes, or a new API client function is added** → update `docs/frontend/hooks.md`
- **A script flag is added or behaviour changes** → update `docs/scripts.md`

Keep the index table above in sync with any new doc files.
