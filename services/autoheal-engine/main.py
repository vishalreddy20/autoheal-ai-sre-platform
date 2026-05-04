"""
AutoHeal Engine — main entry point with all new endpoints.
"""
import asyncio
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import ParseResult, urlparse, urlunparse

import asyncpg
import httpx
import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

from config import get_settings
import incident_store
from detector import run_detection, get_metrics_snapshot, MONITORED_SERVICES, DetectionResult
from healer import apply_rate_limit, execute_db_failover, heal, set_broadcast_fn, set_policy_engine, HEALING_DRY_RUN, _decrement_blast_radius
from policies import PolicyEngine
from correlator import AlertCorrelator
from slo import SLOMonitor

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

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

REQUESTS_TOTAL = Counter("requests_total", "Total HTTP requests", ["service", "method", "path", "status_code"])
REQUEST_LATENCY = Histogram("request_latency_seconds", "HTTP request latency", ["service", "path"],
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.5, 5.0])
DB_POOL_SIZE = Gauge("db_pool_size", "DB pool total size", ["service"])
DB_POOL_AVAILABLE = Gauge("db_pool_available", "DB pool available conns", ["service"])
SERVICE_FAILURE = Gauge("service_simulated_failure", "Whether service is in simulated failure mode", ["service"])
HEALING_ACTIONS = Counter("autoheal_healing_actions", "Total healing actions taken", ["service", "action"])
ACTIVE_INCIDENTS = Gauge("autoheal_active_incidents", "Currently active incidents")
ENGINE_POLL_LATENCY = Histogram("autoheal_poll_latency_seconds", "Polling loop latency",
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0])

_redis_client = None
_policy_engine: Optional[PolicyEngine] = None
_correlator: Optional[AlertCorrelator] = None
_slo_monitor: Optional[SLOMonitor] = None

# Dedup TTL matches AlertCorrelator correlation window (seconds)
_DEDUP_TTL = 130


async def _try_claim_incident(fingerprint: str) -> bool:
    """
    Atomically claim an incident fingerprint in Redis (SET NX).
    Returns True if claimed (this worker should process it),
    False if already claimed by a concurrent detection cycle.
    """
    if _redis_client is None:
        return True  # No Redis → always proceed (single-process safe)
    try:
        acquired = await _redis_client.set(
            f"incident:proc:{fingerprint}", "1", ex=_DEDUP_TTL, nx=True
        )
        return bool(acquired)
    except Exception as exc:
        logger.warning("claim_incident_failed", error=str(exc))
        return True  # Fail open


async def _release_incident(fingerprint: str) -> None:
    """Release the incident processing lock so it can be re-triggered if it recurs."""
    if _redis_client is None:
        return
    try:
        await _redis_client.delete(f"incident:proc:{fingerprint}")
    except Exception:
        pass


async def _create_pool(dsn: str, label: str) -> asyncpg.Pool:
    delay = 1.0
    for attempt in range(1, 6):
        try:
            clean_dsn = _normalize_supabase_dsn(dsn)
            pool = await asyncpg.create_pool(
                dsn=clean_dsn, min_size=5, max_size=20, command_timeout=10,
                ssl=_ssl_mode(clean_dsn),
                statement_cache_size=0 if "pooler.supabase.com" in clean_dsn else 100,
                server_settings={"application_name": "autoheal-engine"},
            )
            logger.info("pool_created", label=label, attempt=attempt)
            return pool
        except Exception as exc:
            logger.warning("pool_failed", label=label, attempt=attempt, error=str(exc))
            if attempt == 5:
                logger.error("pool_exhausted_exiting", label=label)
                sys.exit(1)
            await asyncio.sleep(delay)
            delay *= 2


