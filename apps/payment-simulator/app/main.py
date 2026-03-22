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

HIGH_CARD = int(os.environ.get("HIGH_CARD_MERCHANTS", "0"))
METRICS_ONLY = os.environ.get("METRICS_ONLY", "0") == "1"

logger = structlog.get_logger()

REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests",
    ["method", "path", "status", "merchant_id"],
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "Latency",
    ["method", "path", "merchant_id"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
PAYMENT_ERRORS = Counter(
    "payment_errors_total",
    "Simulated payment errors",
    ["merchant_id", "reason"],
)


def merchant_pool():
    if HIGH_CARD > 0:
        return [f"m_{i}" for i in range(HIGH_CARD)]
    return ["paypal_merch_us", "paypal_merch_eu", "paypal_merch_apac", "marketplace_demo"]


MERCHANTS = merchant_pool()


def configure_tracing():
    if METRICS_ONLY:
        return
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME", "payment-simulator"),
            "deployment.environment": "workshop",
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


configure_tracing()
app = FastAPI(title="Merchant Payments Simulator", version="1.0.0")


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    merchant = random.choice(MERCHANTS)
    start = time.perf_counter()
    response = await call_next(request)
    dur = time.perf_counter() - start
    status = str(response.status_code)
    REQUESTS.labels(request.method, request.url.path, status, merchant).inc()
    LATENCY.labels(request.method, request.url.path, merchant).observe(dur)
    return response


@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok"})


@app.post("/v1/payments")
def create_payment():
    merchant = random.choice(MERCHANTS)
    if random.random() < 0.08:
        reason = random.choice(["insufficient_funds", "risk_hold", "network_timeout"])
        PAYMENT_ERRORS.labels(merchant, reason).inc()
        logger.error("payment_failed", merchant_id=merchant, reason=reason)
        return JSONResponse({"error": reason, "merchant_id": merchant}, status=502)
    txn = str(uuid.uuid4())
    logger.info(
        "payment_captured",
        merchant_id=merchant,
        transaction_id=txn,
        amount_cents=random.randint(50, 5000),
    )
    return {"transaction_id": txn, "merchant_id": merchant, "status": "captured"}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


FastAPIInstrumentor.instrument_app(app)
