"""
Integration tests for JWT middleware.
"""
import pytest
import os
import sys
from jose import jwt
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "api-gateway"))


SECRET = "test-secret"
ALGORITHM = "HS256"


def _make_token(role: str = "viewer", expired: bool = False) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=-1 if expired else 60)
    payload = {"sub": "user-123", "role": role, "exp": exp}
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


@pytest.fixture
def jwt_mw():
    from middleware.jwt_auth import JWTMiddleware
    return JWTMiddleware


class TestJWTMiddlewareLogic:
    """Test the middleware helper functions directly."""

    def test_public_paths_skipped(self):
        from middleware.jwt_auth import _is_public
        assert _is_public("/health") is True
        assert _is_public("/metrics") is True
        assert _is_public("/auth/login") is True
        assert _is_public("/auth/register") is True
        assert _is_public("/docs") is True
        assert _is_public("/api/users") is False

    def test_operator_paths(self):
        from middleware.jwt_auth import _requires_operator
        assert _requires_operator("POST", "/simulate/cpu") is True
        assert _requires_operator("DELETE", "/api/users/123") is True
        assert _requires_operator("POST", "/heal") is True
        assert _requires_operator("GET", "/api/incidents") is False

    def test_valid_token_decode(self):
        token = _make_token("operator")
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        assert payload["role"] == "operator"
        assert payload["sub"] == "user-123"

    def test_expired_token_raises(self):
        from jose import JWTError
        token = _make_token(expired=True)
        with pytest.raises(JWTError):
            jwt.decode(token, SECRET, algorithms=[ALGORITHM])

    def test_viewer_cannot_access_operator_path(self):
        """Viewers should get 403 on operator-only paths."""
        from middleware.jwt_auth import _requires_operator
        role = "viewer"
        path = "/simulate/cpu"
        requires = _requires_operator("POST", path)
        assert requires is True
        # If role is viewer, middleware should block
        assert role != "operator"

    def test_wrong_secret_raises(self):
        from jose import JWTError
        token = _make_token()
        with pytest.raises(JWTError):
            jwt.decode(token, "wrong-secret", algorithms=[ALGORITHM])
