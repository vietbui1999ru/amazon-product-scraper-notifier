export interface Product {
  id: number
  url: string
  name: string | null
  asin: string | null
  created_at: string
  image_url?: string | null
  rating?: string | null
  latest_price?: number | null
}

export interface PriceCheck {
  id: number
  product_id: number
  price: string | null
  currency: string
  scraped_at: string
  scrape_success: boolean
  error_message: string | null
  source: string
}

export interface ScheduledPrice {
  id: number
  product_id: number
  price: number
  currency: string
  scheduled_for: string
  applied_at: string | null
  cancelled_at: string | null
  cancel_reason: string | null
}

export interface SearchResult {
  asin: string
  name: string
  url: string
  price: number | null
  image_url: string | null
  rating: string | null
}
