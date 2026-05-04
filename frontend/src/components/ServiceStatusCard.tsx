import type { ServiceStatus } from '../types'
import { formatDistanceToNow } from 'date-fns'

interface Props {
  service: ServiceStatus
}

const statusColors = {
  healthy: 'text-teal-400',
  degraded: 'text-amber-400',
  down: 'text-crimson-400',
  unknown: 'text-white/40',
}

const dotColors = {
  healthy: 'bg-teal-400',
  degraded: 'bg-amber-400',
  down: 'bg-crimson-400',
  unknown: 'bg-white/25',
}

export function ServiceStatusCard({ service }: Props) {
  const color = statusColors[service.status]
  const dot = dotColors[service.status]
  const isAlive = service.status !== 'down' && service.status !== 'unknown'

  const formatMetric = (value: number | null, digits = 1, suffix = '') =>
    value === null ? '—' : `${value.toFixed(digits)}${suffix}`

  // Mini sparkline using SVG
  const max = Math.max(...service.sparkline, 1)
  const points = service.sparkline
    .map((v, i) => {
      const x = (i / Math.max(service.sparkline.length - 1, 1)) * 100
      const y = 20 - (v / max) * 18
      return `${x},${y}`
    })
    .join(' ')

  return (
    <div className="glass-card rounded-xl p-5 flex flex-col gap-4 border border-white/8 hover:border-white/12 transition-all duration-300 hover:translate-y-[-2px] hover:shadow-lg">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            {/* Pulsing dot */}
            <span className="relative flex h-2.5 w-2.5">
              {isAlive && (
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${dot} opacity-60`} />
              )}
              <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${dot}`} />
            </span>
            <h3 className="text-white font-semibold text-sm font-mono">{service.name}</h3>
          </div>
          <p className="text-white/30 text-xs ml-4.5">:{service.port}</p>
        </div>
        <span className={`text-xs font-bold uppercase tracking-wider ${color} bg-white/5 px-2 py-0.5 rounded`}>
          {service.status}
        </span>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <p className="text-white/30 text-[10px] uppercase tracking-wider mb-0.5">Uptime</p>
          <p className={`font-mono text-sm font-semibold ${color}`}>{formatMetric(service.uptime, 1, '%')}</p>
        </div>
        <div>
          <p className="text-white/30 text-[10px] uppercase tracking-wider mb-0.5">Req/s</p>
          <p className="font-mono text-sm font-semibold text-white">{formatMetric(service.reqPerSec, 1)}</p>
        </div>
        <div>
          <p className="text-white/30 text-[10px] uppercase tracking-wider mb-0.5">P99</p>
          <p className="font-mono text-sm font-semibold text-white">{formatMetric(service.p99LatencyMs, 0, 'ms')}</p>
        </div>
      </div>

      {/* Sparkline */}
      {service.sparkline.length > 1 && (
        <svg viewBox="0 0 100 20" className="w-full h-8 opacity-60" preserveAspectRatio="none">
          <polyline
            points={points}
            fill="none"
            stroke={service.status === 'healthy' ? '#00D4AA' : service.status === 'degraded' ? '#F59E0B' : '#EF4444'}
            strokeWidth="1.5"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        </svg>
      )}

      {/* Last checked */}
      <p className="text-white/20 text-[10px]">
        Checked {formatDistanceToNow(new Date(service.lastChecked), { addSuffix: true })}
      </p>
    </div>
  )
}
