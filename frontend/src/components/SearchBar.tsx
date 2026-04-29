import { useState, type KeyboardEvent } from 'react'

interface Props {
  onSearch: (q: string) => void
  loading: boolean
}

export function SearchBar({ onSearch, loading }: Props) {
  const [query, setQuery] = useState('')

  function submit() {
    const q = query.trim()
    if (q) onSearch(q)
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') submit()
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Keywords or paste Amazon URL…"
        style={{
          width: '100%',
          height: 40,
          padding: '0 12px',
          border: '1px solid var(--border-strong)',
          borderRadius: 'var(--radius-sm)',
          outline: 'none',
          color: 'var(--text-primary)',
          background: 'var(--bg-surface)',
          transition: 'border-color 0.15s, box-shadow 0.15s',
        }}
        onFocus={e => {
          e.target.style.borderColor = 'var(--accent)'
          e.target.style.boxShadow = '0 0 0 3px var(--accent-soft)'
        }}
        onBlur={e => {
          e.target.style.borderColor = 'var(--border-strong)'
          e.target.style.boxShadow = 'none'
        }}
      />
      <button
        onClick={submit}
        disabled={loading || !query.trim()}
        style={{
          height: 40,
          width: '100%',
          background: loading || !query.trim() ? 'var(--border)' : 'var(--accent)',
          color: loading || !query.trim() ? 'var(--text-faint)' : '#fff',
          border: 'none',
          borderRadius: 'var(--radius-sm)',
          fontWeight: 500,
          cursor: loading || !query.trim() ? 'not-allowed' : 'pointer',
          transition: 'background 0.15s',
        }}
      >
        {loading ? 'Searching…' : 'Search'}
      </button>
    </div>
  )
}
