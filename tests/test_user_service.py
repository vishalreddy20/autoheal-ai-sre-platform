from uuid import uuid4

import httpx
import pytest


BASE_URL = "http://localhost:8001"


@pytest.mark.asyncio
async def test_create_user():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/api/users",
            json={
                "name": "Test User",
                "email": f"test_{uuid4()}@example.com",
                "password": "secure123",
            },
        )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert "password" not in data


@pytest.mark.asyncio
async def test_invalid_uuid_returns_422():
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/api/users/not-a-uuid")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_missing_user_returns_404():
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/api/users/{uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_email_returns_409():
    email = f"dup_{uuid4()}@example.com"
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{BASE_URL}/api/users",
            json={"name": "User1", "email": email, "password": "pass123"},
        )
        response = await client.post(
            f"{BASE_URL}/api/users",
            json={"name": "User2", "email": email, "password": "pass456"},
        )
    assert response.status_code == 409