def _normalize_supabase_dsn(dsn: str) -> str:
    clean = dsn.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(clean)
    if parsed.hostname and parsed.hostname.startswith("db.") and parsed.hostname.endswith(".supabase.co"):
        project_ref = parsed.hostname.split(".")[1]
        username = parsed.username or "postgres"
        if "." not in username:
            username = f"{username}.{project_ref}"
        password = f":{parsed.password}" if parsed.password else ""
        host = f"aws-0-{settings.supabase_pooler_region}.pooler.supabase.com"
        netloc = f"{username}{password}@{host}:6543"
        parsed = ParseResult(scheme="postgresql", netloc=netloc,
            path=parsed.path or "/postgres", params="", query=parsed.query, fragment="")
        return urlunparse(parsed)
    return clean


def _ssl_mode(dsn: str):
    host = urlparse(dsn).hostname or ""
    if host.endswith(".supabase.co") or host.endswith(".pooler.supabase.com"):
        return "require"
    return None


async def _compute_slo_compliance(client: httpx.AsyncClient) -> Dict[str, float]:
    from detector import _prom_query
    p95_values = []
    for service in MONITORED_SERVICES:
        q = f'histogram_quantile(0.95, rate(request_latency_seconds_bucket{{service="{service}"}}[5m]))'
        val = await _prom_query(client, q)
        if val is not None:
            p95_values.append(val)
    latency_compliance = round(sum(1 for v in p95_values if v <= 0.2) / len(p95_values) * 100, 2) if p95_values else None
    up_count = 0
    for svc_name, svc_url in MONITORED_SERVICES.items():
        try:
            resp = await client.get(f"{svc_url}/health", timeout=3.0)
            if resp.status_code == 200:
                up_count += 1
        except Exception:
            pass
    availability = round(up_count / len(MONITORED_SERVICES) * 100, 2)
    all_error_rates = []
    for service in MONITORED_SERVICES:
        q = (f'rate(requests_total{{service="{service}",status_code=~"5.."}}[5m])'
             f' / rate(requests_total{{service="{service}"}}[5m])')
        val = await _prom_query(client, q)
        if val is not None:
            all_error_rates.append(val)
    error_compliance = round(sum(1 for v in all_error_rates if v <= 0.01) / len(all_error_rates) * 100, 2) if all_error_rates else None
    return {"latency_slo": latency_compliance, "availability_slo": availability, "error_rate_slo": error_compliance}


