import { useDashboardStore } from '../store/dashboardStore'
import { ServiceStatusCard } from '../components/ServiceStatusCard'
import { MetricsLineChart } from '../components/MetricsChart'
import { Activity, AlertTriangle, Clock, TrendingUp } from 'lucide-react'

function MetricTile({
  label,
  value,
  unit,
  icon: Icon,
  color,
}: {
  label: string
  value: string
  unit?: string
  icon: React.ElementType
  color: string
}) {
  const accentClass =
    color === '#00D4AA'
      ? { panel: 'bg-teal-400/10', icon: 'text-teal-400', dot: 'bg-teal-400' }
      : color === '#F59E0B'
        ? { panel: 'bg-amber-400/10', icon: 'text-amber-400', dot: 'bg-amber-400' }
        : color === '#EF4444'
          ? { panel: 'bg-red-500/10', icon: 'text-red-500', dot: 'bg-red-500' }
          : { panel: 'bg-slate-400/10', icon: 'text-slate-400', dot: 'bg-slate-400' }

  return (
    <div className="glass-card rounded-xl p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-white/40 text-xs uppercase tracking-wider mb-2">{label}</p>
          <div className="flex items-baseline gap-1">
            <span className="font-mono text-2xl font-bold text-white">{value}</span>
            {unit && <span className="text-white/30 text-sm">{unit}</span>}
          </div>
        </div>
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${accentClass.panel}`}>
          <Icon className={`w-5 h-5 ${accentClass.icon}`} />
        </div>
      </div>
    </div>
  )
}

export function Dashboard() {
  const serviceStatuses = useDashboardStore((s) => s.serviceStatuses)
  const totalRequests5m = useDashboardStore((s) => s.totalRequests5m)
  const errorRateCurrent = useDashboardStore((s) => s.errorRateCurrent)
  const p99LatencyMs = useDashboardStore((s) => s.p99LatencyMs)
  const activeIncidentCount = useDashboardStore((s) => s.activeIncidentCount)
  const requestRatePoints = useDashboardStore((s) => s.requestRatePoints)
  const errorRatePoints = useDashboardStore((s) => s.errorRatePoints)
  const externalBase = `${window.location.protocol}//${window.location.hostname}`

  const services = ['api-gateway', 'user-service', 'task-service']
  const serviceColors = {
    'api-gateway': '#00D4AA',
    'user-service': '#818CF8',
    'task-service': '#F59E0B',
  }

  const formatMetric = (value: number | null, digits = 1) =>
    value === null ? '—' : value.toFixed(digits)

  const requestDatasets = services.map((svc) => ({
    label: svc,
    data: requestRatePoints[svc] ?? [],
    color: serviceColors[svc as keyof typeof serviceColors],
  }))

  const errorDatasets = services.map((svc) => ({
    label: svc,
    data: errorRatePoints[svc] ?? [],
    color: serviceColors[svc as keyof typeof serviceColors],
  }))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white mb-1">System Dashboard</h1>
        <p className="text-white/30 text-sm">Real-time overview of all microservices</p>
      </div>

      {/* Row 1 — Service Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {serviceStatuses.map((svc) => (
          <ServiceStatusCard key={svc.name} service={svc} />
        ))}
      </div>

      {/* Row 2 — Summary Tiles */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricTile
          label="Total Requests (5m)"
          value={totalRequests5m.toLocaleString()}
          icon={TrendingUp}
          color="#00D4AA"
        />
        <MetricTile
          label="Error Rate"
          value={errorRateCurrent === null ? '—' : (errorRateCurrent * 100).toFixed(2)}
          unit="%"
          icon={AlertTriangle}
          color={errorRateCurrent === null ? '#94A3B8' : errorRateCurrent > 0.05 ? '#EF4444' : '#00D4AA'}
        />
        <MetricTile
          label="P99 Latency"
          value={formatMetric(p99LatencyMs, 0)}
          unit="ms"
          icon={Clock}
          color={p99LatencyMs === null ? '#94A3B8' : p99LatencyMs > 500 ? '#EF4444' : p99LatencyMs > 200 ? '#F59E0B' : '#00D4AA'}
        />
        <MetricTile
          label="Active Incidents"
          value={activeIncidentCount.toString()}
          icon={Activity}
          color={activeIncidentCount > 0 ? '#EF4444' : '#00D4AA'}
        />
      </div>

      {/* Row 3 — Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <MetricsLineChart
          title="Request Rate (req/s)"
          datasets={requestDatasets}
          yUnit=" req/s"
        />
        <MetricsLineChart
          title="Error Rate"
          datasets={errorDatasets}
          yUnit="%"
        />
      </div>

      {/* Row 4 — External links */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: 'Grafana', url: `${externalBase}:3000`, color: '#F59E0B' },
          { label: 'Prometheus', url: `${externalBase}:9090`, color: '#EF4444' },
          { label: 'Jaeger', url: `${externalBase}:16686`, color: '#818CF8' },
          { label: 'Locust', url: `${externalBase}:8089`, color: '#00D4AA' },
        ].map(({ label, url, color }) => (
          <a
            key={label}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Open ${label} in new tab`}
            className="glass-card rounded-lg p-3 flex items-center gap-2 hover:border-white/15 transition-all duration-200 hover:translate-y-[-1px] border border-white/5"
          >
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${color === '#F59E0B' ? 'bg-amber-400' : color === '#EF4444' ? 'bg-red-500' : color === '#818CF8' ? 'bg-indigo-400' : 'bg-teal-400'}`} />
            <span className="text-white/60 text-sm">{label}</span>
            <span className="text-white/20 text-xs ml-auto">open</span>
          </a>
        ))}
      </div>
    </div>
  )
}
