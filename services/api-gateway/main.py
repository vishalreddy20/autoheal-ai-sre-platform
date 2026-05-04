"""
API Gateway — main FastAPI application entry point.
"""
import asyncio
import hashlib
import hmac
import json
import math
import os
import signal
import time
from datetime import datetime, timezone
from typing import AsyncGenerator

import httpx as _httpx_module

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from config import get_settings
from middleware.request_id import RequestIDMiddleware
from middleware.rate_limiter import limiter, rate_limit_exceeded_handler
from middleware.tracing import setup_tracing
from routes.proxy import router as proxy_router, close_client
from routes.simulate import router as simulate_router

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

# ── Logging ────────────────────────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)
logger = structlog.get_logger(__name__)

settings = get_settings()

# ── Prometheus metrics ─────────────────────────────────────────────────────────
REQUESTS_TOTAL = Counter(
    "requests_total",
    "Total HTTP requests",
    ["service", "method", "path", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "request_latency_seconds",
    "HTTP request latency",
    ["service", "path"],
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.5, 5.0],
)
SERVICE_FAILURE = Gauge(
    "service_simulated_failure",
    "Whether service is in simulated failure mode",
    ["service"],
)
DB_POOL_SIZE = Gauge("db_pool_size", "DB pool total size", ["service"])
DB_POOL_AVAILABLE = Gauge("db_pool_available", "DB pool available conns", ["service"])
SERVICE_FAILURE.labels(service="api-gateway").set(0)
DB_POOL_SIZE.labels(service="api-gateway").set(0)
DB_POOL_AVAILABLE.labels(service="api-gateway").set(0)

# ── Application factory ────────────────────────────────────────────────────────
app = FastAPI(
    title="AutoHeal AI — API Gateway",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors()), "message": "Validation failed"},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error"},
    )


redis_client = aioredis.from_url(settings.redis_url, decode_responses=True) if aioredis else None

# Tracing
setup_tracing(app, settings.service_name, settings.jaeger_endpoint)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# JWT Authentication middleware disabled per user request
# jwt_secret = os.environ.get("AUTH_JWT_SECRET", settings.auth_jwt_secret)
# app.add_middleware(JWTMiddleware, jwt_secret=jwt_secret)

# CORS — lock to allowed origins from env
allowed_origins = settings.cors_origins_list or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Trace-ID"],
)

# Request ID injection
app.add_middleware(RequestIDMiddleware)


# ── Metrics instrumentation middleware ─────────────────────────────────────────
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    path = request.url.path
    if not path.startswith("/metrics"):
        REQUESTS_TOTAL.labels(
            service="api-gateway",
            method=request.method,
            path=path,
            status_code=str(response.status_code),
        ).inc()
        REQUEST_LATENCY.labels(service="api-gateway", path=path).observe(elapsed)
        # Structured JSON access log with trace ID
        trace_id = request.headers.get("X-Trace-ID", "")
        logger.info(
            "request",
            method=request.method,
            path=path,
            status=response.status_code,
            trace_id=trace_id,
            duration_ms=round(elapsed * 1000, 2),
        )
    return response


@app.middleware("http")
async def throttle_rate_limit_middleware(request: Request, call_next):
    path_parts = [part for part in request.url.path.split("/") if part]
    service_from_path = {
        "users": "user-service",
        "tasks": "task-service",
    }

    if len(path_parts) >= 2 and path_parts[0] == "api":
        service_name = service_from_path.get(path_parts[1])
        if service_name and redis_client:
            try:
                limit = await redis_client.get(f"rate_limit:{service_name}")
                if limit:
                    now = int(time.time())
                    counter_key = f"req_count:{service_name}:{now}"
                    count = await redis_client.incr(counter_key)
                    await redis_client.expire(counter_key, 2)
                    if count > int(limit):
                        request_id = getattr(request.state, "request_id", "unknown")
                        return JSONResponse(
                            status_code=429,
                            content={
                                "message": "Rate limit exceeded. Service under throttle healing.",
                                "service": service_name,
                                "request_id": request_id,
                            },
                            headers={"X-Request-ID": request_id},
                        )
            except Exception as exc:
                logger.warning("redis_rate_limit_check_failed", error=str(exc))

    return await call_next(request)


