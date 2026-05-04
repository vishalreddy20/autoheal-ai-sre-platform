"""
Alert Correlator — groups and deduplicates alerts by service + condition fingerprint.
Uses Redis to track active incidents within a correlation window.
"""
import json
from datetime import datetime, timezone
from uuid import uuid4
from typing import List

import structlog
import redis.asyncio as aioredis

logger = structlog.get_logger(__name__)


class AlertCorrelator:
    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
        self.correlation_window = 120  # seconds

    async def correlate(self, alert: dict) -> str:
        """
        Returns a fingerprint string / incident_id for the alert.
        Alerts with the same fingerprint within correlation_window are grouped.
        """
        service = alert.get("service", "unknown")
        condition = alert.get("condition", "unknown")
        fingerprint = f"{service}:{condition}"

        # Check if an open incident already exists for this fingerprint
        try:
            existing = await self.redis.get(f"incident:active:{fingerprint}")
            if existing:
                data = json.loads(existing)
                return data["incident_id"]

            # New incident — store fingerprint with TTL
            incident_id = str(uuid4())
            await self.redis.setex(
                f"incident:active:{fingerprint}",
                self.correlation_window,
                json.dumps({
                    "incident_id": incident_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }),
            )
            return incident_id
        except Exception as exc:
            logger.warning("correlate_failed", error=str(exc))
            return str(uuid4())

    async def group_related_alerts(self, alerts: List[dict]) -> List[dict]:
        """
        Group alerts by service+time window into single incidents.
        Multiple conditions on same service → one grouped incident.
        """
        groups: dict = {}
        for alert in alerts:
            service = alert.get("service", "unknown")
            key = service
            if key not in groups:
                groups[key] = {
                    "service": service,
                    "conditions": [],
                    "severity": "low",
                    "alerts": [],
                }
            condition = alert.get("condition", "unknown")
            if condition not in groups[key]["conditions"]:
                groups[key]["conditions"].append(condition)
            groups[key]["alerts"].append(alert)

            # Escalate severity if multiple conditions hit same service
            cond_count = len(groups[key]["conditions"])
            if cond_count >= 3:
                groups[key]["severity"] = "critical"
            elif cond_count >= 2:
                groups[key]["severity"] = "high"
            else:
                groups[key]["severity"] = alert.get("severity", "low")

        return list(groups.values())

    async def clear_fingerprint(self, service: str, condition: str) -> None:
        """Clear the fingerprint when an incident is resolved."""
        fingerprint = f"{service}:{condition}"
        try:
            await self.redis.delete(f"incident:active:{fingerprint}")
        except Exception as exc:
            logger.warning("clear_fingerprint_failed", error=str(exc))
