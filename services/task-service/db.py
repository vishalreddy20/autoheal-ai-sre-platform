"""
asyncpg connection pool management for task-service.
Mirrors user-service/db.py with task-service application_name.
"""
import asyncio
import asyncpg
import structlog
from typing import Optional
from urllib.parse import ParseResult, urlparse, urlunparse

from config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

PRIMARY_POOL: Optional[asyncpg.Pool] = None
REPLICA_POOL: Optional[asyncpg.Pool] = None

_db_simulated_down: bool = False
_use_replica: bool = False
_db_lock = asyncio.Lock()


async def set_db_simulated_down(value: bool) -> None:
    global _db_simulated_down
    async with _db_lock:
        _db_simulated_down = value


async def set_use_replica(value: bool) -> None:
    global _use_replica
    async with _db_lock:
        _use_replica = value


async def is_db_simulated_down() -> bool:
    async with _db_lock:
        return _db_simulated_down


async def _create_pool(dsn: str, service_name: str, label: str) -> asyncpg.Pool:
    max_attempts = 5
    delay = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            clean_dsn = _normalize_supabase_dsn(dsn)
            pool = await asyncpg.create_pool(
                dsn=clean_dsn,
                min_size=5,
                max_size=20,
                command_timeout=10,
                ssl=_ssl_mode(clean_dsn),
                statement_cache_size=0 if "pooler.supabase.com" in clean_dsn else 100,
                server_settings={"application_name": service_name},
            )
            logger.info("pool_created", label=label, attempt=attempt)
            return pool
        except Exception as exc:
            logger.warning("pool_creation_failed", label=label, attempt=attempt, error=str(exc), retry_in=delay)
            if attempt == max_attempts:
                logger.error("pool_creation_exhausted", label=label)
                raise
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
        parsed = ParseResult(
            scheme="postgresql",
            netloc=netloc,
            path=parsed.path or "/postgres",
            params="",
            query=parsed.query,
            fragment="",
        )
        return urlunparse(parsed)
    return clean


def _ssl_mode(dsn: str):
    host = urlparse(dsn).hostname or ""
    if host.endswith(".supabase.co") or host.endswith(".pooler.supabase.com"):
        return "require"
    return None


async def connect_db() -> None:
    global PRIMARY_POOL, REPLICA_POOL
    PRIMARY_POOL = await _create_pool(settings.supabase_db_url, settings.service_name, "primary")
    REPLICA_POOL = await _create_pool(settings.replica_url, settings.service_name, "replica")


async def disconnect_db() -> None:
    global PRIMARY_POOL, REPLICA_POOL
    if PRIMARY_POOL:
        await PRIMARY_POOL.close()
        PRIMARY_POOL = None
    if REPLICA_POOL:
        await REPLICA_POOL.close()
        REPLICA_POOL = None
    logger.info("db_pools_closed")


def get_write_pool() -> asyncpg.Pool:
    if PRIMARY_POOL is None:
        raise RuntimeError("Primary DB pool not initialized")
    return PRIMARY_POOL


def get_read_pool() -> asyncpg.Pool:
    if _use_replica and REPLICA_POOL is not None:
        return REPLICA_POOL
    if PRIMARY_POOL is None:
        raise RuntimeError("DB pool not initialized")
    return PRIMARY_POOL


async def check_db_health() -> bool:
    if await is_db_simulated_down():
        return False
    try:
        pool = get_read_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False
