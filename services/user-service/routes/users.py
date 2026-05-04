"""
User CRUD routes — all queries use parameterized statements via asyncpg.
"""
import asyncio
import asyncpg
from uuid import UUID

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/users")

# Artificial delay (ms) — set by simulate endpoint
_delay_ms: int = 0
_delay_lock = asyncio.Lock()


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


# ── POST /users ───────────────────────────────────────────────────────────────
@router.post("")
async def create_user(request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    await _maybe_delay()
    try:
        await _check_db_sim(request_id)
        body = await request.json()
        name = body.get("name", "").strip()
        email = body.get("email", "").strip()
        if not name or not email:
            return JSONResponse(
                status_code=422,
                content={"error": "name and email are required", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
        pool = db.get_write_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO users (name, email)
                   VALUES ($1, $2)
                   RETURNING id, name, email, created_at""",
                name,
                email,
            )
        result = dict(row)
        result["id"] = str(result["id"])
        result["created_at"] = result["created_at"].isoformat()
        return JSONResponse(
            status_code=201,
            content=result,
            headers={"X-Request-ID": request_id},
        )
    except asyncpg.UniqueViolationError:
        return JSONResponse(
            status_code=409,
            content={"error": "email_already_exists", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except asyncpg.PostgresConnectionError as exc:
        logger.error("db_connection_error", error=str(exc), request_id=request_id)
        return JSONResponse(
            status_code=503,
            content={"error": "db_unavailable", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except Exception as exc:
        logger.error("create_user_error", error=str(exc), request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )


# ── GET /users ────────────────────────────────────────────────────────────────
@router.get("")
async def list_users(request: Request, page: int = 1, limit: int = 20) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    await _maybe_delay()
    try:
        await _check_db_sim(request_id)
        offset = (page - 1) * limit
        pool = db.get_read_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, name, email, created_at
                   FROM users
                   WHERE deleted_at IS NULL
                   ORDER BY created_at DESC
                   LIMIT $1 OFFSET $2""",
                limit,
                offset,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE deleted_at IS NULL"
            )
        items = [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "email": r["email"],
                "created_at": r["created_at"].isoformat(),
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
        logger.error("list_users_error", error=str(exc), request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )


# ── GET /users/{id} ───────────────────────────────────────────────────────────
@router.get("/{user_id}")
async def get_user(user_id: UUID, request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    await _maybe_delay()
    try:
        await _check_db_sim(request_id)
        pool = db.get_read_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, name, email, created_at
                   FROM users WHERE id = $1 AND deleted_at IS NULL""",
                str(user_id),
            )
        if not row:
            return JSONResponse(
                status_code=404,
                content={"error": "user_not_found", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
        result = dict(row)
        result["id"] = str(result["id"])
        result["created_at"] = result["created_at"].isoformat()
        return JSONResponse(
            status_code=200,
            content=result,
            headers={"X-Request-ID": request_id},
        )
    except asyncpg.PostgresConnectionError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": "db_unavailable", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except Exception as exc:
        logger.error("get_user_error", error=str(exc), request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )


# ── DELETE /users/{id} (soft delete) ─────────────────────────────────────────
@router.delete("/{user_id}")
async def delete_user(user_id: UUID, request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    await _maybe_delay()
    try:
        await _check_db_sim(request_id)
        pool = db.get_write_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE users SET deleted_at = NOW()
                   WHERE id = $1 AND deleted_at IS NULL""",
                str(user_id),
            )
        # result is "UPDATE N"
        if result == "UPDATE 0":
            return JSONResponse(
                status_code=404,
                content={"error": "user_not_found", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
        return JSONResponse(
            status_code=204,
            content=None,
            headers={"X-Request-ID": request_id},
        )
    except asyncpg.PostgresConnectionError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": "db_unavailable", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except Exception as exc:
        logger.error("delete_user_error", error=str(exc), request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
