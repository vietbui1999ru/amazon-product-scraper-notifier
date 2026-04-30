import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchConfig, updateConfig, type AppConfig } from '../api/client'

const inputStyle: React.CSSProperties = {
  padding: '7px 10px', borderRadius: 6, fontSize: 14, width: '100%',
  boxSizing: 'border-box', border: '1px solid var(--border)',
  background: 'var(--bg-card)', color: 'var(--text-primary)',
}

const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4,
}

const rowStyle: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12,
}

function Field({
  label, hint, children,
}: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label style={labelStyle}>{label}</label>
      {children}
      {hint && <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: '3px 0 0' }}>{hint}</p>}
    </div>
  )
}

interface Props {
  onClose: () => void
}

export function ConfigPanel({ onClose }: Props) {
  const qc = useQueryClient()
  const { data: config, isLoading } = useQuery<AppConfig>({
    queryKey: ['config'],
    queryFn: fetchConfig,
  })

  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null)

  const [form, setForm] = useState<Partial<AppConfig>>({})

  function val<K extends keyof AppConfig>(key: K): AppConfig[K] | undefined {
    return key in form ? (form[key] as AppConfig[K]) : config?.[key]
  }

  function set<K extends keyof AppConfig>(key: K, value: AppConfig[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    if (Object.keys(form).length === 0) { onClose(); return }
    setBusy(true)
    setStatus(null)
    try {
      const updated = await updateConfig(form)
      qc.setQueryData(['config'], updated)
      setForm({})
      setStatus({ ok: true, msg: 'Config updated — takes effect on next scheduler tick' })
    } catch (err) {
      setStatus({ ok: false, msg: err instanceof Error ? err.message : 'Update failed' })
    } finally {
      setBusy(false)
    }
  }

  if (isLoading || !config) {
    return (
      <div className="card" style={{ padding: 24 }}>
        <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>Loading config…</p>
      </div>
    )
  }

  const notifMethod = val('notification_method')
  const notifSet: Set<string> = new Set(
    Array.isArray(notifMethod) ? notifMethod : notifMethod ? [notifMethod] : []
  )

  function toggleNotif(method: 'console' | 'slack', checked: boolean) {
    const next = new Set(notifSet)
    checked ? next.add(method) : next.delete(method)
    const arr = Array.from(next)
    set('notification_method', arr.length === 1 ? arr[0] : arr)
  }

  return (
    <div className="card" style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <p className="section-label" style={{ margin: 0 }}>Runtime Config</p>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 18 }}
        >
          ✕
        </button>
      </div>

      <form onSubmit={handleSave}>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
          Scheduler &amp; Scraper
        </p>

        <div style={rowStyle}>
          <Field label="Check interval (seconds)" hint="Min 10, max 86400">
            <input
              type="number" min={10} max={86400} style={inputStyle}
              value={val('check_interval_seconds') ?? ''}
              onChange={(e) => set('check_interval_seconds', parseInt(e.target.value, 10))}
            />
          </Field>
          <Field label="Scraper timeout (ms)" hint="Min 1000, max 120000">
            <input
              type="number" min={1000} max={120000} style={inputStyle}
              value={val('scraper_timeout_ms') ?? ''}
              onChange={(e) => set('scraper_timeout_ms', parseInt(e.target.value, 10))}
            />
          </Field>
        </div>

        <div style={rowStyle}>
          <Field label="Min request delay (s)">
            <input
              type="number" min={0} step={0.1} style={inputStyle}
              value={val('scraper_min_delay') ?? ''}
              onChange={(e) => set('scraper_min_delay', parseFloat(e.target.value))}
            />
          </Field>
          <Field label="Max request delay (s)">
            <input
              type="number" min={0} step={0.1} style={inputStyle}
              value={val('scraper_max_delay') ?? ''}
              onChange={(e) => set('scraper_max_delay', parseFloat(e.target.value))}
            />
          </Field>
        </div>

        <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '16px 0 12px' }}>
          Notifications
        </p>

        <div style={rowStyle}>
          <Field label="Method">
            <div style={{ display: 'flex', gap: 16, paddingTop: 8 }}>
              {(['console', 'slack'] as const).map((m) => (
                <label key={m} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={notifSet.has(m)}
                    onChange={(e) => toggleNotif(m, e.target.checked)}
                  />
                  {m}
                </label>
              ))}
            </div>
          </Field>
          <Field label="Drop threshold %" hint="0 = any positive drop">
            <input
              type="number" min={0} step={0.1} style={inputStyle}
              value={val('price_drop_threshold_percent') ?? ''}
              onChange={(e) => set('price_drop_threshold_percent', parseFloat(e.target.value))}
            />
          </Field>
        </div>

        <div style={{ ...rowStyle, gridTemplateColumns: '1fr' }}>
          <Field label="Drop threshold $ (absolute)" hint="0 = any positive drop">
            <input
              type="number" min={0} step={0.01} style={inputStyle}
              value={val('price_drop_threshold_absolute') ?? ''}
              onChange={(e) => set('price_drop_threshold_absolute', parseFloat(e.target.value))}
            />
          </Field>
        </div>

        <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: '4px 0 16px' }}>
          scraper_headless and proxies require a backend restart to change.
        </p>

        {status && (
          <p style={{
            fontSize: 13, marginBottom: 12,
            color: status.ok ? 'var(--color-success, #4caf50)' : 'var(--color-error, #f44336)',
          }}>
            {status.msg}
          </p>
        )}

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            type="submit" disabled={busy}
            style={{
              flex: 1, padding: '9px 0', borderRadius: 6, fontSize: 14, fontWeight: 600,
              background: 'var(--accent)', color: '#fff', border: 'none', cursor: busy ? 'not-allowed' : 'pointer',
              opacity: busy ? 0.7 : 1,
            }}
          >
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button
            type="button" onClick={onClose}
            style={{
              padding: '9px 16px', borderRadius: 6, fontSize: 14,
              background: 'none', border: '1px solid var(--border)',
              color: 'var(--text-muted)', cursor: 'pointer',
            }}
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