async def _broadcast_to_gateway(event: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(f"{settings.api_gateway_url}/internal/broadcast", json=event)
    except Exception as exc:
        logger.warning("gateway_broadcast_failed", error=str(exc))


async def polling_loop() -> None:
    logger.info("polling_loop_started", interval=settings.poll_interval)
    slo_counter = 0
    SLO_CHECK_EVERY = settings.slo_check_interval // settings.poll_interval

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            loop_start = time.perf_counter()
            try:
                detections = await run_detection(client)
                for result in detections:
                    fingerprint = f"{result.service}:{result.issue_type}"

                    # Single dedup via Redis SET NX — one source of truth
                    if not await _try_claim_incident(fingerprint):
                        logger.debug("incident_deduplicated", service=result.service, issue=result.issue_type)
                        continue

                    # Capture metrics snapshot
                    snap = await get_metrics_snapshot(client, result.service)

                    incident_id = await incident_store.create_incident(
                        service=result.service,
                        issue_type=result.issue_type,
                        severity=result.severity,
                        details=result.details,
                        action_taken=result.action,
                        metrics_snapshot=snap,
                    )
                    if incident_id:
                        HEALING_ACTIONS.labels(service=result.service, action=result.action).inc()
                        asyncio.create_task(_run_heal_and_clear(result, incident_id, fingerprint))

                for service in MONITORED_SERVICES:
                    snap = await get_metrics_snapshot(client, service)
                    await incident_store.save_metrics_snapshot(
                        service=snap["service"], error_rate=snap["error_rate"],
                        latency_p99_ms=snap["latency_p99_ms"], request_count=snap["request_count"],
                    )

                    # Auto-resolve incidents when the service recovers
                    if snap["error_rate"] <= 0.05 and snap["latency_p99_ms"] < 500:
                        try:
                            pool = incident_store.get_pool()
                            async with pool.acquire() as conn:
                                unresolved = await conn.fetch(
                                    "SELECT id, issue_type FROM incidents WHERE service = $1 AND resolved = FALSE",
                                    service
                                )
                                for row in unresolved:
                                    issue = row["issue_type"]
                                    if issue == "db_connectivity":
                                        # Only resolve db_connectivity if the ready endpoint says db is ok
                                        try:
                                            url = MONITORED_SERVICES.get(service)
                                            if url:
                                                resp = await client.get(f"{url}/ready", timeout=2.0)
                                                if resp.status_code != 200 or resp.json().get("db") == "error":
                                                    continue
                                        except Exception:
                                            continue
                                    
                                    await incident_store.resolve_incident(str(row["id"]), "auto_resolved_healthy")
                                    await _broadcast_to_gateway({
                                        "type": "incident",
                                        "payload": {
                                            "id": str(row["id"]),
                                            "resolved": True,
                                            "service": service,
                                            "action": "auto_resolved_healthy",
                                            "ts": datetime.now(timezone.utc).isoformat()
                                        }
                                    })
                        except Exception as exc:
                            logger.error("auto_resolve_failed", error=str(exc))


                slo_counter += 1
                if slo_counter >= SLO_CHECK_EVERY:
                    slo_counter = 0
                    slo = await _compute_slo_compliance(client)
                    await _broadcast_to_gateway({"type": "slo", "payload": slo})
                    for slo_name, compliance in slo.items():
                        if compliance is not None and compliance < 95.0:
                            fingerprint = f"system:slo_breach_{slo_name}"
                            if await _try_claim_incident(fingerprint):
                                _ = await incident_store.create_incident(
                                    service="system", issue_type="slo_violation",
                                    severity="medium", details={"slo": slo_name, "compliance": compliance},
                                    action_taken="LOG_INCIDENT",
                                )

                elapsed = time.perf_counter() - loop_start
                ENGINE_POLL_LATENCY.observe(elapsed)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("polling_loop_error", error=str(exc))
            await asyncio.sleep(settings.poll_interval)


async def _run_heal_and_clear(
    result: DetectionResult, incident_id: str, fingerprint: str = ""
) -> None:
    try:
        await heal(result, incident_id)
    except Exception as exc:
        logger.error("heal_error", error=str(exc), service=result.service)
    finally:
        # Decrement blast radius counter now that healing is complete
        await _decrement_blast_radius()


# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(title="AutoHeal AI — Engine", version="2.0.0")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422,
        content={"detail": jsonable_encoder(exc.errors()), "message": "Validation failed"})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(status_code=500, content={"message": "Internal server error"})


app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins_list,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_id_and_metrics_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
    request.state.request_id = request_id
    request.state.trace_id = trace_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    if not request.url.path.startswith("/metrics"):
        REQUESTS_TOTAL.labels(service="autoheal-engine", method=request.method,
            path=request.url.path, status_code=str(response.status_code)).inc()
        REQUEST_LATENCY.labels(service="autoheal-engine", path=request.url.path).observe(elapsed)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Trace-ID"] = trace_id
    return response


# ── Endpoints ──────────────────────────────────────────────────────────────────
@app.get("/health")
async def health(request: Request):
    return JSONResponse(status_code=200,
        content={"status": "ok", "service": "autoheal-engine", "ts": datetime.now(timezone.utc).isoformat()},
        headers={"X-Request-ID": getattr(request.state, "request_id", "unknown")})


@app.get("/ready")
async def ready(request: Request):
    pool = incident_store._primary_pool
    ok = False
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            ok = True
        except Exception:
            pass
    return JSONResponse(status_code=200 if ok else 503,
        content={"ready": ok, "db": "ok" if ok else "error", "ts": datetime.now(timezone.utc).isoformat()})