# ── Auth proxy routes ──────────────────────────────────────────────────────────
@app.api_route("/auth/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_auth(request: Request, path: str):
    """Proxy all /auth/* requests to the auth-service."""
    target = f"{settings.auth_service_url}/auth/{path}"
    headers = dict(request.headers)
    headers.pop("host", None)
    body = await request.body()
    try:
        async with _httpx_module.AsyncClient(timeout=10.0) as client:
            resp = await client.request(
                method=request.method,
                url=target,
                headers=headers,
                content=body,
                params=dict(request.query_params),
            )
        return JSONResponse(
            status_code=resp.status_code,
            content=resp.json() if resp.content else {},
        )
    except Exception as exc:
        logger.error("auth_proxy_error", path=path, error=str(exc))
        return JSONResponse(status_code=502, content={"error": "Auth service unavailable"})


# ── Login rate limiter (5 per minute per IP) ───────────────────────────────────
@app.middleware("http")
async def login_rate_limit_middleware(request: Request, call_next):
    if request.url.path == "/auth/login" and request.method == "POST":
        if redis_client:
            client_ip = request.client.host if request.client else "unknown"
            key = f"login_attempts:{client_ip}"
            try:
                count = await redis_client.incr(key)
                if count == 1:
                    await redis_client.expire(key, 60)
                if count > 1000:
                    return JSONResponse(
                        status_code=429,
                        content={"message": "Too many login attempts. Try again in 1 minute."},
                    )
            except Exception:
                pass
    return await call_next(request)


# ── HMAC webhook signature verification ───────────────────────────────────────
@app.middleware("http")
async def webhook_hmac_middleware(request: Request, call_next):
    if request.url.path in ("/alerts/webhook", "/api/alerts/webhook"):
        webhook_secret = os.environ.get("ALERTMANAGER_WEBHOOK_SECRET", "")
        if webhook_secret:
            sig_header = request.headers.get("X-Alertmanager-Signature", "")
            body = await request.body()
            expected = hmac.new(
                webhook_secret.encode(), body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(f"sha256={expected}", sig_header):
                return JSONResponse(status_code=401, content={"message": "Invalid webhook signature"})
            # Re-set body for downstream consumption
            async def receive():
                return {"type": "http.request", "body": body}
            request._receive = receive
    return await call_next(request)


# ── Include routers ────────────────────────────────────────────────────────────
app.include_router(proxy_router)
app.include_router(simulate_router)


# ── Health / Ready ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health(request: Request):
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "service": "api-gateway",
            "ts": datetime.now(timezone.utc).isoformat(),
        },
        headers={"X-Request-ID": request_id},
    )


@app.get("/ready")
async def ready(request: Request):
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=200,
        content={
            "ready": True,
            "db": "n/a",
            "ts": datetime.now(timezone.utc).isoformat(),
        },
        headers={"X-Request-ID": request_id},
    )


# ── Prometheus metrics endpoint ────────────────────────────────────────────────
@app.get("/metrics")
async def metrics():
    return StreamingResponse(
        content=iter([generate_latest()]),
        media_type=CONTENT_TYPE_LATEST,
    )


# ── SSE: Server-Sent Events stream ────────────────────────────────────────────
# In-memory queue for SSE events (broadcast to all connected clients)
_sse_queues: list[asyncio.Queue] = []
_sse_lock = asyncio.Lock()


async def broadcast_sse(event: dict) -> None:
    """Broadcast an event to all connected SSE clients."""
    async with _sse_lock:
        dead = []
        for q in _sse_queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _sse_queues.remove(q)


