---
title: "Frontend Components"
description: "Props, state, rendering behaviour, and hook usage for every frontend component."
tags: [frontend, react, components]
updated: 2026-04-28
---

# Frontend Components

Built with React + TypeScript. State management via React Query (`@tanstack/react-query`). No global store.

---

## ProductList

`frontend/src/components/ProductList.tsx`

**Props**

| Prop | Type | Description |
|---|---|---|
| `selectedId` | `number \| null` | Currently selected product ID |
| `onSelect` | `(id: number) => void` | Callback when user clicks a product row |

**State**

| State | Type | Description |
|---|---|---|
| `checkedIds` | `Set<number>` | IDs of checked products (for force-check) |
| `queuing` | `boolean` | True while a force-check API call is in flight |

**Hooks**: `useProducts()` for product list data.

**Renders**

An unordered list of product rows. Each row shows:
- Checkbox (for force-check selection; click does not propagate to row selection)
- Product thumbnail (40×40) or a grey placeholder if no `image_url`
- Product name (falls back to `asin`, then hostname)
- External link to Amazon (`↗`)

Selected row: `background: var(--accent-soft)`, `box-shadow: inset 3px 0 0 var(--accent)`.
Hover (unselected): `background: var(--bg-subtle)`, cleared on mouse leave.

When `checkedIds.size > 0`, two buttons appear below the list:
- **Force Check Selected** — calls `forceCheckProducts(Array.from(checkedIds))`, clears `checkedIds` on success.
- **Check All** — calls `forceCheckAll()`, clears `checkedIds` on success.

Both buttons are disabled during `queuing`.

**Loading / error states**: renders plain text `"Loading products…"` or `"Failed to load products."` respectively.

---

## ProductDetail

`frontend/src/components/ProductDetail.tsx`

**Props**

| Prop | Type | Description |
|---|---|---|
| `productId` | `number` | ID of the product to display |
| `product` | `Product \| null` | Product metadata (passed from parent, may be null during load) |

**Hooks**: `useHistory(productId)` — fetches price check history.

**Renders** (two card sections)

1. **Product header card**: thumbnail (140×140), product name (2-line clamp), current price (28px bold), rating with amber star, "View on Amazon →" link.
2. **Price History card**: `<PriceChart history={data} />` below a "Price History" label.

`latest_price` is read from the `product` prop (not recomputed from history).

**Loading / error states**: `"Loading history…"` or `"Failed to load price history."` text.

---

## PriceChart

`frontend/src/components/PriceChart.tsx`

**Props**

| Prop | Type | Description |
|---|---|---|
| `history` | `PriceCheck[]` | Array of price check records |

**Rendering**

Filters `history` to rows where `scrape_success=true` and `price != null`. Each row is mapped to a `ChartPoint`:

```typescript
interface ChartPoint {
  date: string      // toLocaleDateString()
  price: number | null     // null for simulated rows
  simPrice: number | null  // null for non-simulated rows
}
```

`source === "simulated"` rows populate `simPrice`; all other sources populate `price`. This separates real and simulated data into two lines.

Uses Recharts `LineChart` in a `ResponsiveContainer` (100% width, 300px height).

**Two Line components**

| `dataKey` | `name` | Appearance |
|---|---|---|
| `price` | `"price"` | Default stroke color, solid, `strokeWidth=2` |
| `simPrice` | `"simPrice"` | `stroke="#9ca3af"`, `strokeDasharray="4 2"`, `strokeWidth=2` |

Both lines have `dot={false}` and `connectNulls={false}` — gaps appear where the other source type has data.

**CustomTooltip**

Shows the date label, formatted price (`$X.XX`), and a source badge inline. Source badge colours:

| Source | Background | Text | Border |
|---|---|---|---|
| `amazon` | `#dbeafe` | `#1d4ed8` | `#bfdbfe` |
| `self` | `#fef3c7` | `#92400e` | `#fde68a` |
| `simulated` | `#f3f4f6` | `#6b7280` | `#d1d5db` |
| unknown | falls back to `simulated` colors | | |

Badge text: `[amazon]`, `[self]`, `[sim]`.

If no successful price points exist, renders `"No successful price checks yet."`.

---

## SearchBar

`frontend/src/components/SearchBar.tsx`

**Props**

| Prop | Type | Description |
|---|---|---|
| `onSearch` | `(q: string) => void` | Called with trimmed query on submit |
| `loading` | `boolean` | Disables input and button while search is in flight |

**State**: `query: string` (controlled input).

**Renders**: text input + "Search" button stacked vertically.

Submit triggers on button click or Enter keypress. Trims the query before calling `onSearch`; does nothing if query is empty.

Focus styles: `borderColor: var(--accent)`, `boxShadow: 0 0 0 3px var(--accent-soft)`.

Button is disabled (greyed out, `cursor: not-allowed`) when `loading=true` or query is empty after trim.

---

## SearchResults

`frontend/src/components/SearchResults.tsx`

**Props**

| Prop | Type | Description |
|---|---|---|
| `results` | `SearchResult[]` | Search results from the API |
| `selectedAsins` | `Set<string>` | ASINs checked for tracking |
| `onToggle` | `(asin: string) => void` | Toggle ASIN selection |
| `trackingIds` | `Set<string>` | ASINs already being tracked |
| `onTrackSelected` | `() => void` | Callback to add selected products |
| `tracking` | `boolean` | True while `addProduct` calls are in flight |

Renders nothing if `results` is empty.

**Each result card** shows:
- Checkbox — disabled (and auto-checked) if ASIN is in `trackingIds`
- Thumbnail (56×56) or grey placeholder
- Product name (2-line clamp)
- Price (`$X.XX`) or `"Price unavailable"`, with rating suffix if present
- "Tracked" badge (green pill) for already-tracked items

Card border: `var(--accent)` when selected-but-not-tracked, `var(--border)` otherwise.
Card background: `var(--bg-subtle)` when tracked (opacity 0.55), `var(--accent-soft)` when selected, `var(--bg-surface)` otherwise.

**"Track Selected" button** below the list. Disabled when no un-tracked items are selected or `tracking=true`. Shows count of newly selectable items (excludes already-tracked ASINs from the count).
