"""
Failure simulation endpoints exposed on the API Gateway.
These allow the frontend Controls page and AutoHeal Engine to trigger
controlled chaos for demonstration purposes.
"""
import asyncio
from typing import Dict, Any

import docker
import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from config import get_settings

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/simulate")

settings = get_settings()

# ── Shared state flags (protected by asyncio.Lock) ───────────────────────────
_state_lock = asyncio.Lock()
_db_simulated_down: bool = False
_artificial_delays: Dict[str, int] = {}  # service_name → delay_ms
_service_simulated_down: Dict[str, bool] = {}


def get_db_simulated_down() -> bool:
    return _db_simulated_down


# ── Docker client helper ──────────────────────────────────────────────────────
def _docker_client() -> docker.DockerClient:
    """Create a Docker client.

    Prefer environment-driven configuration (docker.from_env()) so that
    `DOCKER_HOST` is respected (Windows TCP); fall back to the configured
    socket for Linux-style setups.
    """
    try:
        # docker.from_env() respects DOCKER_HOST / DOCKER_TLS_* env vars
        return docker.from_env()
    except Exception:
        # Fallback to explicit socket configuration (legacy)
        if settings.docker_socket.startswith("npipe://"):
            return docker.DockerClient(base_url=settings.docker_socket)
        if settings.docker_socket.startswith("/"):
            return docker.DockerClient(base_url=f"unix://{settings.docker_socket}")
        # Final fallback
        return docker.from_env()


def _resolve_container(dc: docker.DockerClient, service: str):
    """Resolve a container by exact name first, then by compose service label."""
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


