export interface ServiceStatus {
  name: string;
  port: number;
  status: 'healthy' | 'degraded' | 'down' | 'unknown';
  uptime: number | null;
  reqPerSec: number | null;
  p99LatencyMs: number | null;
  lastChecked: string;
  sparkline: number[];
}

export interface Incident {
  id: string;
  service: string;
  issue_type: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  details: Record<string, unknown>;
  action_taken: string | null;
  resolved: boolean;
  detected_at: string;
  resolved_at: string | null;
}

export interface MetricsPayload {
  services: Record<string, {
    status: string;
    request_rate?: number | null;
    error_rate?: number | null;
    p99_latency_ms?: number | null;
  }>;
  ts: string;
}

export interface SLOPayload {
  latency_slo: number | null;
  availability_slo: number | null;
  error_rate_slo: number | null;
}

export interface SLOHistoryPoint extends SLOPayload {
  ts: string;
}

export interface SSEEvent {
  type: 'metrics' | 'incident' | 'status' | 'slo';
  payload: MetricsPayload | Incident | SLOPayload | Record<string, unknown>;
}

export interface MetricPoint {
  ts: number;
  value: number;
}

export interface ServiceMetrics {
  service: string;
  requestRate: MetricPoint[];
  errorRate: MetricPoint[];
  p99Latency: MetricPoint[];
}

export interface SimulationState {
  db_simulated_down: boolean;
  artificial_delays: Record<string, number>;
  request_id: string;
}

export interface ApiError {
  error: string;
  detail?: string;
  request_id: string;
}
