from uuid import uuid4

import httpx
import pytest


BASE_URL = "http://localhost:8002"
USER_BASE_URL = "http://localhost:8001"


async def create_test_user(client: httpx.AsyncClient) -> str:
    response = await client.post(
        f"{USER_BASE_URL}/api/users",
        json={
            "name": "Task Owner",
            "email": f"task_owner_{uuid4()}@example.com",
            "password": "secure123",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_create_task():
    async with httpx.AsyncClient() as client:
        user_id = await create_test_user(client)
        response = await client.post(
            f"{BASE_URL}/api/tasks",
            json={
                "title": "Test Task",
                "description": "Test description",
                "status": "pending",
                "priority": "medium",
                "user_id": user_id,
            },
        )
    assert response.status_code == 201
    assert "id" in response.json()


@pytest.mark.asyncio
async def test_invalid_uuid_returns_422():
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/api/tasks/not-a-uuid")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_status_returns_422():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/api/tasks",
            json={
                "title": "Bad Task",
                "status": "invalid_status",
                "user_id": str(uuid4()),
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_task_not_found_returns_404():
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/api/tasks/{uuid4()}")
    assert response.status_code == 404