async def _notify_service(service_url: str, path: str, payload: Dict[str, Any]) -> None:
    """Notify a downstream service about a simulation state change."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{service_url}{path}", json=payload)
    except Exception as exc:
        logger.warning("notify_service_failed", url=service_url, path=path, error=str(exc))



# ── DB Simulation ─────────────────────────────────────────────────────────────
@router.post("/db-down")
async def simulate_db_down(request: Request) -> JSONResponse:
    global _db_simulated_down
    request_id = getattr(request.state, "request_id", "unknown")
    async with _state_lock:
        _db_simulated_down = True
    # Notify downstream services
    await asyncio.gather(
        _notify_service(settings.user_service_url, "/internal/db-simulate", {"down": True}),
        _notify_service(settings.task_service_url, "/internal/db-simulate", {"down": True}),
        return_exceptions=True,
    )
    logger.warning("db_simulation_activated", request_id=request_id)
    return JSONResponse(
        status_code=200,
        content={"status": "db_simulated_down", "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


@router.post("/db-restore")
async def simulate_db_restore(request: Request) -> JSONResponse:
    global _db_simulated_down
    request_id = getattr(request.state, "request_id", "unknown")
    async with _state_lock:
        _db_simulated_down = False
    await asyncio.gather(
        _notify_service(settings.user_service_url, "/internal/db-simulate", {"down": False}),
        _notify_service(settings.task_service_url, "/internal/db-simulate", {"down": False}),
        return_exceptions=True,
    )
    logger.info("db_simulation_restored", request_id=request_id)
    return JSONResponse(
        status_code=200,
        content={"status": "db_restored", "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


# ── Service Up/Down Simulation ────────────────────────────────────────────────
@router.post("/service-down")
async def simulate_service_down(request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    try:
        body = await request.json()
        service = body.get("service", "")
        if not service:
            return JSONResponse(
                status_code=400,
                content={"error": "service field required", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
        try:
            dc = _docker_client()
            container = _resolve_container(dc, service)
            container.stop(timeout=5)
            logger.warning("service_stopped", service=service, request_id=request_id)
            return JSONResponse(
                status_code=200,
                content={"status": "stopped", "service": service, "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
        except docker.errors.NotFound:
            raise
        except Exception as exc:
            # If Docker access is denied (common on Windows when TCP isn't enabled),
            # fall back to a soft in-app simulation so demos can run without host Docker access.
            err_str = str(exc)
            logger.error("service_stop_failed", error=err_str, request_id=request_id)
            if "Permission denied" in err_str or isinstance(exc, PermissionError) or "Connection aborted" in err_str:
                _service_simulated_down[service] = True
                
                target_url = None
                if service == "user-service": target_url = settings.user_service_url
                elif service == "task-service": target_url = settings.task_service_url
                
                if target_url:
                    try:
                        await _notify_service(
                            target_url,
                            "/internal/service-simulate",
                            {"down": True}
                        )
                    except Exception:
                        pass

                return JSONResponse(
                    status_code=200,
                    content={"status": "simulated_stopped", "service": service, "request_id": request_id, "note": "docker_unavailable_fallback"},
                    headers={"X-Request-ID": request_id},
                )
            # otherwise re-raise to be handled by outer exception handler
            raise
    except docker.errors.NotFound:
        return JSONResponse(
            status_code=404,
            content={"error": "container_not_found", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except Exception as exc:
        logger.error("service_stop_failed", error=str(exc), request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )


@router.post("/service-restore")
async def simulate_service_restore(request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    try:
        body = await request.json()
        service = body.get("service", "")
        if not service:
            return JSONResponse(
                status_code=400,
                content={"error": "service field required", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
        try:
            dc = _docker_client()
            container = _resolve_container(dc, service)
            container.start()
            logger.info("service_started", service=service, request_id=request_id)
            return JSONResponse(
                status_code=200,
                content={"status": "started", "service": service, "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
        except docker.errors.NotFound:
            raise
        except Exception as exc:
            err_str = str(exc)
            logger.error("service_start_failed", error=err_str, request_id=request_id)
            if "Permission denied" in err_str or isinstance(exc, PermissionError) or "Connection aborted" in err_str:
                _service_simulated_down.pop(service, None)

                target_url = None
                if service == "user-service": target_url = settings.user_service_url
                elif service == "task-service": target_url = settings.task_service_url

                if target_url:
                    try:
                        await _notify_service(
                            target_url,
                            "/internal/service-simulate",
                            {"down": False}
                        )
                    except Exception:
                        pass
                
                return JSONResponse(
                    status_code=200,
                    content={"status": "simulated_started", "service": service, "request_id": request_id, "note": "docker_unavailable_fallback"},
                    headers={"X-Request-ID": request_id},
                )
            raise
    except docker.errors.NotFound:
        return JSONResponse(
            status_code=404,
            content={"error": "container_not_found", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except Exception as exc:
        logger.error("service_start_failed", error=str(exc), request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )


# ── Latency Injection ─────────────────────────────────────────────────────────
@router.post("/slow")
async def simulate_slow(request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    try:
        body = await request.json()
        service = body.get("service", "")
        delay_ms = int(body.get("delay_ms", 500))
        service_url_map = {
            "user-service": settings.user_service_url,
            "task-service": settings.task_service_url,
        }
        if service not in service_url_map:
            return JSONResponse(
                status_code=400,
                content={"error": f"Unknown service: {service}", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )
        async with _state_lock:
            _artificial_delays[service] = delay_ms
        await _notify_service(
            service_url_map[service],
            "/internal/delay",
            {"delay_ms": delay_ms},
        )
        logger.warning("latency_injected", service=service, delay_ms=delay_ms, request_id=request_id)
        return JSONResponse(
            status_code=200,
            content={"status": "delay_injected", "service": service, "delay_ms": delay_ms, "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )


@router.post("/slow-restore")
async def simulate_slow_restore(request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    try:
        body = await request.json()
        service = body.get("service", "")
        service_url_map = {
            "user-service": settings.user_service_url,
            "task-service": settings.task_service_url,
        }
        async with _state_lock:
            _artificial_delays.pop(service, None)
        if service in service_url_map:
            await _notify_service(
                service_url_map[service],
                "/internal/delay",
                {"delay_ms": 0},
            )
        logger.info("latency_restored", service=service, request_id=request_id)
        return JSONResponse(
            status_code=200,
            content={"status": "delay_removed", "service": service, "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )


# ── Current simulation state (for dashboard) ──────────────────────────────────
@router.get("/state")
async def simulation_state(request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=200,
        content={
            "db_simulated_down": _db_simulated_down,
            "artificial_delays": _artificial_delays,
            "service_simulated_down": _service_simulated_down,
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )
