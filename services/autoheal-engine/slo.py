"""
SLO Monitor — multi-window burn rate analysis using Prometheus.
Implements Google SRE Book standard multi-window multi-burn-rate alerting.
"""
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)


class SLOMonitor:
    def __init__(self, prometheus_url: str):
        self.prom = prometheus_url

    async def _query(self, query: str) -> Optional[float]:
        """Execute a Prometheus instant query and return the scalar result."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.prom}/api/v1/query",
                    params={"query": query},
                )
                body = resp.json()
                results = body.get("data", {}).get("result", [])
                if results:
                    return float(results[0]["value"][1])
                return None
        except Exception as exc:
            logger.warning("slo_query_failed", query=query, error=str(exc))
            return None

    async def get_error_rate(self, service: str, window: str) -> float:
        """Query Prometheus for error rate over window (e.g. '5m', '1h', '6h')."""
        query = (
            f'rate(http_requests_total{{job="{service}",status=~"5.."}}[{window}])'
            f' / rate(http_requests_total{{job="{service}"}}[{window}])'
        )
        # Fallback to requests_total metric used in this platform
        query_fallback = (
            f'rate(requests_total{{service="{service}",status_code=~"5.."}}[{window}])'
            f' / rate(requests_total{{service="{service}"}}[{window}])'
        )
        result = await self._query(query)
        if result is None:
            result = await self._query(query_fallback)
        return float(result) if result is not None else 0.0

    async def check_burn_rates(self, service: str, slo_target: float = 0.999) -> dict:
        """
        Multi-window multi-burn-rate SLO check.
        Returns burn rate analysis for 5m, 1h, 6h windows.
        """
        error_budget = 1 - slo_target  # 0.001 for 99.9% SLO

        fast_burn = await self.get_error_rate(service, "5m")
        medium_burn = await self.get_error_rate(service, "1h")
        slow_burn = await self.get_error_rate(service, "6h")

        fast_burn_rate = fast_burn / error_budget if error_budget > 0 else 0
        medium_burn_rate = medium_burn / error_budget if error_budget > 0 else 0
        slow_burn_rate = slow_burn / error_budget if error_budget > 0 else 0

        # Multi-window burn rate alert conditions (Google SRE Book standard)
        critical = fast_burn_rate > 14.4 and medium_burn_rate > 14.4   # burns budget in 1h
        high     = fast_burn_rate > 6    and medium_burn_rate > 6       # burns budget in ~2.5h
        warning  = slow_burn_rate > 3                                   # burns budget in ~2 days

        # Fraction of error budget consumed = error_rate / error_budget
        budget_consumed = slow_burn / error_budget if error_budget > 0 else 1.0
        error_budget_remaining = max(0.0, 1.0 - budget_consumed)  # 0.0–1.0 scale

        return {
            "service": service,
            "slo_target": slo_target,
            "error_budget_remaining": round(error_budget_remaining * 100, 4),  # percent
            "burn_rates": {
                "5m": round(fast_burn_rate, 2),
                "1h": round(medium_burn_rate, 2),
                "6h": round(slow_burn_rate, 2),
            },
            "raw_error_rates": {
                "5m": round(fast_burn, 6),
                "1h": round(medium_burn, 6),
                "6h": round(slow_burn, 6),
            },
            "alert_level": "critical" if critical else "high" if high else "warning" if warning else "ok",
        }
