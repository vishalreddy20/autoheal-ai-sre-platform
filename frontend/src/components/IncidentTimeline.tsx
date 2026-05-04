import type { Incident } from '../types'
import { formatDistanceToNow } from 'date-fns'
import { useState } from 'react'
import { ChevronDown, ChevronRight, CheckCircle, AlertCircle } from 'lucide-react'
import { formatIstDateTime } from '../utils/time'

interface Props {
  incidents: Incident[]
}

const severityStyles: Record<string, string> = {
  critical: 'bg-crimson-400/20 text-crimson-400 border-crimson-400/30',
  high: 'bg-orange-400/20 text-orange-400 border-orange-400/30',
  medium: 'bg-amber-400/20 text-amber-400 border-amber-400/30',
  low: 'bg-teal-400/20 text-teal-400 border-teal-400/30',
}

const issueTypeLabels: Record<string, string> = {
  high_error_rate: 'High Error Rate',
  high_latency: 'High Latency',
  health_check_fail: 'Health Check Failed',
  db_connectivity: 'DB Connectivity Issue',
  slo_violation: 'SLO Violation',
  restart_failed: 'Restart Failed',
}

function IncidentRow({ incident }: { incident: Incident }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="animate-slide-in border border-white/5 rounded-lg overflow-hidden mb-2 hover:border-white/10 transition-colors">
      <button
        className="w-full flex items-center gap-4 px-4 py-3 text-left hover:bg-white/2 transition-colors"
        onClick={() => setExpanded(!expanded)}
        aria-label={`Toggle details for incident ${incident.id}`}
      >
        {/* Severity badge */}
        <span
          className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border flex-shrink-0 ${severityStyles[incident.severity] ?? severityStyles.low}`}
        >
          {incident.severity}
        </span>

        {/* Service */}
        <span className="text-white/70 font-mono text-sm flex-shrink-0 w-28">{incident.service}</span>

        {/* Issue */}
        <span className="text-white text-sm flex-1">
          {issueTypeLabels[incident.issue_type] ?? incident.issue_type}
        </span>

        {/* Time */}
        <span className="text-white/30 text-xs flex-shrink-0 w-20 text-right">
          {formatDistanceToNow(new Date(incident.detected_at), { addSuffix: true })}
        </span>

        {/* Status */}
        <div className="flex-shrink-0 w-6">
          {incident.resolved ? (
            <CheckCircle className="w-4 h-4 text-teal-400" />
          ) : (
            <AlertCircle className="w-4 h-4 text-crimson-400" />
          )}
        </div>

        {/* Expand icon */}
        <div className="flex-shrink-0">
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-white/30" />
          ) : (
            <ChevronRight className="w-4 h-4 text-white/30" />
          )}
        </div>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-white/5 bg-navy-950/50">
          <div className="pt-3 grid grid-cols-2 gap-4 text-xs">
            <div>
              <p className="text-white/30 mb-1">Action Taken</p>
              <p className="text-white/70 font-mono">{incident.action_taken ?? 'none'}</p>
            </div>
            <div>
              <p className="text-white/30 mb-1">Detected At</p>
              <p className="text-white/70 font-mono">{formatIstDateTime(new Date(incident.detected_at))} IST</p>
            </div>
            {incident.resolved && incident.resolved_at && (
              <div>
                <p className="text-white/30 mb-1">Resolved At</p>
                <p className="text-teal-400 font-mono">{formatIstDateTime(new Date(incident.resolved_at))} IST</p>
              </div>
            )}
            <div className="col-span-2">
              <p className="text-white/30 mb-1">Raw Details</p>
              <pre className="text-white/50 text-[10px] bg-navy-950 rounded p-2 overflow-x-auto max-h-24 font-mono">
                {JSON.stringify(incident.details, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function IncidentTimeline({ incidents }: Props) {
  return (
    <div className="space-y-1">
      {incidents.length === 0 ? (
        <div className="text-center py-16 text-white/20">
          <CheckCircle className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">No incidents found</p>
        </div>
      ) : (
        incidents.map((inc) => <IncidentRow key={inc.id} incident={inc} />)
      )}
    </div>
  )
}