@app.get("/metrics")
async def metrics():
    pool = incident_store._primary_pool
    if pool:
        DB_POOL_SIZE.labels(service="autoheal-engine").set(pool.get_size())
        DB_POOL_AVAILABLE.labels(service="autoheal-engine").set(pool.get_idle_size())
    active_rows = await incident_store.get_all_incidents(status="investigating", limit=100)
    mitigating_rows = await incident_store.get_all_incidents(status="mitigating", limit=100)
    ACTIVE_INCIDENTS.set(len(active_rows) + len(mitigating_rows))
    return StreamingResponse(content=iter([generate_latest()]), media_type=CONTENT_TYPE_LATEST)


@app.get("/policies", summary="List all loaded remediation policies")
async def get_policies():
    """Return all policies loaded from remediation-policies.yml."""
    if not _policy_engine:
        return JSONResponse(status_code=503, content={"error": "Policy engine not initialized"})
    return JSONResponse(status_code=200, content={"policies": _policy_engine.all_policies()})


@app.get("/config", summary="Current engine configuration and dry-run status")
async def get_config():
    """Return current dry-run status, loaded policies count, and circuit breaker info."""
    policies_count = len(_policy_engine.policies) if _policy_engine else 0
    return JSONResponse(status_code=200, content={
        "dry_run": HEALING_DRY_RUN,
        "policies_loaded": policies_count,
        "blast_radius_limit": 3,
        "dedup_window_seconds": _DEDUP_TTL,
        "poll_interval_seconds": settings.poll_interval,
    })


@app.get("/audit-log", summary="Paginated audit log of all healing decisions")
async def get_audit_log(limit: int = 100, offset: int = 0):
    """Return paginated audit log entries. Records every healing decision."""
    rows = await incident_store.get_audit_log(limit=limit, offset=offset)
    return JSONResponse(status_code=200, content={"audit_log": rows, "count": len(rows)})


@app.get("/approvals", summary="List pending manual approval requests (operator only)")
async def get_approvals(request: Request):
    """List all pending healing action approval requests. Requires operator role."""
    role = request.headers.get("x-user-role", "viewer")
    if role != "operator":
        return JSONResponse(status_code=403, content={"message": "Operator role required"})
    rows = await incident_store.get_pending_approvals()
    return JSONResponse(status_code=200, content={"approvals": rows, "count": len(rows)})


@app.post("/approvals/{approval_id}/approve", summary="Approve a pending healing action")
async def approve_action(approval_id: str, request: Request):
    """Approve a pending healing action. Requires operator role."""
    role = request.headers.get("x-user-role", "viewer")
    user_id = request.headers.get("x-user-id", "system")
    if role != "operator":
        return JSONResponse(status_code=403, content={"message": "Operator role required"})
    ok = await incident_store.resolve_approval(approval_id, "approved", user_id)
    if ok:
        return JSONResponse(status_code=200, content={"message": "Approved", "id": approval_id})
    return JSONResponse(status_code=404, content={"message": "Approval not found"})


@app.post("/approvals/{approval_id}/reject", summary="Reject a pending healing action")
async def reject_action(approval_id: str, request: Request):
    """Reject a pending healing action. Requires operator role."""
    role = request.headers.get("x-user-role", "viewer")
    user_id = request.headers.get("x-user-id", "system")
    if role != "operator":
        return JSONResponse(status_code=403, content={"message": "Operator role required"})
    ok = await incident_store.resolve_approval(approval_id, "rejected", user_id)
    if ok:
        return JSONResponse(status_code=200, content={"message": "Rejected", "id": approval_id})
    return JSONResponse(status_code=404, content={"message": "Approval not found"})


