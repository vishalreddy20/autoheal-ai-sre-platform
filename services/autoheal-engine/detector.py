"""
Detector — evaluates monitoring rules against live Prometheus data and health checks.
Returns DetectionResult objects consumed by the healer.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx
import structlog

from config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

MONITORED_SERVICES = {
    "api-gateway": settings.api_gateway_url,
    "user-service": settings.user_service_url,
    "task-service": settings.task_service_url,
}


@dataclass
class DetectionResult:
    service: str
    issue_type: str      # "high_error_rate" | "high_latency" | "health_check_fail" | "db_connectivity" | "slo_violation"
    severity: str        # "low" | "medium" | "high" | "critical"
    action: str          # "RESTART_SERVICE" | "THROTTLE_TRAFFIC" | "DB_FAILOVER" | "LOG_INCIDENT"
    details: Dict        = field(default_factory=dict)
    ts: str              = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Redis client (injected by main.py at startup) ─────────────────────────────
_redis_client = None

# In-memory fallback (used when Redis is unavailable)
_health_fail_counts_local: Dict[str, int] = {s: 0 for s in MONITORED_SERVICES}
_HEALTH_FAIL_TTL = 600  # 10 minutes — auto-expiry to handle process restarts


def set_redis_client(client) -> None:
    """Called by main.py at startup to inject the shared Redis client."""
    global _redis_client
    _redis_client = client


async def _get_health_fail_count(service: str) -> int:
    """Get consecutive health-check failure count. Redis-backed, local fallback."""
    if _redis_client is not None:
        try:
            val = await _redis_client.get(f"health:fail_count:{service}")
            return int(val) if val else 0
        except Exception:
            pass
    return _health_fail_counts_local.get(service, 0)


async def _set_health_fail_count(service: str, count: int) -> None:
    """Persist consecutive health-check failure count. Redis-backed, local fallback."""
    _health_fail_counts_local[service] = count  # Always update local as fallback
    if _redis_client is not None:
        try:
            if count == 0:
                await _redis_client.delete(f"health:fail_count:{service}")
            else:
                await _redis_client.setex(
                    f"health:fail_count:{service}", _HEALTH_FAIL_TTL, str(count)
                )
        except Exception:
            pass


async def _prom_query(client: httpx.AsyncClient, query: str) -> Optional[float]:
    """Query Prometheus instant API. Returns the first result value or None."""
    try:
        resp = await client.get(
            f"{settings.prometheus_url}/api/v1/query",
            params={"query": query},
            timeout=5.0,
        )
        data = resp.json()
        results = data.get("data", {}).get("result", [])
        if results:
            val = float(results[0]["value"][1])
            import math
            if math.isnan(val):
                return 0.0
            return val
        return None
    except Exception as exc:
        logger.warning("prometheus_query_failed", query=query, error=str(exc))
        return None


async def _check_health(client: httpx.AsyncClient, service: str, url: str) -> bool:
    try:
        resp = await client.get(f"{url}/health", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


async def run_detection(client: httpx.AsyncClient) -> List[DetectionResult]:
    """Run all detection rules and return list of triggered incidents."""
    results: List[DetectionResult] = []

    # ── Rule 1: Error Rate ────────────────────────────────────────────────────
    # Skip api-gateway: its 5xx responses are proxied from downstream services,
    # so detecting them here creates a feedback loop that blocks real healing.
    for service in MONITORED_SERVICES:
        if service == "api-gateway":
            continue
        query = (
            f'rate(requests_total{{service="{service}",status_code=~"5.."}}[1m])'
            f' / rate(requests_total{{service="{service}"}}[1m])'
        )
        error_rate = await _prom_query(client, query)
        if error_rate is not None and error_rate > 0.05:
            if error_rate > 0.30:
                severity = "critical"
            elif error_rate > 0.15:
                severity = "high"
            else:
                severity = "medium"
            results.append(DetectionResult(
                service=service,
                issue_type="high_error_rate",
                severity=severity,
                action="RESTART_SERVICE",
                details={"error_rate": round(error_rate, 4), "threshold": 0.05},
            ))
            logger.warning("rule_error_rate_triggered", service=service, rate=error_rate)

    # ── Rule 2: P99 Latency ────────────────────────────────────────────────────
    for service in MONITORED_SERVICES:
        if service == "api-gateway":
            continue
        query = (
            f'histogram_quantile(0.99, rate(request_latency_seconds_bucket'
            f'{{service="{service}"}}[1m]))'
        )
        latency = await _prom_query(client, query)
        if latency is not None and latency > 0.5:
            severity = "high" if latency > 1.0 else "medium"
            results.append(DetectionResult(
                service=service,
                issue_type="high_latency",
                severity=severity,
                action="THROTTLE_TRAFFIC",
                details={"latency_p99_s": round(latency, 4), "threshold_s": 0.5},
            ))
            logger.warning("rule_latency_triggered", service=service, latency=latency)

    # ── Rule 3: Health Check Fail (3 consecutive) — Redis-backed ──────────────
    for service, url in MONITORED_SERVICES.items():
        if service == "api-gateway":
            continue
        ok = await _check_health(client, service, url)
        if ok:
            await _set_health_fail_count(service, 0)
        else:
            current = await _get_health_fail_count(service)
            new_count = current + 1
            await _set_health_fail_count(service, new_count)
            logger.warning("health_check_failed", service=service, count=new_count)
            if new_count >= 3:
                results.append(DetectionResult(
                    service=service,
                    issue_type="health_check_fail",
                    severity="critical",
                    action="RESTART_SERVICE",
                    details={"consecutive_failures": new_count},
                ))

    # ── Rule 4: DB Connectivity (probe via ready endpoint) ────────────────────
    for service, url in MONITORED_SERVICES.items():
        if service == "api-gateway":
            continue
        try:
            resp = await client.get(f"{url}/ready", timeout=5.0)
            data = resp.json()
            if not data.get("ready", True) or data.get("db") == "error":
                results.append(DetectionResult(
                    service=service,
                    issue_type="db_connectivity",
                    severity="critical",
                    action="DB_FAILOVER",
                    details={"ready_response": data},
                ))
        except Exception as exc:
            results.append(DetectionResult(
                service=service,
                issue_type="db_connectivity",
                severity="critical",
                action="DB_FAILOVER",
                details={"error": str(exc)},
            ))

    # ── Rule 5: SLO P95 Latency ────────────────────────────────────────────────
    for service in MONITORED_SERVICES:
        if service == "api-gateway":
            continue
        query = (
            f'histogram_quantile(0.95, rate(request_latency_seconds_bucket'
            f'{{service="{service}"}}[1m]))'
        )
        p95 = await _prom_query(client, query)
        if p95 is not None and p95 > 0.2:
            results.append(DetectionResult(
                service=service,
                issue_type="high_latency",
                severity="medium",
                action="THROTTLE_TRAFFIC",
                details={"latency_p95_s": round(p95, 4), "slo_threshold_s": 0.2},
            ))

    return results


async def get_metrics_snapshot(client: httpx.AsyncClient, service: str) -> Dict:
    """Collect current metrics for a service for metrics_snapshots table."""
    error_rate_query = (
        f'rate(requests_total{{service="{service}",status_code=~"5.."}}[1m])'
        f' / rate(requests_total{{service="{service}"}}[1m])'
    )
    latency_query = (
        f'histogram_quantile(0.99, rate(request_latency_seconds_bucket'
        f'{{service="{service}"}}[1m]))'
    )
    req_count_query = f'rate(requests_total{{service="{service}"}}[1m])'

    error_rate = await _prom_query(client, error_rate_query) or 0.0
    latency = await _prom_query(client, latency_query) or 0.0
    req_count = await _prom_query(client, req_count_query) or 0.0

    return {
        "service": service,
        "error_rate": round(error_rate, 4),
        "latency_p99_ms": round(latency * 1000, 2),
        "request_count": int(req_count),
    }
