"""
Healer — executes recovery actions in response to DetectionResults.
Integrates PolicyEngine, circuit breaker, blast radius limiter, audit log, dry-run mode.
Actions: RESTART_SERVICE, DB_FAILOVER, THROTTLE_TRAFFIC, LOG_INCIDENT.
"""
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Callable, Awaitable, Dict, Optional, Any

import asyncpg
import docker
import httpx
import redis.asyncio as aioredis
import structlog

from config import get_settings
from detector import DetectionResult, MONITORED_SERVICES
import incident_store
from policies import PolicyEngine

logger = structlog.get_logger(__name__)
settings = get_settings()
redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)

# Global dry-run flag from env
HEALING_DRY_RUN = os.environ.get("HEALING_DRY_RUN", "false").lower() == "true"

# Blast radius limit: max services healing simultaneously in 5 minutes
BLAST_RADIUS_LIMIT = 3
BLAST_RADIUS_TTL = 300  # 5 minutes

# Circuit breaker: open after N failures in window_seconds, stays open for reset_seconds
CB_FAILURE_THRESHOLD = 3
CB_WINDOW_SECONDS = 600   # 10 minutes
CB_RESET_SECONDS = 900    # 15 minutes

# Broadcast callback (set by main.py after SSE infrastructure is ready)
_broadcast_fn: Callable[[dict], Awaitable[None]] | None = None

# Policy engine (set by main.py after Redis is ready)
_policy_engine: Optional[PolicyEngine] = None


def set_broadcast_fn(fn: Callable[[dict], Awaitable[None]]) -> None:
    global _broadcast_fn
    _broadcast_fn = fn


def set_policy_engine(engine: PolicyEngine) -> None:
    global _policy_engine
    _policy_engine = engine


def get_policy_engine() -> PolicyEngine:
    return _policy_engine


async def _emit(event: dict) -> None:
    if _broadcast_fn:
        try:
            await _broadcast_fn(event)
        except Exception as exc:
            logger.warning("broadcast_failed", error=str(exc))


# ── Audit Log ──────────────────────────────────────────────────────────────────
async def log_audit(
    service: str,
    action: str,
    result: str,
    triggered_by: str = "system",
    reason: Optional[str] = None,
) -> None:
    """Insert an audit log entry into Postgres."""
    try:
        pool = incident_store.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_log (service, action, result, triggered_by, reason)
                   VALUES ($1, $2, $3, $4, $5)""",
                service, action, result, triggered_by, reason,
            )
        logger.info("audit_logged", service=service, action=action, result=result)
    except Exception as exc:
        logger.error("audit_log_failed", error=str(exc))


# ── Escalation ─────────────────────────────────────────────────────────────────
async def escalate(service: str, condition: str, escalation_type: str, triggered_by: str = "system") -> None:
    """Handle escalation actions."""
    if escalation_type == "require_manual_approval":
        try:
            pool = incident_store.get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO pending_approvals (service, action, condition, requested_by)
                       VALUES ($1, $2, $3, $4)""",
                    service,
                    _policy_engine.get_policy(condition).action if _policy_engine else "UNKNOWN",
                    condition,
                    triggered_by,
                )
            logger.info("manual_approval_created", service=service, condition=condition)
        except Exception as exc:
            logger.error("create_approval_failed", error=str(exc))
    else:
        logger.warning("escalated", service=service, condition=condition, escalation=escalation_type)


# ── Circuit Breaker ─────────────────────────────────────────────────────────────
async def _get_cb_state(service: str, action: str) -> str:
    """Returns 'closed', 'open', or 'half-open'."""
    try:
        key = f"healing:cb:{service}:{action}"
        state = await redis_client.get(key)
        if state == "open":
            # Check if reset window has passed → half-open
            opened_at_key = f"healing:cb_opened:{service}:{action}"
            opened_at = await redis_client.get(opened_at_key)
            if opened_at:
                elapsed = time.time() - float(opened_at)
                if elapsed > CB_RESET_SECONDS:
                    await redis_client.set(key, "half-open")
                    return "half-open"
            return "open"
        return state or "closed"
    except Exception as exc:
        logger.warning("cb_state_check_failed", error=str(exc))
        return "closed"


