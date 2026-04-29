import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { PriceCheck } from '../types'

interface Props {
  history: PriceCheck[]
}

interface ChartPoint {
  date: string
  fullDate: string
  price: number | null
  simPrice: number | null
  source: string
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString([], {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function toChartPoints(history: PriceCheck[]): ChartPoint[] {
  // API returns newest-first; chart must be oldest-first (left = past, right = present)
  return [...history]
    .reverse()
    .filter((h) => h.scrape_success && h.price !== null)
    .map((h) => {
      const price = parseFloat(h.price!)
      const isSimulated = h.source === 'simulated'
      return {
        date: formatDate(h.scraped_at),
        fullDate: new Date(h.scraped_at).toLocaleString(),
        price: isSimulated ? null : price,
        simPrice: isSimulated ? price : null,
        source: h.source,
      }
    })
}

function sourceBadge(source: string) {
  const styles: Record<string, React.CSSProperties> = {
    amazon: { background: '#dbeafe', color: '#1d4ed8', border: '1px solid #bfdbfe' },
    self:   { background: '#fef3c7', color: '#92400e', border: '1px solid #fde68a' },
    simulated: { background: '#f3f4f6', color: '#6b7280', border: '1px solid #d1d5db' },
  }
  const label: Record<string, string> = {
    amazon: 'amazon',
    self: 'self',
    simulated: 'sim',
  }
  const style = styles[source] ?? styles['simulated']
  const text = label[source] ?? source
  return (
    <span style={{
      fontSize: 11,
      fontWeight: 500,
      borderRadius: 4,
      padding: '2px 5px',
      marginLeft: 6,
      ...style,
    }}>
      [{text}]
    </span>
  )
}

interface TooltipPayload {
  name: string
  value: number
  payload: ChartPoint
}

interface CustomTooltipProps {
  active?: boolean
  payload?: TooltipPayload[]
  label?: string
}

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload?.length) return null

  const point = payload[0].payload as ChartPoint
  const entry = payload[0]
  const price = entry.value

  return (
    <div style={{
      background: 'var(--bg-card, #fff)',
      border: '1px solid var(--border, #e5e7eb)',
      borderRadius: 6,
      padding: '8px 12px',
      fontSize: 13,
    }}>
      <p style={{ margin: 0, color: 'var(--text-muted, #6b7280)', fontSize: 12 }}>{point.fullDate}</p>
      <p style={{ margin: '4px 0 0', fontWeight: 600, color: 'var(--text-primary, #111)' }}>
        ${price.toFixed(2)}
        {sourceBadge(point.source)}
      </p>
    </div>
  )
}

export function PriceChart({ history }: Props) {
  const points = toChartPoints(history)

  if (!points.length) return <p>No successful price checks yet.</p>

  const tickInterval = points.length > 100 ? Math.floor(points.length / 8) : 'preserveStartEnd'
  const hasSimulated = points.some((p) => p.simPrice !== null)

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={points} data-testid="price-chart">
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="date" interval={tickInterval} tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip content={<CustomTooltip />} />
        {hasSimulated && <Legend
          formatter={(value) => value === 'price' ? 'Actual price' : 'Simulated (demo)'}
          wrapperStyle={{ fontSize: 12 }}
        />}
        <Line
          type="monotone"
          dataKey="price"
          name="price"
          dot={false}
          strokeWidth={2}
          connectNulls={false}
        />
        {hasSimulated && (
          <Line
            type="monotone"
            dataKey="simPrice"
            name="simPrice"
            dot={false}
            strokeWidth={1.5}
            stroke="#9ca3af"
            strokeDasharray="4 2"
            connectNulls={false}
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  )
}
