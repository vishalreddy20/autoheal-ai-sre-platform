import { useEffect, useState, useMemo } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { IncidentTimeline } from '../components/IncidentTimeline'
import type { Incident } from '../types'

type StatusFilter = 'all' | 'active' | 'resolved'
type SeverityFilter = 'all' | 'critical' | 'high' | 'medium' | 'low'

export function Incidents() {
  const incidents = useDashboardStore((s) => s.incidents)
  const fetchIncidents = useDashboardStore((s) => s.fetchIncidents)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all')
  const [serviceFilter, setServiceFilter] = useState('all')

  useEffect(() => {
    fetchIncidents()
  }, [fetchIncidents])

  const services = useMemo(() => {
    const s = new Set(incidents.map((i) => i.service))
    return ['all', ...Array.from(s)]
  }, [incidents])

  const filtered = useMemo(() => {
    return incidents.filter((inc: Incident) => {
      if (statusFilter === 'active' && inc.resolved) return false
      if (statusFilter === 'resolved' && !inc.resolved) return false
      if (severityFilter !== 'all' && inc.severity !== severityFilter) return false
      if (serviceFilter !== 'all' && inc.service !== serviceFilter) return false
      return true
    })
  }, [incidents, statusFilter, severityFilter, serviceFilter])

  const activeCount = incidents.filter((i) => !i.resolved).length
  const resolvedCount = incidents.filter((i) => i.resolved).length

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white mb-1">Incidents</h1>
        <div className="flex gap-4 text-sm">
          <span className="text-crimson-400 font-mono">{activeCount} active</span>
          <span className="text-teal-400 font-mono">{resolvedCount} resolved</span>
          <span className="text-white/30">{incidents.length} total</span>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-3 items-center">
        {/* Status filter */}
        <div className="flex rounded-lg overflow-hidden border border-white/10">
          {(['all', 'active', 'resolved'] as StatusFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              aria-label={`Filter by ${f} status`}
              className={`px-4 py-1.5 text-xs font-medium capitalize transition-colors ${
                statusFilter === f
                  ? 'bg-teal-400/20 text-teal-400'
                  : 'text-white/40 hover:text-white/60 hover:bg-white/5'
              }`}
            >
              {f}
            </button>
          ))}
        </div>

        {/* Severity filter */}
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value as SeverityFilter)}
          aria-label="Filter by severity"
          className="bg-navy-800 border border-white/10 text-white/60 text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:border-teal-400/50"
        >
          <option value="all">All Severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>

        {/* Service filter */}
        <select
          value={serviceFilter}
          onChange={(e) => setServiceFilter(e.target.value)}
          aria-label="Filter by service"
          className="bg-navy-800 border border-white/10 text-white/60 text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:border-teal-400/50"
        >
          {services.map((s) => (
            <option key={s} value={s}>{s === 'all' ? 'All Services' : s}</option>
          ))}
        </select>

        <span className="text-white/20 text-xs ml-auto">{filtered.length} matching</span>
      </div>

      {/* Timeline */}
      <div className="glass-card rounded-xl p-5">
        <IncidentTimeline incidents={filtered} />
      </div>
    </div>
  )
}
