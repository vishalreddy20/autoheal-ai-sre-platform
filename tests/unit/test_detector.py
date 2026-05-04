"""
Unit tests for detector.py.
"""
import pytest
from unittest.mock import AsyncMock, patch
import httpx
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "autoheal-engine"))

from detector import (
    run_detection,
    get_metrics_snapshot,
    _get_health_fail_count,
    _set_health_fail_count,
    set_redis_client,
    DetectionResult,
    MONITORED_SERVICES,
)


class FakeRedis:
    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def setex(self, key, ttl, value):
        self._store[key] = value

    async def delete(self, key):
        self._store.pop(key, None)


@pytest.fixture
def fake_redis():
    client = FakeRedis()
    set_redis_client(client)
    yield client
    set_redis_client(None)


@pytest.fixture
def mock_httpx_client():
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.mark.asyncio
async def test_set_get_health_fail_count(fake_redis):
    # Test Redis backed
    await _set_health_fail_count("test-service", 2)
    assert await _get_health_fail_count("test-service") == 2
    
    # Test delete
    await _set_health_fail_count("test-service", 0)
    assert await _get_health_fail_count("test-service") == 0


@pytest.mark.asyncio
async def test_run_detection_error_rate(mock_httpx_client):
    # Mock prometheus query to return error rate > 0.05
    async def mock_get(url, params, **kwargs):
        query = params.get("query", "")
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        
        if "error_rate" in query or "rate(requests_total" in query and "status_code" in query:
            # High error rate
            mock_resp.json.return_value = {"data": {"result": [{"value": [123, "0.20"]}]}}
        else:
            mock_resp.json.return_value = {"data": {"result": [{"value": [123, "0.0"]}]}}
        return mock_resp

    mock_httpx_client.get.side_effect = mock_get

    results = await run_detection(mock_httpx_client)
    assert any(r.issue_type == "high_error_rate" for r in results)
    
@pytest.mark.asyncio
async def test_get_metrics_snapshot(mock_httpx_client):
    async def mock_get(url, params, **kwargs):
        mock_resp = AsyncMock()
        mock_resp.json.return_value = {"data": {"result": [{"value": [123, "10.5"]}]}}
        return mock_resp
    
    mock_httpx_client.get.side_effect = mock_get
    
    snapshot = await get_metrics_snapshot(mock_httpx_client, "user-service")
    assert snapshot["service"] == "user-service"
    assert snapshot["error_rate"] == 10.5
    assert snapshot["latency_p99_ms"] == 10500.0
    assert snapshot["request_count"] == 10

