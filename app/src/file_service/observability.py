"""Structured JSON logs, Prometheus RED metrics, optional OpenTelemetry tracing."""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

# Buckets cluster around the 300 ms SLO threshold so the SLI can be computed exactly.
REQUESTS = Counter("http_requests_total", "HTTP requests", ["route", "method", "status"])
LATENCY = Histogram("http_request_duration_seconds", "HTTP latency", ["route", "method"],
                    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.5, 1, 2.5))
BACKEND_ERRORS = Counter("backend_errors_total", "Dependency failures", ["backend", "reason"])


class JsonFormatter(logging.Formatter):
    """Cloud Logging understands `severity` and `logging.googleapis.com/trace` keys natively."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": request_id_ctx.get(),
        }
        payload.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def configure_tracing(app) -> None:
    """Enabled when OTEL_EXPORTER_OTLP_ENDPOINT is set (GKE: OTel collector -> Cloud Trace)."""
    import os
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    provider = TracerProvider(resource=Resource.create({"service.name": "file-service"}),
                              sampler=ParentBased(TraceIdRatioBased(0.05)))  # 5% at 6k rps
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_ctx.set(rid[:64])
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = request_id_ctx.get()
            response.headers["x-content-type-options"] = "nosniff"
            response.headers["cache-control"] = "no-store"
            return response
        finally:
            route = request.scope.get("route")
            route_name = getattr(route, "path", "unmatched")   # template, not raw path: bounded cardinality
            elapsed = time.perf_counter() - start
            if route_name not in {"/healthz", "/readyz", "/metrics"}:
                REQUESTS.labels(route_name, request.method, str(status)).inc()
                LATENCY.labels(route_name, request.method).observe(elapsed)
                logging.getLogger("access").info(
                    "request", extra={"extra_fields": {
                        "httpRequest": {"requestMethod": request.method, "requestUrl": route_name,
                                        "status": status, "latency": f"{elapsed:.4f}s"}}})
            request_id_ctx.reset(token)
