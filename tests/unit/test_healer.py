"""
Unit tests for healer.py.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "autoheal-engine"))

from healer import (
    heal,
    apply_rate_limit,
    execute_db_failover,
    set_policy_engine,
    _check_blast_radius,
)
from detector import DetectionResult


class FakePolicyEngine:
    def __init__(self, action="RESTART_SERVICE", dry_run=False):
        self._action = action
        self._dry_run = dry_run
        
    def get_policy(self, condition):
        mock_policy = MagicMock()
        mock_policy.action = self._action
        mock_policy.dry_run = self._dry_run
        mock_policy.cooldown_minutes = 5
        mock_policy.max_attempts = 3
        mock_policy.escalation = "log_incident"
        return mock_policy
        
    async def enforce_cooldown(self, service, action):
        return False
        
    async def exceeded_max_attempts(self, service, action, limit):
        return False
        
    async def set_cooldown(self, service, action, minutes):
        pass
        
    async def increment_attempt(self, service, action, minutes):
        return 1

@pytest.fixture
def fake_policy_engine():
    engine = FakePolicyEngine()
    set_policy_engine(engine)
    yield engine
    set_policy_engine(None)


@pytest.mark.asyncio
@patch("healer.redis_client", new_callable=AsyncMock)
async def test_apply_rate_limit(mock_redis):
    result = await apply_rate_limit("test-service", 50, 120)
    assert result["action"] == "THROTTLE_TRAFFIC"
    assert result["service"] == "test-service"
    mock_redis.setex.assert_called_once()


@pytest.mark.asyncio
@patch("healer.asyncpg.connect")
@patch("healer.redis_client", new_callable=AsyncMock)
@patch("healer.httpx.AsyncClient")
async def test_execute_db_failover(mock_httpx, mock_redis, mock_pg):
    # Setup mocks
    mock_conn = AsyncMock()
    mock_pg.return_value = mock_conn
    mock_httpx_instance = AsyncMock()
    mock_httpx.return_value.__aenter__.return_value = mock_httpx_instance
    
    result = await execute_db_failover("test-service")
    assert result["action"] == "DB_FAILOVER"
    mock_conn.execute.assert_called_with("SELECT 1")


@pytest.mark.asyncio
@patch("healer.redis_client", new_callable=AsyncMock)
async def test_check_blast_radius(mock_redis):
    mock_redis.get.return_value = "0"
    assert not await _check_blast_radius("test-service")

    mock_redis.get.return_value = "3"  # limit is 3
    assert await _check_blast_radius("test-service")


@pytest.mark.asyncio
@patch("healer.log_audit")
@patch("healer._execute_action")
async def test_heal_dry_run(mock_execute, mock_log_audit, fake_policy_engine):
    fake_policy_engine._dry_run = True
    result = DetectionResult(service="test", issue_type="test_issue", severity="high", action="RESTART_SERVICE")
    await heal(result, "incident-123")
    
    # execute action should NOT be called
    mock_execute.assert_not_called()
    mock_log_audit.assert_called_with("test", "RESTART_SERVICE", "dry_run", reason="dry_run mode active")

