"""
API Gateway proxy routes — forwards /api/users/* and /api/tasks/* to upstream services.
Implements circuit breaker pattern (>10 failures in 60s → open circuit for 60s).
"""
import asyncio
import time
from collections import defaultdict
from typing import Dict

import httpx
import structlog
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from config import get_settings

logger = structlog.get_logger(__name__)
router = APIRouter()

settings = get_settings()

# ── Circuit breaker state ─────────────────────────────────────────────────────
class CircuitBreakerState:
    def __init__(self):
        self.failures: int = 0
        self.last_failure_time: float = 0.0
        self.open: bool = False
        self.opened_at: float = 0.0
        self._lock = asyncio.Lock()

    async def record_failure(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            if now - self.last_failure_time > 60.0:
                self.failures = 0
            self.failures += 1
            self.last_failure_time = now
            if self.failures > 10:
                self.open = True
                self.opened_at = now
                logger.warning("circuit_breaker_opened", failures=self.failures)
            return self.open

    async def is_open(self) -> bool:
        async with self._lock:
            if self.open and (time.monotonic() - self.opened_at > 60.0):
                self.open = False
                self.failures = 0
                logger.info("circuit_breaker_closed")
            return self.open

    async def record_success(self):
        async with self._lock:
            self.failures = 0
            self.open = False


_circuit_breakers: Dict[str, CircuitBreakerState] = defaultdict(CircuitBreakerState)

# ── Shared httpx client ───────────────────────────────────────────────────────
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    return _client


async def close_client():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ── Core proxy helper ─────────────────────────────────────────────────────────
async def _proxy(
    request: Request,
    target_url: str,
    service_name: str,
) -> Response:
    request_id = getattr(request.state, "request_id", "unknown")
    cb = _circuit_breakers[service_name]

    if await cb.is_open():
        return JSONResponse(
            status_code=503,
            content={
                "error": "circuit_breaker_open",
                "service": service_name,
                "request_id": request_id,
            },
            headers={"X-Request-ID": request_id},
        )

    # Forward headers (strip host and invalid auth headers)
    headers = dict(request.headers)
    headers.pop("host", None)
    headers["X-Request-ID"] = request_id

    # Strip empty/whitespace-only Authorization tokens (e.g. "Bearer ") that
    # cause httpx to raise "Illegal header value" and trip the circuit breaker.
    auth = headers.get("authorization", "")
    if auth:
        parts = auth.split(None, 1)  # Split on whitespace: ["Bearer", "<token>"]
        if len(parts) < 2 or not parts[1].strip():
            headers.pop("authorization", None)

    body = await request.body()

    try:
        client = get_client()
        upstream_resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
            params=dict(request.query_params),
        )

        if upstream_resp.status_code >= 500:
            is_open = await cb.record_failure()
            logger.error(
                "upstream_5xx",
                service=service_name,
                status=upstream_resp.status_code,
                circuit_open=is_open,
                request_id=request_id,
            )
        else:
            await cb.record_success()

        return Response(
            content=upstream_resp.content,
            status_code=upstream_resp.status_code,
            headers={
                **dict(upstream_resp.headers),
                "X-Request-ID": request_id,
            },
            media_type=upstream_resp.headers.get("content-type"),
        )

    except httpx.TimeoutException:
        await cb.record_failure()
        logger.error("upstream_timeout", service=service_name, request_id=request_id)
        return JSONResponse(
            status_code=504,
            content={
                "error": "upstream_timeout",
                "service": service_name,
                "request_id": request_id,
            },
            headers={"X-Request-ID": request_id},
        )
    except Exception as exc:
        await cb.record_failure()
        logger.error("upstream_error", service=service_name, error=str(exc), request_id=request_id)
        return JSONResponse(
            status_code=502,
            content={
                "error": "upstream_error",
                "service": service_name,
                "detail": str(exc),
                "request_id": request_id,
            },
            headers={"X-Request-ID": request_id},
        )


# ── User-service proxy ────────────────────────────────────────────────────────
@router.api_route("/api/users", methods=["GET", "POST"])
@router.api_route("/api/users/{path:path}", methods=["GET", "POST", "PATCH", "DELETE", "PUT"])
async def proxy_users(request: Request, path: str = "") -> Response:
    suffix = f"/{path}" if path else ""
    target = f"{settings.user_service_url}/users{suffix}"
    return await _proxy(request, target, "user-service")


# ── Task-service proxy ────────────────────────────────────────────────────────
@router.api_route("/api/tasks", methods=["GET", "POST"])
@router.api_route("/api/tasks/{path:path}", methods=["GET", "POST", "PATCH", "DELETE", "PUT"])
async def proxy_tasks(request: Request, path: str = "") -> Response:
    suffix = f"/{path}" if path else ""
    target = f"{settings.task_service_url}/tasks{suffix}"
    return await _proxy(request, target, "task-service")
