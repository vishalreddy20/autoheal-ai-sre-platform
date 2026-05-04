"""
Task CRUD routes — all queries use parameterized statements via asyncpg.
"""
import asyncio
import asyncpg
import structlog
from uuid import UUID
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/tasks")

_delay_ms: int = 0
_delay_lock = asyncio.Lock()

VALID_STATUSES = {"pending", "in_progress", "done", "failed"}


async def set_delay(ms: int) -> None:
    global _delay_ms
    async with _delay_lock:
        _delay_ms = max(0, ms)


async def _maybe_delay():
    async with _delay_lock:
        d = _delay_ms
    if d > 0:
        await asyncio.sleep(d / 1000.0)


async def _check_db_sim(request_id: str):
    if await db.is_db_simulated_down():
        raise asyncpg.PostgresConnectionError("DB simulated down")


# ── POST /tasks ───────────────────────────────────────────────────────────────
@router.post("")
async def create_task(request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    await _maybe_delay()
    try:
        await _check_db_sim(request_id)
        body = await request.json()
        user_id = body.get("user_id", "").strip()
        title = body.get("title", "").strip()
        status = body.get("status", "pending").strip()
        if not user_id or not title:
            return JSONResponse(
                status_code=422,
                content={"error": "user_id and title are required", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
        if status not in VALID_STATUSES:
            return JSONResponse(
                status_code=422,
                content={
                    "error": f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )
        pool = db.get_write_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO tasks (user_id, title, status)
                   VALUES ($1::uuid, $2, $3)
                   RETURNING id, user_id, title, status, created_at, updated_at""",
                user_id,
                title,
                status,
            )
        result = {
            "id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "title": row["title"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }
        return JSONResponse(status_code=201, content=result, headers={"X-Request-ID": request_id})
    except asyncpg.ForeignKeyViolationError:
        return JSONResponse(
            status_code=404,
            content={"error": "user_not_found", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except asyncpg.PostgresConnectionError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": "db_unavailable", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except Exception as exc:
        logger.error("create_task_error", error=str(exc), request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )


# ── GET /tasks ────────────────────────────────────────────────────────────────
@router.get("")
async def list_tasks(
    request: Request, page: int = 1, limit: int = 20, status: str = ""
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    await _maybe_delay()
    try:
        await _check_db_sim(request_id)
        offset = (page - 1) * limit
        pool = db.get_read_pool()
        async with pool.acquire() as conn:
            if status and status in VALID_STATUSES:
                rows = await conn.fetch(
                    """SELECT id, user_id, title, status, created_at, updated_at
                       FROM tasks WHERE status = $1
                       ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
                    status, limit, offset,
                )
                total = await conn.fetchval("SELECT COUNT(*) FROM tasks WHERE status = $1", status)
            else:
                rows = await conn.fetch(
                    """SELECT id, user_id, title, status, created_at, updated_at
                       FROM tasks ORDER BY created_at DESC LIMIT $1 OFFSET $2""",
                    limit, offset,
                )
                total = await conn.fetchval("SELECT COUNT(*) FROM tasks")
        items = [
            {
                "id": str(r["id"]),
                "user_id": str(r["user_id"]),
                "title": r["title"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat(),
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ]
        return JSONResponse(
            status_code=200,
            content={"items": items, "total": total, "page": page, "limit": limit},
            headers={"X-Request-ID": request_id},
        )
    except asyncpg.PostgresConnectionError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": "db_unavailable", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except Exception as exc:
        logger.error("list_tasks_error", error=str(exc), request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )


# ── GET /tasks/{id} ───────────────────────────────────────────────────────────
@router.get("/{task_id}")
async def get_task(task_id: UUID, request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    await _maybe_delay()
    try:
        await _check_db_sim(request_id)
        pool = db.get_read_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, user_id, title, status, created_at, updated_at
                   FROM tasks WHERE id = $1::uuid""",
                str(task_id),
            )
        if not row:
            return JSONResponse(
                status_code=404,
                content={"error": "task_not_found", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
        result = {
            "id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "title": row["title"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }
        return JSONResponse(status_code=200, content=result, headers={"X-Request-ID": request_id})
    except asyncpg.PostgresConnectionError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": "db_unavailable", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except Exception as exc:
        logger.error("get_task_error", error=str(exc), request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )


# ── PATCH /tasks/{id}/status ──────────────────────────────────────────────────
@router.patch("/{task_id}/status")
async def update_task_status(task_id: UUID, request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    await _maybe_delay()
    try:
        await _check_db_sim(request_id)
        body = await request.json()
        new_status = body.get("status", "").strip()
        if new_status not in VALID_STATUSES:
            return JSONResponse(
                status_code=422,
                content={
                    "error": f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}",
                    "request_id": request_id,
                },
                headers={"X-Request-ID": request_id},
            )
        pool = db.get_write_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE tasks SET status = $1, updated_at = NOW()
                   WHERE id = $2::uuid
                   RETURNING id, user_id, title, status, created_at, updated_at""",
                new_status,
                str(task_id),
            )
        if not row:
            return JSONResponse(
                status_code=404,
                content={"error": "task_not_found", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
        result = {
            "id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "title": row["title"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }
        return JSONResponse(status_code=200, content=result, headers={"X-Request-ID": request_id})
    except asyncpg.PostgresConnectionError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": "db_unavailable", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except Exception as exc:
        logger.error("update_task_status_error", error=str(exc), request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
