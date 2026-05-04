"""
JWT middleware for API Gateway.
Validates Bearer tokens on all protected routes.
Injects x-user-id and x-user-role headers into proxied requests.
"""
from typing import Optional

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)

# Routes that do NOT require authentication
PUBLIC_PATHS = {
    "/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json",
    "/stream/events", "/internal/broadcast",
}
PUBLIC_PREFIXES = ("/auth/", "/metrics")

# Routes that require 'operator' role
OPERATOR_PATHS_PREFIXES = (
    "/simulate/",
    "/api/simulate/",
)
OPERATOR_EXACT = {"/heal", "/api/heal", "/alerts/webhook"}


def _is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _requires_operator(method: str, path: str) -> bool:
    if method == "DELETE":
        return True
    for prefix in OPERATOR_PATHS_PREFIXES:
        if path.startswith(prefix):
            return True
    if path in OPERATOR_EXACT:
        return True
    return False


class JWTMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, jwt_secret: str, jwt_algorithm: str = "HS256"):
        super().__init__(app)
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # Skip auth for public paths
        if _is_public(path):
            return await call_next(request)

        # Extract token from Authorization header
        auth_header = request.headers.get("Authorization", "")
        token: Optional[str] = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not token:
            return JSONResponse(
                status_code=401,
                content={"message": "Missing authentication token", "path": path},
            )

        # Validate JWT
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
            user_id = payload.get("sub", "")
            role = payload.get("role", "viewer")
        except JWTError as exc:
            logger.warning("jwt_invalid", path=path, error=str(exc))
            return JSONResponse(
                status_code=401,
                content={"message": "Invalid or expired token"},
            )

        # Role check for operator-only routes
        if _requires_operator(method, path) and role != "operator":
            logger.warning("rbac_denied", path=path, method=method, role=role)
            return JSONResponse(
                status_code=403,
                content={"message": "Operator role required", "your_role": role},
            )

        # Inject user context into request headers for downstream services
        # We mutate the headers via scope
        scope = request.scope
        headers = dict(request.headers)
        headers["x-user-id"] = user_id
        headers["x-user-role"] = role
        # Rebuild headers in scope
        scope["headers"] = [
            (k.lower().encode(), v.encode())
            for k, v in headers.items()
        ]

        return await call_next(request)
