"""Rate limiter setup for API Gateway."""
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request
from fastapi.responses import JSONResponse


limiter = Limiter(key_func=get_remote_address, default_limits=["2000/minute"])


async def rate_limit_exceeded_handler(request: Request, exc):
    return JSONResponse(
        status_code=429,
        content={"message": "Rate limit exceeded. Please slow down.", "path": str(request.url.path)},
    )
