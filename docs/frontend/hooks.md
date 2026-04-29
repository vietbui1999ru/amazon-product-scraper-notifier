---
title: "Frontend Hooks & API Client"
description: "React Query hooks and API client function reference — query keys, fetch intervals, response types."
tags: [frontend, hooks, api-client, react-query]
updated: 2026-04-28
---

# Frontend Hooks & API Client

---

## Hooks

All hooks use `@tanstack/react-query`. Query data is cached per query key and shared across components.

### `useProducts`

`frontend/src/hooks/useProducts.ts`

```typescript
function useProducts(): UseQueryResult<Product[]>
```

| Property | Value |
|---|---|
| Query key | `['products']` |
| Fetches | `GET /api/products` |
| Refetch interval | 60 seconds |
| Enabled | always |

Returns `Product[]` on success. `isLoading`, `isError`, and `data` from the React Query result object are the primary consumer interface.

---

### `useHistory`

`frontend/src/hooks/useHistory.ts`

```typescript
function useHistory(productId: number | null): UseQueryResult<PriceCheck[]>
```

| Property | Value |
|---|---|
| Query key | `['history', productId]` |
| Fetches | `GET /api/products/{productId}/history` |
| Refetch interval | 60 seconds |
| Enabled | only when `productId !== null` |

When `productId` changes, React Query automatically fetches the new product's history. Each unique `productId` has its own cache entry.

---

### `useSearch`

`frontend/src/hooks/useSearch.ts`

```typescript
function useSearch(): {
  results: SearchResult[]
  loading: boolean
  error: string | null
  search: (q: string) => Promise<void>
}
```

Not backed by React Query — uses plain `useState`. Search is triggered imperatively by calling `search(q)`.

| State | Initial | Description |
|---|---|---|
| `results` | `[]` | Current search results |
| `loading` | `false` | True while fetch is in flight |
| `error` | `null` | Error message string, or `null` |

Calling `search(q)` sets `loading=true`, clears `error`, calls `searchProducts(q)`, then sets `results` on success or `error` on failure.

---

## API Client

`frontend/src/api/client.ts`

Base path: `/api` (relative, proxied in dev via Vite config).

### `fetchProducts`

```typescript
function fetchProducts(): Promise<Product[]>
```

`GET /api/products` → `Product[]`

---

### `fetchHistory`

```typescript
function fetchHistory(productId: number): Promise<PriceCheck[]>
```

`GET /api/products/{productId}/history` → `PriceCheck[]`

---

### `searchProducts`

```typescript
async function searchProducts(q: string): Promise<SearchResult[]>
```

`GET /api/search?q={encodeURIComponent(q)}` → `SearchResult[]`

Throws a plain `Error` on non-OK response. Does not handle `RateLimitError` internally — callers should check for 429 separately if needed.

---

### `forceCheckProducts`

```typescript
async function forceCheckProducts(productIds: number[]): Promise<void>
```

`POST /api/products/force-check` with body `{ product_ids: productIds }`. Throws `Error` on non-OK response.

---

### `forceCheckAll`

```typescript
async function forceCheckAll(): Promise<void>
```

`POST /api/products/force-check` with body `{ all: true }`. Throws `Error` on non-OK response.

---

### `addProduct`

```typescript
async function addProduct(
  url: string,
  name: string,
  meta?: {
    image_url?: string | null
    rating?: string | null
    initial_price?: number | null
  }
): Promise<Product>
```

`POST /api/products` with `{ url, name, ...meta }` → `Product`.

Throws `RateLimitError` on HTTP 429. Throws plain `Error` on other non-OK responses.

---

### `RateLimitError`

```typescript
class RateLimitError extends Error
```

Thrown by `addProduct` when the API returns 429. Callers can `instanceof` check to display a specific message to the user.

---

## TypeScript Types

`frontend/src/types.ts`

### `Product`

```typescript
interface Product {
  id: number
  url: string
  name: string | null
  asin: string | null
  created_at: string        // ISO 8601
  image_url?: string | null
  rating?: string | null
  latest_price?: number | null
}
```

### `PriceCheck`

```typescript
interface PriceCheck {
  id: number
  product_id: number
  price: string | null      // Note: string, not number
  currency: string
  scraped_at: string        // ISO 8601
  scrape_success: boolean
  error_message: string | null
  source: string            // "amazon" | "self" | "simulated"
}
```

> Note: `price` is typed as `string | null` on the frontend. `PriceChart` uses `parseFloat(h.price!)` to convert.

### `ScheduledPrice`

```typescript
interface ScheduledPrice {
  id: number
  product_id: number
  price: number
  currency: string
  scheduled_for: string     // ISO 8601
  applied_at: string | null
  cancelled_at: string | null
  cancel_reason: string | null
}
```

### `SearchResult`

```typescript
interface SearchResult {
  asin: string
  name: string
  url: string
  price: number | null
  image_url: string | null
  rating: string | null
}
```
