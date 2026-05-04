import { useEffect, useRef } from 'react'
import type { SSEEvent, Incident, MetricsPayload, SLOPayload, MetricPoint } from '../types'
import { useDashboardStore } from '../store/dashboardStore'

const SSE_URL = import.meta.env.VITE_SSE_URL ?? `${window.location.origin}/stream/events`
const MAX_BACKOFF = 30_000

function normalizeIncident(payload: Record<string, unknown>): Incident | null {
  const id = payload.id
  if (typeof id !== 'string' || !id) return null

  const ts =
    (typeof payload.detected_at === 'string' && payload.detected_at) ||
    (typeof payload.ts === 'string' && payload.ts) ||
    new Date().toISOString()

  const resolved = Boolean(payload.resolved)
  const resolvedAt =
    (typeof payload.resolved_at === 'string' && payload.resolved_at) ||
    (resolved && typeof payload.ts === 'string' ? payload.ts : null)

  return {
    id,
    service: typeof payload.service === 'string' ? payload.service : 'unknown',
    issue_type: typeof payload.issue_type === 'string' ? payload.issue_type : 'unknown_issue',
    severity:
      payload.severity === 'critical' || payload.severity === 'high' || payload.severity === 'medium' || payload.severity === 'low'
        ? payload.severity
        : 'medium',
    details:
      payload.details && typeof payload.details === 'object' && !Array.isArray(payload.details)
        ? (payload.details as Record<string, unknown>)
        : {},
    action_taken:
      typeof payload.action_taken === 'string'
        ? payload.action_taken
        : typeof payload.action === 'string'
          ? payload.action
          : null,
    resolved,
    detected_at: ts,
    resolved_at: resolvedAt,
  }
}

function safeOptionalNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export function useSSE(): void {
  const esRef = useRef<EventSource | null>(null)
  const backoffRef = useRef<number>(1_000)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const setSseConnected = useDashboardStore((s) => s.setSseConnected)
  const setSseReconnecting = useDashboardStore((s) => s.setSseReconnecting)
  const addIncident = useDashboardStore((s) => s.addIncident)
  const resolveIncident = useDashboardStore((s) => s.resolveIncident)
  const recordServiceHealth = useDashboardStore((s) => s.recordServiceHealth)
  const updateServiceStatus = useDashboardStore((s) => s.updateServiceStatus)
  const appendMetricPoint = useDashboardStore((s) => s.appendMetricPoint)
  const setMetricsSummary = useDashboardStore((s) => s.setMetricsSummary)
  const setSlo = useDashboardStore((s) => s.setSlo)

  function connect() {
    if (esRef.current) {
      esRef.current.close()
    }

    const es = new EventSource(SSE_URL)
    esRef.current = es

    es.onopen = () => {
      setSseConnected(true)
      setSseReconnecting(false)
      backoffRef.current = 1_000
    }

    es.onmessage = (event: MessageEvent) => {
      try {
        const parsed: SSEEvent = JSON.parse(event.data as string)
        if (parsed.type === 'metrics') {
          const p = parsed.payload as MetricsPayload
          const services = p.services ?? {}
          const ts = Date.parse(p.ts) || Date.now()

          let totalReqPerSec = 0
          let weightedErrorNumerator = 0
          let maxP99Ms = 0

          for (const [svcName, data] of Object.entries(services)) {
            const requestRate = safeOptionalNumber(data.request_rate)
            const errorRate = safeOptionalNumber(data.error_rate)
            const p99LatencyMs = safeOptionalNumber(data.p99_latency_ms)

            let status: 'healthy' | 'degraded' | 'down' = 'healthy'
            if (data.status !== 'up' || (errorRate ?? 0) >= 0.95) {
              status = 'down'
            } else if ((errorRate ?? 0) > 0.05 || (p99LatencyMs ?? 0) > 500) {
              status = 'degraded'
            }

            recordServiceHealth(svcName, status, p.ts)
            updateServiceStatus(svcName, {
              reqPerSec: requestRate,
              p99LatencyMs,
            })

            if (requestRate !== null) {
              const point: MetricPoint = { ts, value: requestRate }
              appendMetricPoint('requestRatePoints', svcName, point)
            }
            if (errorRate !== null) {
              appendMetricPoint('errorRatePoints', svcName, { ts, value: errorRate })
            }

            if (requestRate !== null) totalReqPerSec += requestRate
            if (requestRate !== null && errorRate !== null) {
              weightedErrorNumerator += requestRate * errorRate
            }
            if (p99LatencyMs !== null) maxP99Ms = Math.max(maxP99Ms, p99LatencyMs)
          }

          const totalRequests5m = Math.round(totalReqPerSec * 300)
          const currentErrorRate = totalReqPerSec > 0 ? weightedErrorNumerator / totalReqPerSec : null
          setMetricsSummary(totalRequests5m, currentErrorRate, maxP99Ms > 0 ? maxP99Ms : null)
        } else if (parsed.type === 'incident') {
          const inc = normalizeIncident(parsed.payload as Record<string, unknown>)
          if (inc) {
            addIncident(inc)
            if (inc.resolved && inc.resolved_at) {
              resolveIncident(inc.id, inc.resolved_at)
            }
          }
        } else if (parsed.type === 'slo') {
          setSlo(parsed.payload as SLOPayload)
        }
      } catch {
        // Ignore parse errors (keep-alive comments, etc.)
      }
    }

    es.onerror = () => {
      setSseConnected(false)
      setSseReconnecting(true)
      es.close()
      esRef.current = null

      const delay = backoffRef.current
      backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF)

      reconnectTimerRef.current = setTimeout(() => {
        connect()
      }, delay)
    }
  }

  useEffect(() => {
    connect()

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
