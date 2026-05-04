"""
Incident store — writes and updates incidents in Supabase via asyncpg.
All writes use parameterized queries.
Enhanced with lifecycle status, timeline, root cause, postmortem, metrics_snapshot.
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
import structlog

logger = structlog.get_logger(__name__)

# Injected at startup by main.py
_primary_pool: Optional[asyncpg.Pool] = None
_pool_lock = asyncio.Lock()


def set_pool(pool: asyncpg.Pool) -> None:
    global _primary_pool
    _primary_pool = pool


def get_pool() -> asyncpg.Pool:
    if _primary_pool is None:
        raise RuntimeError("Incident store pool not initialized")
    return _primary_pool


async def create_incident(
    service: str,
    issue_type: str,
    severity: str,
    details: Dict[str, Any],
    action_taken: Optional[str] = None,
    title: Optional[str] = None,
    linked_trace_id: Optional[str] = None,
    metrics_snapshot: Optional[Dict] = None,
) -> Optional[str]:
    """Insert a new incident row. Returns incident UUID string."""
    generated_title = title or f"{issue_type.replace('_', ' ').title()} on {service}"
    severity = severity.lower()
    if severity not in ("critical", "high", "medium", "low"):
        severity = "medium"
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO incidents
                     (service, issue_type, severity, details, action_taken, title,
                      linked_trace_id, metrics_snapshot, condition, healing_action,
                      timeline)
                   VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8::jsonb, $9, $10, $11::jsonb)
                   RETURNING id""",
                service,
                issue_type,
                severity,
                json.dumps(details),
                action_taken,
                generated_title,
                linked_trace_id,
                json.dumps(metrics_snapshot or {}),
                issue_type,
                action_taken,
                json.dumps([{
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user": "system",
                    "message": f"AutoHeal triggered {action_taken or 'detection'} for {issue_type}",
                }]),
            )
        incident_id = str(row["id"])
        logger.info("incident_created", id=incident_id, service=service, issue_type=issue_type)
        return incident_id
    except Exception as exc:
        logger.error("incident_create_failed", error=str(exc))
        return None


async def resolve_incident(incident_id: str, action_taken: Optional[str] = None) -> bool:
    """Mark an incident as resolved."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE incidents
                   SET resolved = TRUE,
                       status = 'resolved',
                       resolved_at = NOW(),
                       action_taken = COALESCE($2, action_taken)
                   WHERE id = $1::uuid""",
                incident_id,
                action_taken,
            )
        logger.info("incident_resolved", id=incident_id)
        return True
    except Exception as exc:
        logger.error("incident_resolve_failed", error=str(exc), id=incident_id)
        return False


async def update_incident_status(incident_id: str, status: str, user: str = "system") -> bool:
    """Update incident lifecycle status."""
    try:
        pool = get_pool()
        now = datetime.now(timezone.utc).isoformat()
        async with pool.acquire() as conn:
            # Update status and timestamp fields
            if status == "acknowledged":
                await conn.execute(
                    """UPDATE incidents SET status = $2, acknowledged_at = NOW() WHERE id = $1::uuid""",
                    incident_id, status,
                )
            elif status == "resolved":
                await conn.execute(
                    """UPDATE incidents SET status = $2, resolved_at = NOW(), resolved = TRUE WHERE id = $1::uuid""",
                    incident_id, status,
                )
            else:
                await conn.execute(
                    """UPDATE incidents SET status = $2 WHERE id = $1::uuid""",
                    incident_id, status,
                )
            # Append to timeline
            await conn.execute(
                """UPDATE incidents
                   SET timeline = timeline || $2::jsonb
                   WHERE id = $1::uuid""",
                incident_id,
                json.dumps([{"timestamp": now, "user": user, "message": f"Status changed to {status}"}]),
            )
        return True
    except Exception as exc:
        logger.error("update_status_failed", error=str(exc))
        return False


async def update_root_cause(incident_id: str, root_cause: str, user: str = "system") -> bool:
    """Update root cause field."""
    try:
        pool = get_pool()
        now = datetime.now(timezone.utc).isoformat()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE incidents SET root_cause = $2 WHERE id = $1::uuid""",
                incident_id, root_cause,
            )
            await conn.execute(
                """UPDATE incidents SET timeline = timeline || $2::jsonb WHERE id = $1::uuid""",
                incident_id,
                json.dumps([{"timestamp": now, "user": user, "message": "Root cause updated"}]),
            )
        return True
    except Exception as exc:
        logger.error("update_root_cause_failed", error=str(exc))
        return False


async def update_postmortem(incident_id: str, postmortem: str, user: str = "system") -> bool:
    """Update postmortem field."""
    try:
        pool = get_pool()
        now = datetime.now(timezone.utc).isoformat()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE incidents SET postmortem = $2 WHERE id = $1::uuid""",
                incident_id, postmortem,
            )
            await conn.execute(
                """UPDATE incidents SET timeline = timeline || $2::jsonb WHERE id = $1::uuid""",
                incident_id,
                json.dumps([{"timestamp": now, "user": user, "message": "Postmortem updated"}]),
            )
        return True
    except Exception as exc:
        logger.error("update_postmortem_failed", error=str(exc))
        return False