async def _record_cb_failure(service: str, action: str) -> None:
    """Record a circuit breaker failure. Open circuit after threshold."""
    try:
        fail_key = f"healing:cb_failures:{service}:{action}"
        count = await redis_client.incr(fail_key)
        if count == 1:
            await redis_client.expire(fail_key, CB_WINDOW_SECONDS)
        if count >= CB_FAILURE_THRESHOLD:
            cb_key = f"healing:cb:{service}:{action}"
            opened_key = f"healing:cb_opened:{service}:{action}"
            await redis_client.set(cb_key, "open", ex=CB_RESET_SECONDS + 60)
            await redis_client.set(opened_key, str(time.time()), ex=CB_RESET_SECONDS + 60)
            logger.warning("circuit_breaker_opened", service=service, action=action, failures=count)
    except Exception as exc:
        logger.warning("cb_record_failure_failed", error=str(exc))


async def _record_cb_success(service: str, action: str) -> None:
    """Reset circuit breaker on success."""
    try:
        await redis_client.delete(
            f"healing:cb:{service}:{action}",
            f"healing:cb_failures:{service}:{action}",
            f"healing:cb_opened:{service}:{action}",
        )
    except Exception as exc:
        logger.warning("cb_record_success_failed", error=str(exc))


# ── Blast Radius Limiter ───────────────────────────────────────────────────────
async def _check_blast_radius(service: str) -> bool:
    """
    Returns True if blast radius limit reached (action should be blocked).
    Tracks active healing count in Redis with TTL=300s.
    """
    try:
        key = "healing:active_count"
        count_str = await redis_client.get(key)
        current_count = int(count_str) if count_str else 0
        if current_count >= BLAST_RADIUS_LIMIT:
            logger.warning(
                "blast_radius_limit_reached",
                count=current_count,
                limit=BLAST_RADIUS_LIMIT,
                skipping=service,
            )
            return True
        return False
    except Exception as exc:
        logger.warning("blast_radius_check_failed", error=str(exc))
        return False


async def _increment_blast_radius() -> None:
    try:
        key = "healing:active_count"
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, BLAST_RADIUS_TTL)
    except Exception as exc:
        logger.warning("blast_radius_increment_failed", error=str(exc))


async def _decrement_blast_radius() -> None:
    """Decrement blast radius counter when healing action completes."""
    try:
        key = "healing:active_count"
        count_str = await redis_client.get(key)
        if count_str and int(count_str) > 0:
            await redis_client.decr(key)
    except Exception as exc:
        logger.warning("blast_radius_decrement_failed", error=str(exc))


# ── Docker helpers ─────────────────────────────────────────────────────────────
def _docker_client() -> docker.DockerClient:
    try:
        return docker.from_env()
    except Exception:
        if settings.docker_socket.startswith("npipe://"):
            return docker.DockerClient(base_url=settings.docker_socket)
        if settings.docker_socket.startswith("/"):
            return docker.DockerClient(base_url=f"unix://{settings.docker_socket}")
        return docker.from_env()


def _resolve_container(dc: docker.DockerClient, service: str):
    try:
        return dc.containers.get(service)
    except docker.errors.NotFound:
        matches = dc.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.service={service}"},
        )
        if matches:
            return matches[0]
        raise


async def _wait_for_healthy(service: str, url: str, timeout: int = 30) -> bool:
    async with httpx.AsyncClient(timeout=3.0) as client:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client.get(f"{url}/health")
                if resp.status_code == 200:
                    logger.info("service_healthy_after_restart", service=service)
                    return True
            except Exception:
                pass
            await asyncio.sleep(5)
    return False


# ── Rate limit / DB Failover ───────────────────────────────────────────────────
async def apply_rate_limit(service: str, limit: int = 50, duration_seconds: int = 120) -> dict:
    await redis_client.setex(f"rate_limit:{service}", duration_seconds, str(limit))
    logger.info("rate_limit_applied", service=service, limit=f"{limit}req/s", duration=f"{duration_seconds}s")
    return {
        "action": "THROTTLE_TRAFFIC",
        "result": "rate_limit_applied",
        "service": service,
        "limit": f"{limit}req/s",
        "duration": f"{duration_seconds}s",
    }


