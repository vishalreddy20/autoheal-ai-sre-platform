import httpx
import pytest


BASE_URL = "http://localhost:8003"


@pytest.mark.asyncio
async def test_health_endpoint():
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_healing_action_restart():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/heal",
            json={
                "service": "user-service",
                "action": "RESTART_SERVICE",
            },
        )
    assert response.status_code in [200, 202]


@pytest.mark.asyncio
async def test_throttle_applies_rate_limit():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/heal",
            json={
                "service": "task-service",
                "action": "THROTTLE_TRAFFIC",
            },
        )
    assert response.status_code in [200, 202]
    data = response.json()
    assert data.get("result") == "rate_limit_applied"
