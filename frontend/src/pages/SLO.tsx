import { useDashboardStore } from '../store/dashboardStore'
import { SLOGauge } from '../components/SLOGauge'
import { formatIstTime } from '../utils/time'

const SLO_TARGETS = {
  latency_slo: 95,
  availability_slo: 99,
  error_rate_slo: 99,
}

const SLO_LABELS = {
  latency_slo: 'Latency SLO (P95 < 200ms)',
  availability_slo: 'Availability SLO (99% uptime)',
  error_rate_slo: 'Error Rate SLO (< 1%)',
}

function cellColor(value: number | null, target: number): string {
  if (value === null) return 'text-white/35'
  if (value >= target) return 'text-teal-400'
  if (value >= target - 4) return 'text-amber-400'
  return 'text-crimson-400'
}

export function SLO() {
  const slo = useDashboardStore((s) => s.slo)
  const history = useDashboardStore((s) => s.sloHistory)

  // Error budget calculation (minutes)
  const budget = {
    latency: slo.latency_slo === null ? null : ((slo.latency_slo - 95) / 100) * 24 * 60,
    availability: slo.availability_slo === null ? null : ((slo.availability_slo - 99) / 100) * 24 * 60,
    error_rate: slo.error_rate_slo === null ? null : ((slo.error_rate_slo - 99) / 100) * 24 * 60,
  }

  const formatBudget = (value: number | null) => {
    if (value === null) return '—'
    return value >= 0 ? `+${value.toFixed(0)}m` : `${value.toFixed(0)}m`
  }

  const budgetFill = (value: number | null) => {
    if (value === null) return { filled: 0, active: 'bg-slate-400' }
    const normalized = Math.min(100, Math.max(0, ((value + 60) / 120) * 100))
    return {
      filled: Math.round((normalized / 100) * 12),
      active: value >= 0 ? 'bg-teal-400' : 'bg-red-500',
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white mb-1">SLO Dashboard</h1>
        <p className="text-white/30 text-sm">Service Level Objectives tracking and compliance</p>
      </div>

      {/* SLO Gauges */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <SLOGauge
          label={SLO_LABELS.latency_slo}
          value={slo.latency_slo}
          target={SLO_TARGETS.latency_slo}
        />
        <SLOGauge
          label={SLO_LABELS.availability_slo}
          value={slo.availability_slo}
          target={SLO_TARGETS.availability_slo}
        />
        <SLOGauge
          label={SLO_LABELS.error_rate_slo}
          value={slo.error_rate_slo}
          target={SLO_TARGETS.error_rate_slo}
        />
      </div>

      {/* Error Budget Panel */}
      <div className="glass-card rounded-xl p-6">
        <h3 className="text-white font-semibold text-sm mb-4">Error Budget (24h window)</h3>
        <div className="grid grid-cols-3 gap-6">
          {[
            { label: 'Latency SLO', budget: budget.latency },
            { label: 'Availability SLO', budget: budget.availability },
            { label: 'Error Rate SLO', budget: budget.error_rate },
          ].map(({ label, budget: b }) => (
            (() => {
              const bar = budgetFill(b)
              return (
            <div key={label}>
              <p className="text-white/40 text-xs mb-1">{label}</p>
              <p className={`font-mono text-lg font-bold ${b === null ? 'text-white/35' : b >= 0 ? 'text-teal-400' : 'text-crimson-400'}`}>
                {formatBudget(b)}
              </p>
              <div className="mt-2 grid grid-cols-12 gap-1">
                {Array.from({ length: 12 }, (_, idx) => (
                  <div
                    key={idx}
                    className={`h-1.5 rounded-full ${idx < bar.filled ? bar.active : 'bg-white/5'}`}
                  />
                ))}
              </div>
            </div>
              )
            })()
          ))}
        </div>
      </div>

      {/* SLO History Table */}
      <div className="glass-card rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-white/5">
          <h3 className="text-white font-semibold text-sm">SLO History (Last 24h, 30-min buckets)</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-white/5">
                <th className="text-left px-6 py-3 text-white/30 font-medium">Time</th>
                <th className="text-right px-4 py-3 text-white/30 font-medium">Latency SLO %</th>
                <th className="text-right px-4 py-3 text-white/30 font-medium">Availability %</th>
                <th className="text-right px-6 py-3 text-white/30 font-medium">Error Rate SLO %</th>
              </tr>
            </thead>
            <tbody>
              {history.length > 0 ? history.slice(-24).map((row, idx) => (
                <tr key={idx} className="border-b border-white/5 hover:bg-white/2 transition-colors">
                  <td className="px-6 py-2.5 font-mono text-white/50">{formatIstTime(new Date(row.ts))} IST</td>
                  <td className={`px-4 py-2.5 font-mono text-right ${cellColor(row.latency_slo, 95)}`}>
                    {row.latency_slo === null ? '—' : `${row.latency_slo.toFixed(1)}%`}
                  </td>
                  <td className={`px-4 py-2.5 font-mono text-right ${cellColor(row.availability_slo, 99)}`}>
                    {row.availability_slo === null ? '—' : `${row.availability_slo.toFixed(1)}%`}
                  </td>
                  <td className={`px-6 py-2.5 font-mono text-right ${cellColor(row.error_rate_slo, 99)}`}>
                    {row.error_rate_slo === null ? '—' : `${row.error_rate_slo.toFixed(1)}%`}
                  </td>
                </tr>
              )) : (
                <tr>
                  <td className="px-6 py-8 text-center text-white/35" colSpan={4}>
                    Waiting for live SLO data from the stream.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