async def execute_db_failover(service: str) -> dict:
    replica_url = settings.replica_url
    if not replica_url or replica_url == settings.supabase_db_url:
        return {"action": "DB_FAILOVER", "result": "failed", "reason": "No replica configured"}

    clean_replica_url = replica_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = None
    try:
        conn = await asyncpg.connect(clean_replica_url, ssl="require" if "supabase" in clean_replica_url else None)
        await conn.execute("SELECT 1")
    except Exception as exc:
        return {"action": "DB_FAILOVER", "result": "failed", "reason": str(exc)}
    finally:
        if conn:
            await conn.close()

    message = {
        "new_primary": replica_url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "triggered_by": "autoheal-engine",
        "service": service,
    }
    await redis_client.publish("db_failover", json.dumps(message))

    async with httpx.AsyncClient(timeout=5.0) as client:
        for svc_name, svc_url in MONITORED_SERVICES.items():
            if svc_name == "api-gateway":
                continue
            try:
                await client.post(f"{svc_url}/internal/db-mode", json={"mode": "replica"})
                logger.info("db_mode_switched", target_service=svc_name, mode="replica")
            except Exception as exc:
                logger.warning("db_failover_notify_failed", target=svc_name, error=str(exc))

    return {
        "action": "DB_FAILOVER",
        "result": "success",
        "replica_healthy": True,
        "services_notified": True,
    }


# ── Action executors ───────────────────────────────────────────────────────────
async def _execute_action(service: str, action: str, result: DetectionResult, incident_id: str) -> bool:
    """Execute the healing action. Returns True on success, False on failure."""
    try:
        if action == "RESTART_SERVICE":
            await action_restart_service(result, incident_id)
            return True
        elif action == "DB_FAILOVER":
            outcome = await execute_db_failover(service)
            if outcome["result"] == "success":
                await incident_store.resolve_incident(incident_id, "db_failover_to_replica")
                return True
            return False
        elif action == "THROTTLE_TRAFFIC":
            await apply_rate_limit(service)
            await incident_store.resolve_incident(incident_id, "traffic_rate_limit_applied")
            return True
        else:
            # LOG_INCIDENT
            await action_log_incident(result, incident_id)
            return True
    except Exception as exc:
        logger.error("execute_action_failed", service=service, action=action, error=str(exc))
        return False


