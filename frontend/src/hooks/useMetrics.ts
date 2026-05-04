import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/client'

interface PrometheusResult {
  metric: Record<string, string>
  value: [number, string]
}

async function queryPrometheus(promQL: string): Promise<PrometheusResult[]> {
  const PROM_URL =
    import.meta.env.VITE_PROMETHEUS_URL ??
    import.meta.env.VITE_API_BASE_URL?.replace(':8000', ':9090') ??
    `${window.location.protocol}//${window.location.hostname}:9090`
  const resp = await apiClient.get<{
    data: { result: PrometheusResult[] }
  }>(`${PROM_URL}/api/v1/query`, { params: { query: promQL } })
  return resp.data.data.result ?? []
}

export function useRequestRate(service: string) {
  return useQuery({
    queryKey: ['requestRate', service],
    queryFn: () =>
      queryPrometheus(`rate(requests_total{service="${service}"}[1m])`),
    refetchInterval: false,
    staleTime: 30_000,
  })
}

export function useErrorRate(service: string) {
  return useQuery({
    queryKey: ['errorRate', service],
    queryFn: () =>
      queryPrometheus(
        `rate(requests_total{service="${service}",status_code=~"5.."}[1m]) / rate(requests_total{service="${service}"}[1m])`,
      ),
    refetchInterval: false,
    staleTime: 30_000,
  })
}

export function useP99Latency(service: string) {
  return useQuery({
    queryKey: ['p99Latency', service],
    queryFn: () =>
      queryPrometheus(
        `histogram_quantile(0.99, rate(request_latency_seconds_bucket{service="${service}"}[1m]))`,
      ),
    refetchInterval: false,
    staleTime: 30_000,
  })
}
