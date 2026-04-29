import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ProductList } from './components/ProductList'
import { ProductDetail } from './components/ProductDetail'
import { SearchBar } from './components/SearchBar'
import { SearchResults } from './components/SearchResults'
import { Toast } from './components/Toast'
import { useSearch } from './hooks/useSearch'
import { useProducts } from './hooks/useProducts'
import { addProduct, RateLimitError } from './api/client'
import type { Product } from './types'

interface ToastState {
  message: string
  type: 'error' | 'warning' | 'success'
}

export default function App() {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [selectedAsins, setSelectedAsins] = useState<Set<string>>(new Set())
  const [batchTracking, setBatchTracking] = useState(false)

  const queryClient = useQueryClient()
  const { results, loading: searchLoading, search } = useSearch()
  const { data: products } = useProducts()

  const trackingIds = new Set(products?.map((p) => p.asin).filter(Boolean) as string[])

  function extractNameFromUrl(url: string): string {
    try {
      const path = new URL(url).pathname
      const slug = path.split('/dp/')[0].split('/').filter(Boolean).pop() ?? ''
      const name = slug.replace(/-/g, ' ').replace(/\s+/g, ' ').trim()
      return name || 'Amazon Product'
    } catch {
      return 'Amazon Product'
    }
  }

  async function handleSearch(q: string) {
    // If input looks like an Amazon URL, track it directly — skip Playwright search
    if (q.includes('amazon.') && q.includes('/dp/')) {
      try {
        const name = extractNameFromUrl(q)
        await addProduct(q, name)
        await queryClient.invalidateQueries({ queryKey: ['products'] })
        setToast({ message: `Now tracking ${name}`, type: 'success' })
      } catch (e) {
        if (e instanceof RateLimitError) {
          setToast({ message: 'Rate limit reached — wait 1 second', type: 'warning' })
        } else {
          setToast({ message: e instanceof Error ? e.message : 'Failed to add product', type: 'error' })
        }
      }
      return
    }
    search(q)
  }

  function toggleSelect(asin: string) {
    setSelectedAsins((prev) => {
      const next = new Set(prev)
      next.has(asin) ? next.delete(asin) : next.add(asin)
      return next
    })
  }

  async function handleTrackSelected() {
    const toTrack = results.filter(
      (r) => selectedAsins.has(r.asin) && !trackingIds.has(r.asin)
    )
    if (!toTrack.length) return

    setBatchTracking(true)
    let added = 0

    for (const result of toTrack) {
      try {
        await addProduct(result.url, result.name, {
          image_url: result.image_url,
          rating: result.rating,
          initial_price: result.price,
        })
        added++
        setToast({ message: `Tracked ${added} of ${toTrack.length}…`, type: 'success' })
        await queryClient.invalidateQueries({ queryKey: ['products'] })

        if (added < toTrack.length) {
          await new Promise<void>((r) => setTimeout(r, 2000 + Math.random() * 2000))
        }
      } catch (e) {
        if (e instanceof RateLimitError) {
          setToast({ message: `Rate limited after ${added} items — waiting 10s…`, type: 'warning' })
          await new Promise<void>((r) => setTimeout(r, 10000))
        } else {
          setToast({ message: e instanceof Error ? e.message : 'Failed', type: 'error' })
          break
        }
      }
    }

    setToast({ message: `Done — tracking ${added} new product${added !== 1 ? 's' : ''}`, type: 'success' })
    setSelectedAsins(new Set())
    setBatchTracking(false)
  }

  return (
    <div className="app">
      {toast && (
        <Toast message={toast.message} type={toast.type} onDismiss={() => setToast(null)} />
      )}

      <header className="app-header">
        <h1>Price Monitor</h1>
        <p>Track Amazon products · get drop alerts</p>
      </header>

      <div className="app-grid">
        <aside className="sidebar">
          <div className="card">
            <p className="section-label">Search Amazon</p>
            <SearchBar onSearch={handleSearch} loading={searchLoading} />
            {results.length > 0 && (
              <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
                <SearchResults
                  results={results}
                  selectedAsins={selectedAsins}
                  onToggle={toggleSelect}
                  trackingIds={trackingIds}
                  onTrackSelected={handleTrackSelected}
                  tracking={batchTracking}
                />
              </div>
            )}
          </div>

          <div className="card">
            <p className="section-label">Tracked Products</p>
            <ProductList selectedId={selectedId} onSelect={setSelectedId} />
          </div>
        </aside>

        <main className="main">
          {selectedId !== null ? (
            <ProductDetail
              productId={selectedId}
              product={products?.find((p): p is Product => p.id === selectedId) ?? null}
            />
          ) : (
            <div className="card" style={{ padding: '64px 24px', textAlign: 'center', color: 'var(--text-muted)' }}>
              <p style={{ fontSize: 15 }}>Select a tracked product to see its price history</p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
