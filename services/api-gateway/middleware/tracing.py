"""OpenTelemetry tracing setup for FastAPI services."""
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
import structlog

logger = structlog.get_logger(__name__)


def setup_tracing(app, service_name: str, jaeger_endpoint: str):
    """Configure OpenTelemetry with OTLP gRPC exporter."""
    try:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=jaeger_endpoint, insecure=True)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        logger.info("tracing_configured", service=service_name, endpoint=jaeger_endpoint)
    except Exception as exc:
        logger.warning("tracing_setup_failed", error=str(exc))
