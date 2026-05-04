"""
User Service — main FastAPI application.
Handles /users CRUD routes, health/ready probes, Prometheus metrics, SIGTERM.
"""
import asyncio
import signal
import time
from datetime import datetime, timezone

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

from config import get_settings
from middleware_helpers import RequestIDMiddleware, setup_tracing
import db
from routes.users import router as users_router, set_delay

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
DB_POOL_SIZE = Gauge("db_pool_size", "DB pool total size", ["service"])
DB_POOL_AVAILABLE = Gauge("db_pool_available", "DB pool available conns", ["service"])
SERVICE_FAILURE = Gauge(
    "service_simulated_failure",
    "Whether service is in simulated failure mode",
    ["service"],
)
SERVICE_FAILURE.labels(service="user-service").set(0)

_SERVICE_SIMULATED_DOWN = False

app = FastAPI(title="AutoHeal AI — User Service", version="1.0.0")
setup_tracing(app, settings.service_name, settings.jaeger_endpoint)


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestIDMiddleware)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    global _SERVICE_SIMULATED_DOWN
    if _SERVICE_SIMULATED_DOWN and not request.url.path.startswith("/internal/"):
        return JSONResponse(status_code=503, content={"error": "Service simulated down"})

    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    path = request.url.path
    if not path.startswith("/metrics"):
        REQUESTS_TOTAL.labels(
            service="user-service",
            method=request.method,
            path=path,
            status_code=str(response.status_code),
        ).inc()
        REQUEST_LATENCY.labels(service="user-service", path=path).observe(elapsed)
    return response


app.include_router(users_router)
app.include_router(users_router, prefix="/api")


@app.get("/health")
async def health(request: Request):
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "service": "user-service", "ts": datetime.now(timezone.utc).isoformat()},
        headers={"X-Request-ID": request_id},
    )


@app.get("/ready")
async def ready(request: Request):
    request_id = getattr(request.state, "request_id", "unknown")
    ok = await db.check_db_health()
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"ready": ok, "db": "ok" if ok else "error", "ts": datetime.now(timezone.utc).isoformat()},
        headers={"X-Request-ID": request_id},
    )


@app.get("/metrics")
async def metrics():
    # Update pool gauges
    if db.PRIMARY_POOL:
        DB_POOL_SIZE.labels(service="user-service").set(db.PRIMARY_POOL.get_size())
        DB_POOL_AVAILABLE.labels(service="user-service").set(db.PRIMARY_POOL.get_idle_size())
    SERVICE_FAILURE.labels(service="user-service").set(1 if await db.is_db_simulated_down() else 0)
    return StreamingResponse(
        content=iter([generate_latest()]),
        media_type=CONTENT_TYPE_LATEST,
    )


# ── Internal endpoints (not proxied by gateway) ────────────────────────────────
@app.post("/internal/db-simulate")
async def internal_db_simulate(request: Request):
    body = await request.json()
    await db.set_db_simulated_down(body.get("down", False))
    logger.info("db_simulation_state_changed", down=body.get("down"))
    return JSONResponse(status_code=200, content={"ok": True})


@app.post("/internal/service-simulate")
async def internal_service_simulate(request: Request):
    global _SERVICE_SIMULATED_DOWN
    body = await request.json()
    _SERVICE_SIMULATED_DOWN = body.get("down", False)
    logger.info("service_simulation_state_changed", down=_SERVICE_SIMULATED_DOWN)
    return JSONResponse(status_code=200, content={"ok": True})


@app.post("/internal/db-mode")
async def internal_db_mode(request: Request):
    body = await request.json()
    use_replica = body.get("mode") == "replica"
    await db.set_use_replica(use_replica)
    logger.info("db_mode_changed", replica=use_replica)
    return JSONResponse(status_code=200, content={"ok": True, "replica": use_replica})


@app.post("/internal/delay")
async def internal_delay(request: Request):
    body = await request.json()
    ms = int(body.get("delay_ms", 0))
    await set_delay(ms)
    logger.info("artificial_delay_set", delay_ms=ms)
    return JSONResponse(status_code=200, content={"ok": True, "delay_ms": ms})


@app.on_event("startup")
async def startup():
    await db.connect_db()
    logger.info("user_service_started", port=settings.service_port)


@app.on_event("shutdown")
async def shutdown():
    await db.disconnect_db()
    logger.info("user_service_shutdown_complete")


def _handle_sigterm(*_):
    logger.info("sigterm_received")
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _handle_sigterm)
