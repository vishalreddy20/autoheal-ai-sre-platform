"""Request ID middleware — injects a UUID into every request."""
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
        
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        
        # Inject into headers so proxy routes forward them automatically
        scope = request.scope
        headers = dict(request.headers)
        headers["x-request-id"] = request_id
        headers["x-trace-id"] = trace_id
        scope["headers"] = [
            (k.lower().encode(), v.encode())
            for k, v in headers.items()
        ]
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        return response
