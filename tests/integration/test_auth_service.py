"""
Integration tests for auth-service endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
import asyncpg
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "auth-service"))


def _make_mock_pool():
    """Create a mock asyncpg pool."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool, mock_conn


@pytest.fixture
def auth_client():
    # Set required env vars before importing
    os.environ["SUPABASE_DB_URL"] = "postgresql://test:test@localhost/test"
    os.environ["AUTH_JWT_SECRET"] = "test-secret-key-32-chars-minimum!!"
    import main as auth_main
    mock_pool, mock_conn = _make_mock_pool()
    auth_main._pool = mock_pool
    with patch.object(auth_main, "_pool", mock_pool):
        with TestClient(auth_main.app) as client:
            yield client, mock_conn


class TestHealthEndpoint:
    def test_health_returns_ok(self, auth_client):
        client, _ = auth_client
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestLoginEndpoint:
    def test_login_valid_credentials(self, auth_client):
        client, mock_conn = auth_client
        from passlib.context import CryptContext
        pwd = CryptContext(schemes=["bcrypt"], deprecated="auto").hash("admin123")
        mock_conn.fetchrow = AsyncMock(return_value={
            "id": "11111111-1111-1111-1111-111111111111",
            "username": "admin",
            "password_hash": pwd,
            "role": "operator",
        })
        resp = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["role"] == "operator"

    def test_login_invalid_password(self, auth_client):
        client, mock_conn = auth_client
        from passlib.context import CryptContext
        pwd = CryptContext(schemes=["bcrypt"], deprecated="auto").hash("admin123")
        mock_conn.fetchrow = AsyncMock(return_value={
            "id": "11111111-1111-1111-1111-111111111111",
            "username": "admin",
            "password_hash": pwd,
            "role": "operator",
        })
        resp = client.post("/auth/login", json={"username": "admin", "password": "wrongpassword"})
        assert resp.status_code == 401

    def test_login_user_not_found(self, auth_client):
        client, mock_conn = auth_client
        mock_conn.fetchrow = AsyncMock(return_value=None)
        resp = client.post("/auth/login", json={"username": "ghost", "password": "any"})
        assert resp.status_code == 401


class TestRegisterEndpoint:
    def test_register_viewer(self, auth_client):
        client, mock_conn = auth_client
        mock_conn.execute = AsyncMock()
        resp = client.post("/auth/register", json={"username": "newuser", "password": "pass123", "role": "viewer"})
        assert resp.status_code == 201
        assert resp.json()["role"] == "viewer"

    def test_register_invalid_role(self, auth_client):
        client, _ = auth_client
        resp = client.post("/auth/register", json={"username": "x", "password": "y", "role": "superadmin"})
        assert resp.status_code == 422

    def test_register_duplicate_username(self, auth_client):
        client, mock_conn = auth_client
        mock_conn.execute = AsyncMock(side_effect=asyncpg.UniqueViolationError("duplicate"))
        resp = client.post("/auth/register", json={"username": "admin", "password": "admin123", "role": "viewer"})
        assert resp.status_code == 409


class TestVerifyEndpoint:
    def test_verify_valid_token(self, auth_client):
        client, mock_conn = auth_client
        # First get a real token
        from passlib.context import CryptContext
        pwd = CryptContext(schemes=["bcrypt"], deprecated="auto").hash("admin123")
        mock_conn.fetchrow = AsyncMock(return_value={
            "id": "11111111-1111-1111-1111-111111111111",
            "username": "admin",
            "password_hash": pwd,
            "role": "operator",
        })
        login_resp = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
        token = login_resp.json()["token"]
        resp = client.post("/auth/verify", json={"token": token})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_verify_invalid_token(self, auth_client):
        client, _ = auth_client
        resp = client.post("/auth/verify", json={"token": "garbage.token.here"})
        assert resp.status_code == 401
        assert resp.json()["valid"] is False
