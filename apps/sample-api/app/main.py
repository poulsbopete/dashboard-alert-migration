import os
import random
import time
import uuid

import structlog
from fastapi import FastAPI, Request
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import JSONResponse, PlainTextResponse

HIGH_CARD = int(os.environ.get("HIGH_CARD_ENTITIES", "0"))
METRICS_ONLY = os.environ.get("METRICS_ONLY", "0") == "1"

logger = structlog.get_logger()

REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests",
    ["method", "path", "status", "entity_id"],
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "Latency",
    ["method", "path", "entity_id"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
OPERATION_ERRORS = Counter(
    "operation_errors_total",
    "Simulated operation errors",
    ["entity_id", "reason"],
)


def entity_pool():
    if HIGH_CARD > 0:
        return [f"e_{i}" for i in range(HIGH_CARD)]
    return ["tenant_a", "tenant_b", "tenant_c", "shared_pool"]


ENTITIES = entity_pool()


def configure_tracing():
    if METRICS_ONLY:
        return
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME", "sample-api"),
            "deployment.environment": "workshop",
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


configure_tracing()
app = FastAPI(title="Sample API (workshop telemetry)", version="1.0.0")


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    entity = random.choice(ENTITIES)
    start = time.perf_counter()
    response = await call_next(request)
    dur = time.perf_counter() - start
    status = str(response.status_code)
    REQUESTS.labels(request.method, request.url.path, status, entity).inc()
    LATENCY.labels(request.method, request.url.path, status, entity).observe(dur)
    return response


@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok"})


@app.post("/v1/invoke")
def invoke():
    entity = random.choice(ENTITIES)
    if random.random() < 0.08:
        reason = random.choice(["upstream_timeout", "rate_limited", "dependency_error"])
        OPERATION_ERRORS.labels(entity, reason).inc()
        logger.error("request_failed", entity_id=entity, reason=reason)
        return JSONResponse({"error": reason, "entity_id": entity}, status=502)
    rid = str(uuid.uuid4())
    logger.info(
        "request_completed",
        entity_id=entity,
        request_id=rid,
        units=random.randint(1, 100),
    )
    return {"request_id": rid, "entity_id": entity, "status": "ok"}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


FastAPIInstrumentor.instrument_app(app)