async def add_timeline_comment(incident_id: str, user: str, message: str) -> bool:
    """Append a comment to the incident timeline."""
    try:
        pool = get_pool()
        now = datetime.now(timezone.utc).isoformat()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE incidents SET timeline = timeline || $2::jsonb WHERE id = $1::uuid""",
                incident_id,
                json.dumps([{"timestamp": now, "user": user, "message": message}]),
            )
        return True
    except Exception as exc:
        logger.error("add_comment_failed", error=str(exc))
        return False


async def save_metrics_snapshot(
    service: str,
    error_rate: float,
    latency_p99_ms: float,
    request_count: int,
) -> None:
    """Write a metrics snapshot row."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO metrics_snapshots
                     (service, error_rate, latency_p99_ms, request_count)
                   VALUES ($1, $2, $3, $4)""",
                service,
                round(error_rate, 4),
                round(latency_p99_ms, 2),
                request_count,
            )
    except Exception as exc:
        logger.warning("metrics_snapshot_failed", error=str(exc))


async def get_recent_incidents(service: str, limit: int = 50) -> list:
    """Fetch recent incidents for a service."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, service, issue_type, severity, status, details,
                          action_taken, resolved, detected_at, resolved_at,
                          title, assigned_to, root_cause, postmortem,
                          linked_trace_id, timeline, metrics_snapshot
                   FROM incidents
                   WHERE service = $1
                   ORDER BY detected_at DESC
                   LIMIT $2""",
                service,
                limit,
            )
        return [_serialize_incident(r) for r in rows]
    except Exception as exc:
        logger.error("get_incidents_failed", error=str(exc))
        return []


async def get_all_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    service: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[dict]:
    """Fetch incidents with optional filters."""
    try:
        pool = get_pool()
        conditions = []
        params = []
        idx = 1
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if severity:
            conditions.append(f"severity = ${idx}")
            params.append(severity)
            idx += 1
        if service:
            conditions.append(f"service = ${idx}")
            params.append(service)
            idx += 1

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT id, service, issue_type, severity, status, details,
                          action_taken, resolved, detected_at, resolved_at,
                          title, assigned_to, root_cause, postmortem,
                          linked_trace_id, timeline, metrics_snapshot
                   FROM incidents
                   {where}
                   ORDER BY detected_at DESC
                   LIMIT ${idx} OFFSET ${idx+1}""",
                *params,
            )
        return [_serialize_incident(r) for r in rows]
    except Exception as exc:
        logger.error("get_all_incidents_failed", error=str(exc))
        return []


async def get_incident_by_id(incident_id: str) -> Optional[dict]:
    """Fetch a single incident by ID."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, service, issue_type, severity, status, details,
                          action_taken, resolved, detected_at, resolved_at,
                          title, assigned_to, root_cause, postmortem,
                          linked_trace_id, timeline, metrics_snapshot
                   FROM incidents
                   WHERE id = $1::uuid""",
                incident_id,
            )
        if row:
            return _serialize_incident(row)
        return None
    except Exception as exc:
        logger.error("get_incident_by_id_failed", error=str(exc))
        return None


async def get_audit_log(limit: int = 100, offset: int = 0) -> List[dict]:
    """Fetch paginated audit log entries."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, timestamp, service, action, result, triggered_by, reason
                   FROM audit_log
                   ORDER BY timestamp DESC
                   LIMIT $1 OFFSET $2""",
                limit, offset,
            )
        return [
            {
                "id": str(r["id"]),
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                "service": r["service"],
                "action": r["action"],
                "result": r["result"],
                "triggered_by": r["triggered_by"],
                "reason": r["reason"],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.error("get_audit_log_failed", error=str(exc))
        return []


async def get_pending_approvals() -> List[dict]:
    """Fetch pending approval requests."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, service, action, condition, requested_at, requested_by, status
                   FROM pending_approvals
                   WHERE status = 'pending'
                   ORDER BY requested_at DESC""",
            )
        return [
            {
                "id": str(r["id"]),
                "service": r["service"],
                "action": r["action"],
                "condition": r["condition"],
                "requested_at": r["requested_at"].isoformat() if r["requested_at"] else None,
                "requested_by": r["requested_by"],
                "status": r["status"],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.error("get_approvals_failed", error=str(exc))
        return []


async def resolve_approval(approval_id: str, decision: str, resolved_by: str) -> bool:
    """Approve or reject a pending approval."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE pending_approvals
                   SET status = $2, resolved_at = NOW(), resolved_by = $3
                   WHERE id = $1::uuid""",
                approval_id, decision, resolved_by,
            )
        return True
    except Exception as exc:
        logger.error("resolve_approval_failed", error=str(exc))
        return False


def _serialize_incident(r) -> dict:
    """Convert asyncpg record to dict."""
    def _parse_jsonb(val):
        if val is None:
            return {}
        if isinstance(val, (dict, list)):
            return val
        try:
            return json.loads(val)
        except Exception:
            return {}

    return {
        "id": str(r["id"]),
        "service": r["service"],
        "issue_type": r["issue_type"],
        "severity": r["severity"],
        "status": r.get("status", "open"),
        "details": _parse_jsonb(r["details"]),
        "action_taken": r["action_taken"],
        "resolved": r["resolved"],
        "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
        "resolved_at": r["resolved_at"].isoformat() if r["resolved_at"] else None,
        "title": r.get("title"),
        "assigned_to": r.get("assigned_to"),
        "root_cause": r.get("root_cause"),
        "postmortem": r.get("postmortem"),
        "linked_trace_id": r.get("linked_trace_id"),
        "timeline": _parse_jsonb(r.get("timeline")) or [],
        "metrics_snapshot": _parse_jsonb(r.get("metrics_snapshot")) or {},
    }
