import type { PriceCheck, Product, SearchResult } from '../types'

const BASE = '/api'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export function fetchProducts(): Promise<Product[]> {
  return get<Product[]>('/products')
}

export function fetchHistory(productId: number): Promise<PriceCheck[]> {
  return get<PriceCheck[]>(`/products/${productId}/history`)
}

export class RateLimitError extends Error {
  constructor() {
    super('Rate limit exceeded')
    this.name = 'RateLimitError'
  }
}

export async function searchProducts(q: string): Promise<SearchResult[]> {
  const res = await fetch(`${BASE}/search?q=${encodeURIComponent(q)}`)
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`)
  }
  return res.json() as Promise<SearchResult[]>
}

export async function forceCheckProducts(productIds: number[]): Promise<void> {
  const res = await fetch(`${BASE}/products/force-check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_ids: productIds }),
  })
  if (!res.ok) throw new Error(`Force check failed: ${res.status}`)
}

export async function forceCheckAll(): Promise<void> {
  const res = await fetch(`${BASE}/products/force-check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ all: true }),
  })
  if (!res.ok) throw new Error(`Force check all failed: ${res.status}`)
}

export interface ScheduledPriceEntry {
  id: number
  product_id: number
  product: string
  price: number
  currency: string
  scheduled_for: string
  created_at: string
}

export async function demoDropPrice(url: string, price: number): Promise<void> {
  const res = await fetch(`${BASE}/demo/drop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, price }),
  })
  if (!res.ok) throw new Error(`Demo drop failed: ${res.status}`)
}

export async function schedulePrice(
  productId: number,
  price: number,
  delaySeconds: number,
): Promise<void> {
  const res = await fetch(`${BASE}/scheduler/prices`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_id: productId, price, seconds: delaySeconds }),
  })
  if (!res.ok) throw new Error(`Schedule price failed: ${res.status}`)
}

export function getPendingScheduledPrices(): Promise<ScheduledPriceEntry[]> {
  return get<ScheduledPriceEntry[]>('/scheduler/prices/pending')
}

export async function cancelScheduledPrice(id: number): Promise<void> {
  const res = await fetch(`${BASE}/scheduler/prices/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Cancel failed: ${res.status}`)
}

export async function updateProductImage(productId: number, imageUrl: string | null): Promise<Product> {
  const res = await fetch(`${BASE}/products/${productId}/image`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image_url: imageUrl }),
  })
  if (!res.ok) throw new Error(`Update image failed: ${res.status}`)
  return res.json() as Promise<Product>
}

export async function addProduct(
  url: string,
  name: string,
  meta?: { image_url?: string | null; rating?: string | null; initial_price?: number | null }
): Promise<Product> {
  const res = await fetch(`${BASE}/products`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, name, ...meta }),
  })
  if (res.status === 429) throw new RateLimitError()
  if (!res.ok) throw new Error(`API error ${res.status}: ${res.statusText}`)
  return res.json() as Promise<Product>
}
