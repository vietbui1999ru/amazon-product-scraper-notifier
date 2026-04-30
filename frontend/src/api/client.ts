import type { PriceCheck, Product, SearchResult } from '../types'

const BASE = '/api'
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined

function authHeaders(): Record<string, string> {
  return API_KEY ? { 'X-API-Key': API_KEY } : {}
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() })
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
  const res = await fetch(`${BASE}/search?q=${encodeURIComponent(q)}`, { headers: authHeaders() })
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`)
  }
  return res.json() as Promise<SearchResult[]>
}

export async function forceCheckProducts(productIds: number[]): Promise<void> {
  const res = await fetch(`${BASE}/products/force-check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ product_ids: productIds }),
  })
  if (!res.ok) throw new Error(`Force check failed: ${res.status}`)
}

export async function forceCheckAll(): Promise<void> {
  const res = await fetch(`${BASE}/products/force-check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
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
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
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
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ product_id: productId, price, seconds: delaySeconds }),
  })
  if (!res.ok) throw new Error(`Schedule price failed: ${res.status}`)
}

export function getPendingScheduledPrices(): Promise<ScheduledPriceEntry[]> {
  return get<ScheduledPriceEntry[]>('/scheduler/prices/pending')
}

export async function cancelScheduledPrice(id: number): Promise<void> {
  const res = await fetch(`${BASE}/scheduler/prices/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error(`Cancel failed: ${res.status}`)
}

export async function updateProductImage(productId: number, imageUrl: string | null): Promise<Product> {
  const res = await fetch(`${BASE}/products/${productId}/image`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ image_url: imageUrl }),
  })
  if (!res.ok) throw new Error(`Update image failed: ${res.status}`)
  return res.json() as Promise<Product>
}

export interface AppConfig {
  check_interval_seconds: number
  notification_method: string | string[]
  price_drop_threshold_percent: number
  price_drop_threshold_absolute: number
  scraper_headless: boolean
  scraper_timeout_ms: number
  scraper_min_delay: number
  scraper_max_delay: number
}

export function fetchConfig(): Promise<AppConfig> {
  return get<AppConfig>('/config')
}

export async function updateConfig(patch: Partial<Omit<AppConfig, 'scraper_headless'>>): Promise<AppConfig> {
  const res = await fetch(`${BASE}/config`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error(`Config update failed: ${res.status}`)
  return res.json() as Promise<AppConfig>
}

export async function addProduct(
  url: string,
  name: string,
  meta?: { image_url?: string | null; rating?: string | null; initial_price?: number | null }
): Promise<Product> {
  const res = await fetch(`${BASE}/products`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ url, name, ...meta }),
  })
  if (res.status === 429) throw new RateLimitError()
  if (!res.ok) throw new Error(`API error ${res.status}: ${res.statusText}`)
  return res.json() as Promise<Product>
}
