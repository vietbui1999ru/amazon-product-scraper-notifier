import { useState } from 'react'
import { searchProducts } from '../api/client'
import type { SearchResult } from '../types'

export function useSearch() {
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function search(q: string) {
    setLoading(true)
    setError(null)
    try {
      const data = await searchProducts(q)
      setResults(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  return { results, loading, error, search }
}
