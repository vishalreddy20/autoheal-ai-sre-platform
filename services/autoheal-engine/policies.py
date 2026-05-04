"""
Policy Engine — loads remediation policies from YAML and enforces cooldowns,
max attempts, and escalation via Redis.
"""
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import structlog
import yaml
import redis.asyncio as aioredis

logger = structlog.get_logger(__name__)

# Default path to policies file, overridable via env
POLICIES_PATH = os.environ.get(
    "POLICIES_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "config", "remediation-policies.yml"),
)


@dataclass
class Policy:
    name: str
    condition: str
    action: str
    cooldown_minutes: int
    max_attempts: int
    escalation: str
    dry_run: bool


def _load_policies(path: str) -> List[Policy]:
    """Load policies from YAML file at startup."""
    try:
        abs_path = os.path.abspath(path)
        with open(abs_path, "r") as f:
            data = yaml.safe_load(f)
        policies = []
        for p in data.get("policies", []):
            policies.append(Policy(
                name=p["name"],
                condition=p["match"]["condition"],
                action=p["action"],
                cooldown_minutes=p.get("cooldown_minutes", 5),
                max_attempts=p.get("max_attempts", 3),
                escalation=p.get("escalation", "log_incident"),
                dry_run=p.get("dry_run", False),
            ))
        logger.info("policies_loaded", count=len(policies), path=abs_path)
        return policies
    except FileNotFoundError:
        logger.warning("policies_file_not_found", path=path)
        return []
    except Exception as exc:
        logger.error("policies_load_failed", error=str(exc))
        return []


class PolicyEngine:
    def __init__(self, redis_client: aioredis.Redis, policies_path: str = POLICIES_PATH):
        self.redis = redis_client
        self.policies: List[Policy] = _load_policies(policies_path)
        self._policy_map: Dict[str, Policy] = {p.condition: p for p in self.policies}

    def get_policy(self, condition: str) -> Optional[Policy]:
        """Return matching policy for a condition, or None."""
        return self._policy_map.get(condition)

    def all_policies(self) -> List[dict]:
        """Return all loaded policies as list of dicts."""
        return [
            {
                "name": p.name,
                "condition": p.condition,
                "action": p.action,
                "cooldown_minutes": p.cooldown_minutes,
                "max_attempts": p.max_attempts,
                "escalation": p.escalation,
                "dry_run": p.dry_run,
            }
            for p in self.policies
        ]

    async def enforce_cooldown(self, service: str, action: str) -> bool:
        """
        Returns True if cooldown is still active (action should be skipped).
        Returns False if cooldown has elapsed (action can proceed).
        Checks Redis key directly — no policy lookup needed.
        """
        key = f"healing:cooldown:{service}:{action}"
        try:
            value = await self.redis.get(key)
            return value is not None
        except Exception as exc:
            logger.warning("cooldown_check_failed", error=str(exc))
            return False

    async def set_cooldown(self, service: str, action: str, cooldown_minutes: int) -> None:
        """Set a cooldown key in Redis with TTL matching cooldown_minutes."""
        key = f"healing:cooldown:{service}:{action}"
        ttl_seconds = cooldown_minutes * 60
        try:
            await self.redis.setex(key, ttl_seconds, "1")
        except Exception as exc:
            logger.warning("cooldown_set_failed", error=str(exc))

    async def increment_attempt(self, service: str, action: str, cooldown_minutes: int) -> int:
        """Increment attempt counter in Redis. Returns new count."""
        key = f"healing:attempts:{service}:{action}"
        ttl_seconds = cooldown_minutes * 60
        try:
            count = await self.redis.incr(key)
            if count == 1:
                await self.redis.expire(key, ttl_seconds)
            return count
        except Exception as exc:
            logger.warning("increment_attempt_failed", error=str(exc))
            return 0

    async def exceeded_max_attempts(self, service: str, action: str, max_attempts: int) -> bool:
        """Returns True if attempt count >= max_attempts."""
        key = f"healing:attempts:{service}:{action}"
        try:
            value = await self.redis.get(key)
            if value is None:
                return False
            return int(value) >= max_attempts
        except Exception as exc:
            logger.warning("max_attempts_check_failed", error=str(exc))
            return False
