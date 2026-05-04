import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { fetchAllIncidents } from '../api/endpoints'
import type { Incident, ServiceStatus, SLOPayload, SLOHistoryPoint, MetricPoint } from '../types'

const MAX_POINTS = 60 // Keep 60 data points (3 min at 3s interval)
const MAX_SAMPLES = 300

interface DashboardStore {
  // Connection
  sseConnected: boolean
  sseReconnecting: boolean
  setSseConnected: (v: boolean) => void
  setSseReconnecting: (v: boolean) => void

  // Service statuses
  serviceStatuses: ServiceStatus[]
  updateServiceStatus: (service: string, updates: Partial<ServiceStatus>) => void
  recordServiceHealth: (service: string, status: ServiceStatus['status'], ts: string) => void
  serviceHealthSamples: Record<string, Array<{ ts: string; up: boolean }>>

  // Incidents
  incidents: Incident[]
  addIncident: (inc: Incident) => void
  resolveIncident: (id: string, resolved_at: string) => void
  setIncidents: (incidents: Incident[]) => void
  fetchIncidents: () => Promise<void>

  // Metrics timeseries
  requestRatePoints: Record<string, MetricPoint[]>
  errorRatePoints: Record<string, MetricPoint[]>
  appendMetricPoint: (
    metric: 'requestRatePoints' | 'errorRatePoints',
    service: string,
    point: MetricPoint,
  ) => void

  // SLO
  slo: SLOPayload
  sloHistory: SLOHistoryPoint[]
  setSlo: (slo: SLOPayload) => void

  // Summary
  totalRequests5m: number
  errorRateCurrent: number | null
  p99LatencyMs: number | null
  activeIncidentCount: number
  setMetricsSummary: (r: number, e: number | null, l: number | null) => void
}

const DEFAULT_SERVICES: ServiceStatus[] = [
  { name: 'api-gateway', port: 8000, status: 'unknown', uptime: null, reqPerSec: null, p99LatencyMs: null, lastChecked: new Date().toISOString(), sparkline: [] },
  { name: 'user-service', port: 8001, status: 'unknown', uptime: null, reqPerSec: null, p99LatencyMs: null, lastChecked: new Date().toISOString(), sparkline: [] },
  { name: 'task-service', port: 8002, status: 'unknown', uptime: null, reqPerSec: null, p99LatencyMs: null, lastChecked: new Date().toISOString(), sparkline: [] },
]

function appendAndTrim(points: MetricPoint[], point: MetricPoint): MetricPoint[] {
  const next = [...points, point]
  if (next.length > MAX_POINTS) next.shift()
  return next
}

function appendHealthSample(
  samples: Record<string, Array<{ ts: string; up: boolean }>>,
  service: string,
  status: ServiceStatus['status'],
  ts: string,
) {
  const nextSamples = {
    ...samples,
    [service]: [
      ...(samples[service] ?? []),
      { ts, up: status !== 'down' && status !== 'unknown' },
    ].slice(-MAX_SAMPLES),
  }

  const serviceSamples = nextSamples[service]
  const uptime = serviceSamples.length
    ? (serviceSamples.filter((sample) => sample.up).length / serviceSamples.length) * 100
    : null

  return { nextSamples, uptime }
}

export const useDashboardStore = create<DashboardStore>()(
  persist(
    (set) => ({
  sseConnected: false,
  sseReconnecting: false,
  setSseConnected: (v) => set({ sseConnected: v }),
  setSseReconnecting: (v) => set({ sseReconnecting: v }),

  serviceStatuses: DEFAULT_SERVICES,
  serviceHealthSamples: {},
  updateServiceStatus: (service, updates) =>
    set((state) => ({
      serviceStatuses: state.serviceStatuses.map((s) =>
        s.name === service ? { ...s, ...updates } : s,
      ),
    })),
  recordServiceHealth: (service, status, ts) =>
    set((state) => {
      const { nextSamples, uptime } = appendHealthSample(state.serviceHealthSamples, service, status, ts)

      return {
        serviceHealthSamples: nextSamples,
        serviceStatuses: state.serviceStatuses.map((s) =>
          s.name === service ? { ...s, status, uptime, lastChecked: ts } : s,
        ),
      }
    }),

  incidents: [],
  addIncident: (inc) =>
    set((state) => {
      const existingIdx = state.incidents.findIndex((i) => i.id === inc.id)
      let incidents: Incident[]

      if (existingIdx >= 0) {
        incidents = state.incidents.map((i) => (i.id === inc.id ? { ...i, ...inc } : i))
      } else {
        incidents = [inc, ...state.incidents].slice(0, 200)
      }

      return {
        incidents,
        activeIncidentCount: incidents.filter((i) => !i.resolved).length,
      }
    }),
  resolveIncident: (id, resolved_at) =>
    set((state) => {
      const incidents = state.incidents.map((i) =>
        i.id === id ? { ...i, resolved: true, resolved_at } : i,
      )
      return {
        incidents,
        activeIncidentCount: incidents.filter((i) => !i.resolved).length,
      }
    }),
  setIncidents: (incidents) =>
    set({
      incidents,
      activeIncidentCount: incidents.filter((i) => !i.resolved).length,
    }),
  fetchIncidents: async () => {
    try {
      const response = await fetchAllIncidents()
      const incidents = response.data.incidents
      set({
        incidents,
        activeIncidentCount: incidents.filter((i) => !i.resolved).length,
      })
    } catch (error) {
      console.error('Failed to fetch incidents:', error)
    }
  },

  requestRatePoints: {},
  errorRatePoints: {},
  appendMetricPoint: (metric, service, point) =>
    set((state) => ({
      [metric]: {
        ...state[metric],
        [service]: appendAndTrim(state[metric][service] ?? [], point),
      },
    })),

  slo: { latency_slo: null, availability_slo: null, error_rate_slo: null },
  sloHistory: [] as SLOHistoryPoint[],
  setSlo: (slo) =>
    set((state) => ({
      slo,
      sloHistory: [
        ...state.sloHistory,
        { ts: new Date().toISOString(), ...slo },
      ].slice(-MAX_POINTS),
    })),

  totalRequests5m: 0,
  errorRateCurrent: null,
  p99LatencyMs: null,
  activeIncidentCount: 0,
  setMetricsSummary: (r, e, l) =>
    set({ totalRequests5m: r, errorRateCurrent: e, p99LatencyMs: l }),
    }),
    {
      name: 'autoheal-dashboard',
      partialize: (state) => ({
        incidents: state.incidents,
        sloHistory: state.sloHistory,
      }),
    },
  ),
)
