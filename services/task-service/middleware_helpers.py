"""
Shared middleware helpers for task-service.
"""
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

import structlog

logger = structlog.get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        return response


def setup_tracing(app, service_name: str, jaeger_endpoint: str) -> None:
    if not _OTEL_AVAILABLE:
        return
    try:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=jaeger_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        logger.info("tracing_initialized", service=service_name)
    except Exception as exc:
        logger.warning("tracing_init_failed", error=str(exc))
