"""
Auth Service — JWT authentication with role-based access control.
Endpoints: POST /auth/login, POST /auth/register, GET /auth/me
"""
import asyncio
import signal
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse, urlunparse, ParseResult

import asyncpg
import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel

from config import get_settings

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

# ── Crypto helpers ─────────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)

# ── Prometheus metrics ─────────────────────────────────────────────────────────
REQUESTS_TOTAL = Counter(
    "requests_total", "Total HTTP requests",
    ["service", "method", "path", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "request_latency_seconds", "HTTP request latency",
    ["service", "path"],
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.5, 5.0],
)

# ── DB pool ────────────────────────────────────────────────────────────────────
_pool: Optional[asyncpg.Pool] = None


def _normalize_dsn(dsn: str) -> str:
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
            scheme="postgresql", netloc=netloc,
            path=parsed.path or "/postgres",
            params="", query=parsed.query, fragment="",
        )
        return urlunparse(parsed)
    return clean


async def _create_pool() -> asyncpg.Pool:
    clean_dsn = _normalize_dsn(settings.supabase_db_url)
    ssl_mode = "require" if "supabase" in clean_dsn else None
    for attempt in range(1, 6):
        try:
            pool = await asyncpg.create_pool(
                dsn=clean_dsn,
                min_size=2,
                max_size=10,
                command_timeout=10,
                ssl=ssl_mode,
                statement_cache_size=0 if "pooler.supabase.com" in clean_dsn else 100,
            )
            logger.info("auth_pool_created", attempt=attempt)
            return pool
        except Exception as exc:
            logger.warning("auth_pool_failed", attempt=attempt, error=str(exc))
            if attempt == 5:
                raise
            await asyncio.sleep(2 ** attempt)


# ── JWT helpers ────────────────────────────────────────────────────────────────
def create_access_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.auth_jwt_expire_minutes)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm=settings.auth_jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.auth_jwt_secret, algorithms=[settings.auth_jwt_algorithm])


# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AutoHeal AI — Auth Service",
    version="1.0.0",
    description="JWT authentication and RBAC for AutoHeal AI platform",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    request.state.request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request.state.trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    path = request.url.path
    if not path.startswith("/metrics"):
        REQUESTS_TOTAL.labels(
            service="auth-service", method=request.method,
            path=path, status_code=str(response.status_code),
        ).inc()
        REQUEST_LATENCY.labels(service="auth-service", path=path).observe(elapsed)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Trace-ID"] = request.state.trace_id
    return response


# ── Request/Response models ────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class TokenResponse(BaseModel):
    token: str
    user_id: str
    username: str
    role: str


class UserResponse(BaseModel):
    user_id: str
    username: str
    role: str


# ── Auth dependency ────────────────────────────────────────────────────────────
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication token")
    try:
        payload = decode_token(credentials.credentials)
        return {"user_id": payload["sub"], "role": payload["role"]}
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


# ── Endpoints ──────────────────────────────────────────────────────────────────
@app.post("/auth/login", response_model=TokenResponse, summary="Login and obtain JWT token")
async def login(body: LoginRequest):
    """
    Authenticate with username and password.
    Returns a JWT token containing user_id, role, and expiration.
    """
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, password_hash, role FROM auth_users WHERE username = $1",
            body.username,
        )
    if not row or not pwd_context.verify(body.password, row["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = create_access_token(str(row["id"]), row["role"])
    logger.info("user_logged_in", username=body.username, role=row["role"])
    return {"token": token, "user_id": str(row["id"]), "username": row["username"], "role": row["role"]}


@app.post("/auth/register", status_code=201, summary="Register a new user")
async def register(body: RegisterRequest):
    """
    Register a new user with role 'viewer' or 'operator'.
    Default role is 'viewer'.
    """
    if body.role not in ("viewer", "operator"):
        raise HTTPException(status_code=422, detail="role must be 'viewer' or 'operator'")

    hashed = pwd_context.hash(body.password)
    user_id = str(uuid.uuid4())
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO auth_users (id, username, password_hash, role) VALUES ($1, $2, $3, $4)",
                user_id, body.username, hashed, body.role,
            )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Username already exists")
    except Exception as exc:
        logger.error("register_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to create user")

    logger.info("user_registered", username=body.username, role=body.role)
    return {"user_id": user_id, "username": body.username, "role": body.role}


@app.get("/auth/me", response_model=UserResponse, summary="Get current authenticated user")
async def me(current_user: dict = Depends(get_current_user)):
    """Return the currently authenticated user's profile from JWT claims."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT username FROM auth_users WHERE id = $1::uuid",
            current_user["user_id"],
        )
    username = row["username"] if row else current_user["user_id"]
    return {"user_id": current_user["user_id"], "username": username, "role": current_user["role"]}


@app.post("/auth/verify", summary="Verify a JWT token (internal use)")
async def verify_token(request: Request):
    """Internal endpoint used by API Gateway to verify tokens."""
    body = await request.json()
    token = body.get("token", "")
    try:
        payload = decode_token(token)
        return JSONResponse(status_code=200, content={
            "valid": True,
            "user_id": payload["sub"],
            "role": payload["role"],
        })
    except JWTError as exc:
        return JSONResponse(status_code=401, content={"valid": False, "error": str(exc)})


@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok", "service": "auth-service", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/ready", summary="Readiness check")
async def ready():
    try:
        async with _pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"ready": True, "db": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"ready": False, "db": "error"})


@app.get("/metrics", summary="Prometheus metrics")
async def metrics():
    return StreamingResponse(content=iter([generate_latest()]), media_type=CONTENT_TYPE_LATEST)


# ── Lifecycle ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    global _pool
    _pool = await _create_pool()
    await _seed_default_users()
    logger.info("auth_service_started", port=settings.service_port)


async def _seed_default_users() -> None:
    """
    Ensure default users exist on every startup.
    Hashes are computed with bcrypt at runtime — no hardcoded hashes in SQL.
    """
    defaults = [
        ("admin",  "admin123",  "operator"),
        ("viewer", "viewer123", "viewer"),
    ]
    async with _pool.acquire() as conn:
        for username, password, role in defaults:
            existing = await conn.fetchrow(
                "SELECT id FROM auth_users WHERE username = $1", username
            )
            if existing:
                continue
            hashed = pwd_context.hash(password)
            await conn.execute(
                "INSERT INTO auth_users (username, password_hash, role) VALUES ($1, $2, $3)"
                " ON CONFLICT (username) DO NOTHING",
                username, hashed, role,
            )
            logger.info("default_user_seeded", username=username, role=role)


@app.on_event("shutdown")
async def shutdown():
    if _pool:
        await _pool.close()
    logger.info("auth_service_shutdown_complete")


def _handle_sigterm(*_):
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _handle_sigterm)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port, log_config=None, workers=1)
