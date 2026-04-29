import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { Product } from '../types'
import {
  cancelScheduledPrice,
  demoDropPrice,
  getPendingScheduledPrices,
  schedulePrice,
  type ScheduledPriceEntry,
} from '../api/client'

interface Props {
  product: Product
}

type Mode = 'now' | 'schedule'
type Unit = 'seconds' | 'minutes'

function usePendingForProduct(productId: number) {
  return useQuery<ScheduledPriceEntry[]>({
    queryKey: ['pending-prices'],
    queryFn: getPendingScheduledPrices,
    refetchInterval: 5000,
    select: (data) => data.filter((p) => p.product_id === productId),
  })
}

const input: React.CSSProperties = {
  padding: '7px 10px', borderRadius: 6, fontSize: 14, width: '100%',
  boxSizing: 'border-box', border: '1px solid var(--border)',
  background: 'var(--bg-card)', color: 'var(--text-primary)',
}

export function PriceEditor({ product }: Props) {
  const qc = useQueryClient()
  const [mode, setMode] = useState<Mode>('now')
  const [price, setPrice] = useState('')
  const [delay, setDelay] = useState('30')
  const [unit, setUnit] = useState<Unit>('seconds')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null)

  const { data: pending = [], refetch: refetchPending } = usePendingForProduct(product.id)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const p = parseFloat(price)
    if (!price || isNaN(p) || p <= 0) {
      setStatus({ ok: false, msg: 'Enter a valid price > 0' })
      return
    }
    setBusy(true)
    setStatus(null)
    try {
      if (mode === 'now') {
        await demoDropPrice(product.url, p)
        setStatus({ ok: true, msg: `Price set to $${p.toFixed(2)} — notification fired` })
        qc.invalidateQueries({ queryKey: ['history', product.id] })
        qc.invalidateQueries({ queryKey: ['products'] })
      } else {
        const d = parseInt(delay, 10)
        if (!d || d <= 0) { setStatus({ ok: false, msg: 'Enter a valid delay' }); return }
        const secs = unit === 'minutes' ? d * 60 : d
        await schedulePrice(product.id, p, secs)
        setStatus({ ok: true, msg: `Scheduled $${p.toFixed(2)} in ${d} ${unit}` })
        refetchPending()
      }
      setPrice('')
    } catch (err) {
      setStatus({ ok: false, msg: err instanceof Error ? err.message : 'Request failed' })
    } finally {
      setBusy(false)
    }
  }

  async function handleCancel(id: number) {
    await cancelScheduledPrice(id).catch(() => null)
    refetchPending()
  }

  function Tab({ id, label }: { id: Mode; label: string }) {
    const active = mode === id
    return (
      <button
        type="button"
        onClick={() => { setMode(id); setStatus(null) }}
        style={{
          flex: 1, padding: '8px 0', fontSize: 13, fontWeight: active ? 600 : 400,
          background: 'none', border: 'none', cursor: 'pointer',
          color: active ? 'var(--accent)' : 'var(--text-muted)',
          borderBottom: `2px solid ${active ? 'var(--accent)' : 'transparent'}`,
          transition: 'color 0.15s, border-color 0.15s',
        }}
      >
        {label}
      </button>
    )
  }

  return (
    <div style={{ marginTop: 16 }}>
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {/* Tab bar */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
          <Tab id="now" label="Set Price Now" />
          <Tab id="schedule" label="Schedule Price" />
        </div>

        {/* Form body */}
        <form onSubmit={handleSubmit} style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
              {mode === 'now' ? 'New price (USD) — fires notification immediately' : 'New price (USD)'}
            </label>
            <input
              type="number" min="0.01" step="0.01" placeholder="e.g. 39.99"
              value={price} onChange={(e) => setPrice(e.target.value)}
              style={input}
            />
          </div>

          {mode === 'schedule' && (
            <div>
              <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                Apply after
              </label>
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  type="number" min="1" step="1"
                  value={delay} onChange={(e) => setDelay(e.target.value)}
                  style={{ ...input, width: 90 }}
                />
                <select
                  value={unit} onChange={(e) => setUnit(e.target.value as Unit)}
                  style={{ ...input, width: 'auto', flex: 1, cursor: 'pointer' }}
                >
                  <option value="seconds">seconds</option>
                  <option value="minutes">minutes</option>
                </select>
              </div>
            </div>
          )}

          <button
            type="submit" disabled={busy}
            style={{
              padding: '8px 0', borderRadius: 6, fontSize: 13, fontWeight: 600,
              border: 'none', cursor: busy ? 'not-allowed' : 'pointer',
              background: 'var(--accent)', color: '#fff',
              opacity: busy ? 0.6 : 1,
            }}
          >
            {busy ? 'Submitting…' : mode === 'now' ? 'Set Price & Notify' : 'Schedule Price'}
          </button>

          {status && (
            <p style={{
              margin: 0, fontSize: 13, padding: '7px 10px', borderRadius: 6,
              background: status.ok ? 'var(--accent-soft)' : '#fee2e2',
              color: status.ok ? 'var(--accent)' : '#b91c1c',
            }}>
              {status.msg}
            </p>
          )}
        </form>
      </div>

      {/* Pending scheduled prices */}
      {pending.length > 0 && (
        <div className="card" style={{ marginTop: 10 }}>
          <p className="section-label" style={{ marginBottom: 10 }}>Pending Schedules</p>
          {pending.map((sp) => (
            <div key={sp.id} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '7px 0', borderBottom: '1px solid var(--border)',
            }}>
              <div>
                <span style={{ fontWeight: 600, fontSize: 14 }}>${sp.price.toFixed(2)}</span>
                <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>
                  at {new Date(sp.scheduled_for).toLocaleTimeString()}
                </span>
              </div>
              <button
                onClick={() => handleCancel(sp.id)}
                style={{
                  fontSize: 12, padding: '3px 10px', borderRadius: 5, cursor: 'pointer',
                  border: '1px solid var(--border)', background: 'var(--bg-subtle)',
                  color: 'var(--text-muted)',
                }}
              >
                Cancel
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
