"""
Unit tests for PolicyEngine.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "autoheal-engine"))


class FakeRedis:
    """In-memory fake Redis for testing."""
    def __init__(self):
        self._store = {}
        self._ttls = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ex=None):
        self._store[key] = value
        if ex:
            self._ttls[key] = ex

    async def setex(self, key, ttl, value):
        self._store[key] = value
        self._ttls[key] = ttl

    async def incr(self, key):
        self._store[key] = str(int(self._store.get(key, "0")) + 1)
        return int(self._store[key])

    async def expire(self, key, ttl):
        self._ttls[key] = ttl

    async def delete(self, *keys):
        for k in keys:
            self._store.pop(k, None)


POLICY_YAML = """
policies:
  - name: restart-on-error
    match:
      condition: high_error_rate
    action: RESTART_SERVICE
    cooldown_minutes: 5
    max_attempts: 2
    escalation: log_incident
    dry_run: false
  - name: throttle-latency
    match:
      condition: high_latency
    action: THROTTLE_TRAFFIC
    cooldown_minutes: 3
    max_attempts: 3
    escalation: log_incident
    dry_run: false
"""


@pytest.fixture
def tmp_policy_file(tmp_path):
    p = tmp_path / "policies.yml"
    p.write_text(POLICY_YAML)
    return str(p)


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def engine(fake_redis, tmp_policy_file):
    from policies import PolicyEngine
    return PolicyEngine(redis_client=fake_redis, policies_path=tmp_policy_file)


class TestPolicyEngine:
    def test_policies_loaded(self, engine):
        assert len(engine.policies) == 2

    def test_get_policy_match(self, engine):
        p = engine.get_policy("high_error_rate")
        assert p is not None
        assert p.action == "RESTART_SERVICE"
        assert p.cooldown_minutes == 5

    def test_get_policy_no_match(self, engine):
        assert engine.get_policy("nonexistent_condition") is None

    def test_all_policies_returns_list(self, engine):
        all_p = engine.all_policies()
        assert isinstance(all_p, list)
        assert len(all_p) == 2
        assert all_p[0]["name"] == "restart-on-error"

    @pytest.mark.asyncio
    async def test_cooldown_not_active_initially(self, engine):
        assert await engine.enforce_cooldown("user-service", "RESTART_SERVICE") is False

    @pytest.mark.asyncio
    async def test_cooldown_active_after_set(self, engine):
        await engine.set_cooldown("user-service", "RESTART_SERVICE", 5)
        assert await engine.enforce_cooldown("user-service", "RESTART_SERVICE") is True

    @pytest.mark.asyncio
    async def test_increment_attempt(self, engine):
        count = await engine.increment_attempt("user-service", "RESTART_SERVICE", 5)
        assert count == 1
        count = await engine.increment_attempt("user-service", "RESTART_SERVICE", 5)
        assert count == 2

    @pytest.mark.asyncio
    async def test_max_attempts_not_exceeded(self, engine):
        # max_attempts=2, count=1 — not exceeded
        await engine.increment_attempt("user-service", "RESTART_SERVICE", 5)
        assert await engine.exceeded_max_attempts("user-service", "RESTART_SERVICE", 2) is False

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded(self, engine):
        await engine.increment_attempt("user-service", "RESTART_SERVICE", 5)
        await engine.increment_attempt("user-service", "RESTART_SERVICE", 5)
        assert await engine.exceeded_max_attempts("user-service", "RESTART_SERVICE", 2) is True
