import { useState } from 'react'
import type { Product } from '../types'
import { useProducts } from '../hooks/useProducts'
import { forceCheckProducts, forceCheckAll } from '../api/client'

interface Props {
  selectedId: number | null
  onSelect: (id: number) => void
}

function productLabel(p: Product): string {
  return p.name ?? p.asin ?? new URL(p.url).hostname
}

export function ProductList({ selectedId, onSelect }: Props) {
  const { data, isLoading, isError } = useProducts()
  const [checkedIds, setCheckedIds] = useState<Set<number>>(new Set())
  const [queuing, setQueuing] = useState(false)

  if (isLoading) return <p>Loading products…</p>
  if (isError) return <p>Failed to load products.</p>
  if (!data?.length) return <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>No products tracked yet.</p>

  function toggleCheck(id: number) {
    setCheckedIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function handleForceSelected() {
    setQueuing(true)
    try {
      await forceCheckProducts(Array.from(checkedIds))
      setCheckedIds(new Set())
    } finally {
      setQueuing(false)
    }
  }

  async function handleCheckAll() {
    setQueuing(true)
    try {
      await forceCheckAll()
      setCheckedIds(new Set())
    } finally {
      setQueuing(false)
    }
  }

  return (
    <>
      <ul data-testid="product-list" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {data.map((p) => {
          const selected = p.id === selectedId
          const checked = checkedIds.has(p.id)
          return (
            <li
              key={p.id}
              data-testid="product-item"
              onClick={() => onSelect(p.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 8px',
                cursor: 'pointer',
                borderRadius: 6,
                transition: 'background 0.1s',
                background: selected ? 'var(--accent-soft)' : undefined,
                boxShadow: selected ? 'inset 3px 0 0 var(--accent)' : undefined,
              }}
              onMouseEnter={e => {
                if (!selected) (e.currentTarget as HTMLLIElement).style.background = 'var(--bg-subtle)'
              }}
              onMouseLeave={e => {
                if (!selected) (e.currentTarget as HTMLLIElement).style.background = ''
              }}
            >
              <input
                type="checkbox"
                checked={checked}
                onClick={(e) => e.stopPropagation()}
                onChange={() => toggleCheck(p.id)}
                style={{ flexShrink: 0, cursor: 'pointer', width: 15, height: 15 }}
              />
              {p.image_url ? (
                <img
                  src={p.image_url}
                  alt=""
                  referrerPolicy="no-referrer"
                  style={{ width: 64, height: 64, objectFit: 'contain', flexShrink: 0, borderRadius: 4 }}
                />
              ) : (
                <div style={{ width: 64, height: 64, background: 'var(--bg-subtle)', flexShrink: 0, borderRadius: 4 }} />
              )}
              <span style={{ fontSize: 14, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-primary)' }}>
                {productLabel(p)}
              </span>
              <a
                href={p.url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                style={{ fontSize: 13, color: 'var(--text-faint)', flexShrink: 0 }}
              >
                ↗
              </a>
            </li>
          )
        })}
      </ul>

      {checkedIds.size > 0 && (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button
            disabled={queuing}
            onClick={handleForceSelected}
            style={{
              flex: 1,
              padding: '6px 10px',
              fontSize: 13,
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'var(--bg-subtle)',
              cursor: queuing ? 'not-allowed' : 'pointer',
              color: 'var(--text-primary)',
            }}
          >
            {queuing ? 'Queuing…' : `Force Check Selected (${checkedIds.size})`}
          </button>
          <button
            disabled={queuing}
            onClick={handleCheckAll}
            style={{
              padding: '6px 10px',
              fontSize: 13,
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'var(--bg-subtle)',
              cursor: queuing ? 'not-allowed' : 'pointer',
              color: 'var(--text-primary)',
            }}
          >
            {queuing ? 'Queuing…' : 'Check All'}
          </button>
        </div>
      )}
    </>
  )
}
