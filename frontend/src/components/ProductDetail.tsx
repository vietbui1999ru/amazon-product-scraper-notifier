import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { Product } from '../types'
import { useHistory } from '../hooks/useHistory'
import { PriceChart } from './PriceChart'
import { PriceEditor } from './PriceEditor'
import { updateProductImage } from '../api/client'

interface Props {
  productId: number
  product: Product | null
}

export function ProductDetail({ productId, product }: Props) {
  const { data, isLoading, isError } = useHistory(productId)
  const qc = useQueryClient()
  const [editingImage, setEditingImage] = useState(false)
  const [imageInput, setImageInput] = useState('')
  const [imageStatus, setImageStatus] = useState<string | null>(null)

  async function handleImageSave() {
    if (!product) return
    const url = imageInput.trim()
    if (url && !/^https?:\/\//i.test(url)) {
      setImageStatus('URL must start with https://')
      return
    }
    try {
      await updateProductImage(product.id, url || null)
      await qc.invalidateQueries({ queryKey: ['products'] })
      setEditingImage(false)
      setImageInput('')
      setImageStatus(null)
    } catch {
      setImageStatus('Failed to update image.')
    }
  }

  if (isLoading) return <p>Loading history…</p>
  if (isError) return <p>Failed to load price history.</p>
  if (!data) return null

  const latestPrice = product?.latest_price

  return (
    <div data-testid="product-detail">
      {/* Product header card */}
      <div className="card" style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
        <div style={{ position: 'relative', flexShrink: 0 }}>
          {product?.image_url ? (
            <img
              src={product.image_url}
              alt=""
              referrerPolicy="no-referrer"
              style={{ width: 140, height: 140, objectFit: 'contain', display: 'block',
                       borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-subtle)' }}
            />
          ) : (
            <div style={{ width: 140, height: 140, borderRadius: 8,
                          border: '1px solid var(--border)', background: 'var(--bg-subtle)' }} />
          )}
          {product && (
            <button
              onClick={() => {
                setEditingImage(prev => {
                  if (!prev) setImageInput(product.image_url ?? '')
                  return !prev
                })
                setImageStatus(null)
              }}
              title="Edit image URL"
              style={{
                position: 'absolute', bottom: 4, right: 4,
                padding: '2px 6px', fontSize: 11, borderRadius: 4,
                border: '1px solid var(--border)', background: 'var(--bg-card)',
                color: 'var(--text-muted)', cursor: 'pointer',
              }}
            >
              edit
            </button>
          )}
          {editingImage && (
            <div style={{
              position: 'absolute', top: 148, left: 0, zIndex: 10,
              background: 'var(--bg-card)', border: '1px solid var(--border)',
              borderRadius: 8, padding: 10, width: 260, boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            }}>
              <input
                type="url"
                value={imageInput}
                onChange={e => setImageInput(e.target.value)}
                placeholder="https://... or leave blank to clear"
                style={{
                  width: '100%', padding: '6px 8px', fontSize: 12,
                  borderRadius: 4, border: '1px solid var(--border)',
                  background: 'var(--bg-subtle)', color: 'var(--text-primary)',
                  boxSizing: 'border-box',
                }}
              />
              <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                <button onClick={handleImageSave} style={{
                  flex: 1, padding: '4px 0', fontSize: 12, borderRadius: 4,
                  border: 'none', background: 'var(--accent)', color: '#fff', cursor: 'pointer',
                }}>Save</button>
                <button onClick={() => { setEditingImage(false); setImageInput(product?.image_url ?? ''); setImageStatus(null) }} style={{
                  flex: 1, padding: '4px 0', fontSize: 12, borderRadius: 4,
                  border: '1px solid var(--border)', background: 'var(--bg-subtle)',
                  color: 'var(--text-muted)', cursor: 'pointer',
                }}>Cancel</button>
              </div>
              {imageStatus && <p style={{ margin: '6px 0 0', fontSize: 11, color: 'var(--error)' }}>{imageStatus}</p>}
            </div>
          )}
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          {product?.name && (
            <h3 style={{ fontSize: 18, fontWeight: 600, margin: '0 0 8px',
                         overflow: 'hidden', display: '-webkit-box',
                         WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
              {product.name}
            </h3>
          )}
          {latestPrice != null && (
            <p style={{ margin: '0 0 6px' }}>
              <span style={{ fontSize: 28, fontWeight: 700, color: 'var(--text-primary)' }}>
                ${latestPrice.toFixed(2)}
              </span>
              <span style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-muted)', marginLeft: 4 }}>USD</span>
            </p>
          )}
          {product?.rating && (
            <p style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--text-muted)' }}>
              <span style={{ color: '#f59e0b' }}>★</span> {product.rating}
            </p>
          )}
          {product?.url && (
            <a href={product.url} target="_blank" rel="noopener noreferrer"
               style={{ fontSize: 13, fontWeight: 500, color: 'var(--accent)' }}>
              View on Amazon →
            </a>
          )}
          {!product && <p style={{ color: 'var(--text-muted)' }}>Loading product details…</p>}
        </div>
      </div>

      {/* Chart card */}
      <div className="card" style={{ marginTop: 16 }}>
        <p className="section-label" style={{ marginBottom: 16 }}>Price History</p>
        <PriceChart history={data} />
      </div>

      {product && <PriceEditor product={product} />}
    </div>
  )
}