@app.get("/incidents", summary="List incidents with filters")
async def get_incidents_list(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    service: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """List incidents with optional filters for status, severity, and service."""
    rows = await incident_store.get_all_incidents(status=status, severity=severity, service=service, limit=limit, offset=offset)
    return JSONResponse(status_code=200, content={"incidents": rows, "count": len(rows)})


@app.get("/incidents/recent")
async def get_incidents_recent(service: str = "api-gateway"):
    rows = await incident_store.get_recent_incidents(service)
    return JSONResponse(status_code=200, content={"incidents": rows})


@app.get("/api/incidents")
async def get_all_recent_incidents():
    incidents = []
    for service in [*MONITORED_SERVICES.keys(), "system"]:
        incidents.extend(await incident_store.get_recent_incidents(service))
    incidents.sort(key=lambda inc: inc.get("detected_at") or "", reverse=True)
    return JSONResponse(status_code=200, content={"incidents": incidents[:100]})


@app.get("/incidents/{incident_id}", summary="Get full incident detail")
async def get_incident_detail(incident_id: str):
    """Return full incident detail including timeline, metrics snapshot, and postmortem."""
    row = await incident_store.get_incident_by_id(incident_id)
    if not row:
        return JSONResponse(status_code=404, content={"message": "Incident not found"})
    return JSONResponse(status_code=200, content=row)


@app.patch("/incidents/{incident_id}/acknowledge", summary="Acknowledge an incident")
async def acknowledge_incident(incident_id: str, request: Request):
    """Set incident status to acknowledged and assign to current user."""
    user_id = request.headers.get("x-user-id", "system")
    ok = await incident_store.update_incident_status(incident_id, "acknowledged", user_id)
    if not ok:
        return JSONResponse(status_code=404, content={"message": "Incident not found"})
    return JSONResponse(status_code=200, content={"message": "Acknowledged", "id": incident_id})


@app.patch("/incidents/{incident_id}/status", summary="Update incident status")
async def update_incident_status(incident_id: str, request: Request):
    """Update incident status: investigating, mitigating, or resolved."""
    body = await request.json()
    status = body.get("status", "")
    user_id = request.headers.get("x-user-id", "system")
    if status not in ("investigating", "mitigating", "resolved", "acknowledged"):
        return JSONResponse(status_code=422, content={"message": "Invalid status"})
    ok = await incident_store.update_incident_status(incident_id, status, user_id)
    return JSONResponse(status_code=200 if ok else 404, content={"message": "Updated" if ok else "Not found"})


@app.patch("/incidents/{incident_id}/root-cause", summary="Update root cause")
async def update_root_cause(incident_id: str, request: Request):
    """Update the root cause text for an incident."""
    body = await request.json()
    user_id = request.headers.get("x-user-id", "system")
    ok = await incident_store.update_root_cause(incident_id, body.get("root_cause", ""), user_id)
    return JSONResponse(status_code=200 if ok else 404, content={"message": "Updated" if ok else "Not found"})


@app.patch("/incidents/{incident_id}/postmortem", summary="Update postmortem")
async def update_postmortem(incident_id: str, request: Request):
    """Update the postmortem text for an incident."""
    body = await request.json()
    user_id = request.headers.get("x-user-id", "system")
    ok = await incident_store.update_postmortem(incident_id, body.get("postmortem", ""), user_id)
    return JSONResponse(status_code=200 if ok else 404, content={"message": "Updated" if ok else "Not found"})


@app.post("/incidents/{incident_id}/comment", summary="Add a comment to incident timeline")
async def add_comment(incident_id: str, request: Request):
    """Append a timestamped comment to the incident timeline."""
    body = await request.json()
    user_id = request.headers.get("x-user-id", "system")
    message = body.get("message", "")
    if not message:
        return JSONResponse(status_code=422, content={"message": "message is required"})
    ok = await incident_store.add_timeline_comment(incident_id, user_id, message)
    return JSONResponse(status_code=200 if ok else 404, content={"message": "Comment added" if ok else "Not found"})


@app.get("/slo/burn-rates", summary="Get SLO burn rate analysis for all services")
async def get_slo_burn_rates():
    """Return multi-window burn rate analysis for all monitored services."""
    if not _slo_monitor:
        return JSONResponse(status_code=503, content={"error": "SLO monitor not initialized"})
    results = []
    for service in MONITORED_SERVICES:
        analysis = await _slo_monitor.check_burn_rates(service)
        results.append(analysis)
    return JSONResponse(status_code=200, content={"burn_rates": results})


@app.post("/alerts/webhook", summary="Alertmanager webhook receiver")
async def alertmanager_webhook(request: Request):
    """Receive alerts from Alertmanager and create/correlate incidents."""
    body = await request.json()
    alerts = body.get("alerts", [])
    created = 0
    for alert in alerts:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        status = alert.get("status", "firing")
        service = labels.get("job", labels.get("service", "unknown"))
        condition = f"alertmanager_{labels.get('alertname', 'alert')}"

        # Skip resolved alerts and api-gateway (its errors are proxied from downstream)
        if status != "firing":
            continue
        if service == "api-gateway":
            logger.debug("alertmanager_skip_gateway", condition=condition)
            continue

        if _correlator:
            corr_alert = {"service": service, "condition": condition}
            await _correlator.correlate(corr_alert)

        await incident_store.create_incident(
            service=service,
            issue_type=condition,
            severity=labels.get("severity", "medium"),
            details={"status": status, "summary": annotations.get("summary"),
                     "description": annotations.get("description"), "labels": labels},
            action_taken="ALERTMANAGER_WEBHOOK",
        )
        created += 1
    return JSONResponse(status_code=202, content={"accepted": created})


@app.post("/heal", summary="Manually trigger a healing action")
async def manual_heal(request: Request):
    """Manually trigger RESTART_SERVICE, THROTTLE_TRAFFIC, or DB_FAILOVER."""
    body = await request.json()
    service = body.get("service", "")
    action = body.get("action", "")
    if not service or not action:
        return JSONResponse(status_code=422, content={"message": "service and action are required"})

    if action == "THROTTLE_TRAFFIC":
        result = await apply_rate_limit(service)
        return JSONResponse(status_code=202, content=result)
    if action == "DB_FAILOVER":
        result = await execute_db_failover(service)
        return JSONResponse(status_code=202 if result.get("result") == "success" else 409, content=result)
    if action == "RESTART_SERVICE":
        incident_id = await incident_store.create_incident(
            service=service, issue_type="manual_restart", severity="medium",
            details={"source": "manual_heal_endpoint"}, action_taken=action,
        )
        result = DetectionResult(service=service, issue_type="manual_restart",
            severity="medium", action=action, details={"source": "manual_heal_endpoint"})
        if incident_id:
            asyncio.create_task(_run_heal_and_clear(result, incident_id))
        return JSONResponse(status_code=202, content={"action": action, "result": "accepted", "service": service})

    return JSONResponse(status_code=422, content={"message": f"Unsupported action: {action}"})


# ── Lifecycle ──────────────────────────────────────────────────────────────────
_poll_task: Optional[asyncio.Task] = None


@app.on_event("startup")
async def startup():
    global _poll_task, _redis_client, _policy_engine, _correlator, _slo_monitor
    primary_pool = await _create_pool(settings.supabase_db_url, "primary")
    incident_store.set_pool(primary_pool)
    _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True) if aioredis else None
    if _redis_client:
        _policy_engine = PolicyEngine(_redis_client)
        set_policy_engine(_policy_engine)
        _correlator = AlertCorrelator(_redis_client)
        # Inject Redis into detector for Redis-backed health-fail counters
        from detector import set_redis_client as _detector_set_redis
        _detector_set_redis(_redis_client)
    _slo_monitor = SLOMonitor(settings.prometheus_url)
    set_broadcast_fn(_broadcast_to_gateway)
    _poll_task = asyncio.create_task(polling_loop())
    logger.info("autoheal_engine_started", port=settings.service_port)


@app.on_event("shutdown")
async def shutdown():
    global _poll_task
    if _poll_task:
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass
    pool = incident_store._primary_pool
    if pool:
        await pool.close()
    logger.info("autoheal_engine_shutdown_complete")


def _handle_sigterm(*_):
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _handle_sigterm)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port, log_config=None, workers=1)
