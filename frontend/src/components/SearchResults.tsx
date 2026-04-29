import type { SearchResult } from '../types'

interface Props {
  results: SearchResult[]
  selectedAsins: Set<string>
  onToggle: (asin: string) => void
  trackingIds: Set<string>
  onTrackSelected: () => void
  tracking: boolean
}

export function SearchResults({
  results,
  selectedAsins,
  onToggle,
  trackingIds,
  onTrackSelected,
  tracking,
}: Props) {
  if (!results.length) return null

  const selectedCount = results.filter(
    (r) => selectedAsins.has(r.asin) && !trackingIds.has(r.asin)
  ).length

  return (
    <div>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {results.map((r) => {
          const tracked = trackingIds.has(r.asin)
          const checked = selectedAsins.has(r.asin)

          return (
            <li
              key={r.asin}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px',
                border: `1px solid ${checked && !tracked ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 6,
                background: tracked ? 'var(--bg-subtle)' : checked ? 'var(--accent-soft)' : 'var(--bg-surface)',
                opacity: tracked ? 0.55 : 1,
                transition: 'background 0.1s, border-color 0.1s',
              }}
            >
              <input
                type="checkbox"
                checked={tracked ? true : checked}
                disabled={tracked}
                onChange={() => !tracked && onToggle(r.asin)}
                style={{ flexShrink: 0, width: 16, height: 16, cursor: tracked ? 'default' : 'pointer' }}
              />
              {r.image_url ? (
                <img
                  src={r.image_url}
                  alt=""
                  referrerPolicy="no-referrer"
                  style={{ width: 56, height: 56, objectFit: 'contain', flexShrink: 0 }}
                />
              ) : (
                <div
                  style={{
                    width: 56,
                    height: 56,
                    background: 'var(--bg-subtle)',
                    flexShrink: 0,
                    borderRadius: 4,
                  }}
                />
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <p
                  style={{
                    margin: 0,
                    fontSize: 13,
                    fontWeight: 500,
                    color: 'var(--text-primary)',
                    overflow: 'hidden',
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                  }}
                >
                  {r.name}
                </p>
                <p style={{ margin: '4px 0 0', fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                  {r.price != null ? `$${r.price.toFixed(2)}` : 'Price unavailable'}
                  {r.rating && <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--text-muted)', marginLeft: 6 }}>{r.rating} ★</span>}
                </p>
              </div>
              {tracked && (
                <span style={{
                  fontSize: 11,
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  color: 'var(--success)',
                  background: '#ecfdf5',
                  padding: '2px 8px',
                  borderRadius: 999,
                  flexShrink: 0,
                }}>
                  Tracked
                </span>
              )}
            </li>
          )
        })}
      </ul>

      <button
        onClick={onTrackSelected}
        disabled={selectedCount === 0 || tracking}
        style={{
          marginTop: 12,
          height: 40,
          width: '100%',
          background: selectedCount === 0 || tracking ? 'var(--border)' : 'var(--accent)',
          color: selectedCount === 0 || tracking ? 'var(--text-faint)' : '#fff',
          border: 'none',
          borderRadius: 'var(--radius-sm)',
          fontWeight: 500,
          cursor: selectedCount === 0 || tracking ? 'not-allowed' : 'pointer',
          transition: 'background 0.15s',
        }}
      >
        {tracking ? 'Tracking…' : `Track Selected (${selectedCount})`}
      </button>
    </div>
  )
}