async def action_restart_service(result: DetectionResult, incident_id: str) -> None:
    service = result.service
    # Never restart the API gateway — its errors are proxied from downstream,
    # and restarting it kills all traffic (Locust keeps hitting it), cascading into
    # more 503s, circuit breaker trips, and new incidents.
    if service == "api-gateway":
        logger.info("restart_skipped_gateway", service=service, reason="gateway errors are proxied")
        await incident_store.resolve_incident(incident_id, "skipped_gateway_restart")
        return

    logger.info("action_restart_service", service=service)
    success = False
    try:
        try:
            dc = _docker_client()
            container = _resolve_container(dc, service)
            container.restart(timeout=10)
        except Exception as e:
            logger.warning("docker_restart_skipped", service=service, reason=str(e))
            
        # Also clear any simulated failure in the API gateway so healing works locally
        async with httpx.AsyncClient(timeout=2.0) as client:
            try:
                gw_url = settings.api_gateway_url or "http://api-gateway:8000"
                await client.post(f"{gw_url}/simulate/service-restore", json={"service": service})
            except Exception:
                pass

        service_url = MONITORED_SERVICES.get(service, "")
        success = await _wait_for_healthy(service, service_url, timeout=30)
        if success:
            await incident_store.resolve_incident(incident_id, "container_restarted")
            await _emit({
                "type": "incident",
                "payload": {
                    "id": incident_id,
                    "resolved": True,
                    "service": service,
                    "action": "restarted",
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            })
        else:
            esc_id = await incident_store.create_incident(
                service=service,
                issue_type="restart_failed",
                severity="critical",
                details={"original_issue": result.issue_type},
                action_taken="escalated_after_restart_failure",
            )
            await _emit({
                "type": "incident",
                "payload": {
                    "id": esc_id,
                    "service": service,
                    "issue_type": "restart_failed",
                    "severity": "critical",
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            })
    except docker.errors.NotFound:
        logger.error("container_not_found", service=service)
    except Exception as exc:
        logger.error("restart_service_error", service=service, error=str(exc))
        raise

    logger.info("restart_complete", service=service, success=success)


async def action_log_incident(result: DetectionResult, incident_id: str) -> None:
    """Just emit SSE — incident was already written to DB by caller."""
    await _emit({
        "type": "incident",
        "payload": {
            "id": incident_id,
            "service": result.service,
            "issue_type": result.issue_type,
            "severity": result.severity,
            "details": result.details,
            "resolved": False,
            "ts": result.ts,
        },
    })


# ── Main heal orchestrator with all safety controls ────────────────────────────
async def heal(result: DetectionResult, incident_id: str) -> None:
    """
    Main healing dispatcher with:
    - Policy engine lookup
    - Cooldown enforcement
    - Max attempt enforcement
    - Blast radius limiting
    - Circuit breaker
    - Dry-run mode
    - Audit logging
    - Manual approval escalation
    """
    service = result.service
    condition = result.issue_type

    if not _policy_engine:
        logger.warning("policy_engine_not_initialized", service=service)
        return

    # 1. Policy lookup
    policy = _policy_engine.get_policy(condition)
    if not policy:
        logger.info("no_policy_for_condition", service=service, condition=condition)
        await log_audit(service, "UNKNOWN", "skipped", reason=f"No policy for condition: {condition}")
        return

    action = policy.action

    # 2. Global dry-run override (env) or policy-level dry_run
    if HEALING_DRY_RUN or policy.dry_run:
        logger.info("dry_run_mode", service=service, action=action)
        await log_audit(service, action, "dry_run", reason="dry_run mode active")
        await _emit({"type": "dry_run", "payload": {"service": service, "action": action, "condition": condition}})
        return

    # 3. Cooldown check
    if await _policy_engine.enforce_cooldown(service, action):
        logger.info("cooldown_active", service=service, action=action)
        await log_audit(service, action, "cooldown", reason="Cooldown window active")
        return

    # 4. Max attempts check
    if await _policy_engine.exceeded_max_attempts(service, action, policy.max_attempts):
        logger.warning("max_attempts_reached", service=service, action=action)
        await escalate(service, condition, policy.escalation)
        await log_audit(
            service, action, "skipped",
            reason=f"Max attempts ({policy.max_attempts}) reached, escalating: {policy.escalation}",
        )
        return

    # 5. Blast radius check
    if await _check_blast_radius(service):
        await log_audit(
            service, action, "blast_radius",
            reason=f"Blast radius limit reached: {BLAST_RADIUS_LIMIT} services already healing",
        )
        return

    # 6. Circuit breaker check
    cb_state = await _get_cb_state(service, action)
    if cb_state == "open":
        logger.info("circuit_breaker_open", service=service, action=action)
        await log_audit(service, action, "circuit_open", reason="Circuit breaker is OPEN")
        return

    # 7. Manual approval escalation
    if policy.escalation == "require_manual_approval":
        logger.info("manual_approval_required", service=service, action=action)
        await escalate(service, condition, "require_manual_approval")
        await log_audit(service, action, "skipped", reason="Pending manual approval")
        return

    # 8. Execute healing action
    await _increment_blast_radius()
    success = False
    try:
        success = await _execute_action(service, action, result, incident_id)
    except Exception as exc:
        logger.error("heal_execution_failed", service=service, action=action, error=str(exc))
        await _record_cb_failure(service, action)
        await log_audit(service, action, "failed", reason=str(exc))
        return

    if success:
        await _record_cb_success(service, action)
        await _policy_engine.set_cooldown(service, action, policy.cooldown_minutes)
        await _policy_engine.increment_attempt(service, action, policy.cooldown_minutes)
        await log_audit(service, action, "executed", triggered_by="system")
        logger.info("heal_executed", service=service, action=action)
    else:
        await _record_cb_failure(service, action)
        await log_audit(service, action, "failed", reason="Action returned failure")
