"""
Unit tests for AlertCorrelator.
"""
import asyncio
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "autoheal-engine"))


class FakeRedis:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def setex(self, key, ttl, value):
        self._store[key] = value

    async def delete(self, *keys):
        for k in keys:
            self._store.pop(k, None)


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def correlator(fake_redis):
    from correlator import AlertCorrelator
    return AlertCorrelator(redis_client=fake_redis)


class TestAlertCorrelator:
    @pytest.mark.asyncio
    async def test_new_alert_creates_incident_id(self, correlator):
        alert = {"service": "user-service", "condition": "high_error_rate"}
        incident_id = await correlator.correlate(alert)
        assert incident_id is not None
        assert len(incident_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_duplicate_alert_same_incident(self, correlator):
        alert = {"service": "user-service", "condition": "high_error_rate"}
        id1 = await correlator.correlate(alert)
        id2 = await correlator.correlate(alert)
        assert id1 == id2

    @pytest.mark.asyncio
    async def test_different_conditions_different_incidents(self, correlator):
        alert1 = {"service": "user-service", "condition": "high_error_rate"}
        alert2 = {"service": "user-service", "condition": "high_latency"}
        id1 = await correlator.correlate(alert1)
        id2 = await correlator.correlate(alert2)
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_clear_fingerprint(self, correlator):
        alert = {"service": "user-service", "condition": "high_error_rate"}
        id1 = await correlator.correlate(alert)
        await correlator.clear_fingerprint("user-service", "high_error_rate")
        id2 = await correlator.correlate(alert)
        assert id1 != id2  # New incident after clear

    @pytest.mark.asyncio
    async def test_group_related_alerts(self, correlator):
        alerts = [
            {"service": "api-gateway", "condition": "high_error_rate", "severity": "critical"},
            {"service": "api-gateway", "condition": "high_latency", "severity": "warning"},
            {"service": "user-service", "condition": "db_connectivity", "severity": "high"},
        ]
        groups = await correlator.group_related_alerts(alerts)
        assert len(groups) == 2  # api-gateway and user-service
        gw = next(g for g in groups if g["service"] == "api-gateway")
        assert len(gw["conditions"]) == 2
        assert gw["severity"] == "high"  # escalated due to 2 conditions