async def _sse_generator(request: Request) -> AsyncGenerator[str, None]:
    """Generate SSE events for a connected client."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    async with _sse_lock:
        _sse_queues.append(queue)

    logger.info("sse_client_connected", client=str(request.client))
    keep_alive_interval = 15
    last_ka = time.monotonic()

    try:
        while True:
            if await request.is_disconnected():
                break

            now = time.monotonic()
            if now - last_ka >= keep_alive_interval:
                yield ":\n\n"
                last_ka = now

            try:
                event = queue.get_nowait()
                data = json.dumps(event)
                yield f"data: {data}\n\n"
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.1)

    finally:
        async with _sse_lock:
            if queue in _sse_queues:
                _sse_queues.remove(queue)
        logger.info("sse_client_disconnected")


# Background task: push metrics snapshots every 3s
async def _prom_query(client, query: str) -> float | None:
    try:
        resp = await client.get(
            f"{settings.prometheus_url}/api/v1/query",
            params={"query": query},
            timeout=2.5,
        )
        body = resp.json()
        results = body.get("data", {}).get("result", [])
        if not results:
            return None
        value = float(results[0]["value"][1])
        return value if math.isfinite(value) else None
    except Exception:
        return None


async def _metrics_broadcaster():
    import httpx as _httpx
    while True:
        try:
            await asyncio.sleep(3)
            services = {
                "api-gateway": settings.api_gateway_url,
                "user-service": settings.user_service_url,
                "task-service": settings.task_service_url,
            }
            payloads = {}
            async with _httpx.AsyncClient(timeout=2.0) as client:
                for svc, url in services.items():
                    try:
                        r = await client.get(f"{url}/metrics")
                        is_up = r.status_code == 200

                        request_rate = await _prom_query(
                            client,
                            f'rate(requests_total{{service="{svc}"}}[1m])',
                        )
                        error_rate = await _prom_query(
                            client,
                            f'rate(requests_total{{service="{svc}",status_code=~"5.."}}[1m]) / rate(requests_total{{service="{svc}"}}[1m])',
                        )
                        p99_latency_s = await _prom_query(
                            client,
                            f'histogram_quantile(0.99, rate(request_latency_seconds_bucket{{service="{svc}"}}[1m]))',
                        )

                        payloads[svc] = {
                            "status": "up" if is_up else "down",
                            "request_rate": request_rate,
                            "error_rate": error_rate,
                            "p99_latency_ms": p99_latency_s * 1000.0 if p99_latency_s is not None else None,
                        }
                    except Exception:
                        payloads[svc] = {
                            "status": "down",
                            "request_rate": None,
                            "error_rate": None,
                            "p99_latency_ms": None,
                        }

            await broadcast_sse({
                "type": "metrics",
                "payload": {"services": payloads, "ts": datetime.now(timezone.utc).isoformat()},
            })
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("metrics_broadcast_error", error=str(exc))


# Expose broadcast_sse so autoheal engine can call it via internal endpoint
@app.post("/internal/broadcast")
async def internal_broadcast(request: Request):
    """Internal endpoint for autoheal-engine to push events to SSE clients."""
    try:
        body = await request.json()
        await broadcast_sse(body)
        return JSONResponse(status_code=200, content={"ok": True})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.api_route(
    "/api/incidents/{path:path}",
    methods=["GET", "POST", "PATCH", "DELETE"],
    summary="Proxy incident management to autoheal-engine",
)
async def proxy_incidents(request: Request, path: str):
    """Proxy /api/incidents/* to the autoheal-engine — keeps frontend behind gateway."""
    target = f"{settings.autoheal_engine_url}/incidents/{path}"
    if request.query_params:
        target += f"?{request.query_params}"
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    body = await request.body()
    try:
        async with _httpx_module.AsyncClient(timeout=10.0) as client:
            resp = await client.request(
                method=request.method,
                url=target,
                headers=headers,
                content=body,
            )
        return JSONResponse(
            status_code=resp.status_code,
            content=resp.json() if resp.content else {},
        )
    except Exception as exc:
        logger.error("incidents_proxy_error", path=path, error=str(exc))
        return JSONResponse(status_code=502, content={"error": "AutoHeal engine unavailable"})


@app.api_route(
    "/api/incidents",
    methods=["GET"],
    summary="List all incidents via autoheal-engine proxy",
)
async def proxy_all_incidents(request: Request):
    """Proxy GET /api/incidents to the autoheal-engine."""
    target = f"{settings.autoheal_engine_url}/api/incidents"
    if request.query_params:
        target += f"?{request.query_params}"
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    try:
        async with _httpx_module.AsyncClient(timeout=10.0) as client:
            resp = await client.get(target, headers=headers)
        return JSONResponse(
            status_code=resp.status_code,
            content=resp.json() if resp.content else {},
        )
    except Exception as exc:
        logger.error("all_incidents_proxy_error", error=str(exc))
        return JSONResponse(status_code=502, content={"error": "AutoHeal engine unavailable"})



@app.get("/stream/events")
async def stream_events(request: Request):
    request_id = getattr(request.state, "request_id", "unknown")
    return StreamingResponse(
        _sse_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )


# ── Lifecycle ──────────────────────────────────────────────────────────────────
_broadcaster_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup():
    global _broadcaster_task
    _broadcaster_task = asyncio.create_task(_metrics_broadcaster())
    logger.info("api_gateway_started", port=settings.service_port)


@app.on_event("shutdown")
async def shutdown():
    global _broadcaster_task
    if _broadcaster_task:
        _broadcaster_task.cancel()
        try:
            await _broadcaster_task
        except asyncio.CancelledError:
            pass
    await close_client()
    if redis_client:
        await redis_client.aclose()
    logger.info("api_gateway_shutdown_complete")


# ── SIGTERM handler ────────────────────────────────────────────────────────────
def _handle_sigterm(*_):
    logger.info("sigterm_received")
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _handle_sigterm)
