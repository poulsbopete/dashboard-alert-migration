#!/usr/bin/env python3
"""
Emit OpenTelemetry (traces, metrics, logs) with Datadog-style service/tags into local Grafana Alloy,
which forwards to Elastic Observability **managed OTLP** (mOTLP).

Use this in the Datadog→Elastic migration narrative: same OTLP you would dual-ship or migrate toward,
landing in Elastic’s managed collector instead of Datadog intake.

Env:
  WORKSHOP_ALLOY_OTLP_HTTP — default http://127.0.0.1:4318 (Alloy HTTP OTLP receiver)
  WORKSHOP_DD_OTEL_INTERVAL_SEC — seconds between ticks (default 12)
"""
from __future__ import annotations

import logging
import os
import random
import sys
import time

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def _resource() -> Resource:
    # Datadog Agent / OTLP mapping–friendly resource (service, env, version, host).
    return Resource.create(
        {
            "service.name": (os.environ.get("DD_SERVICE") or "shopist-checkout"),
            "deployment.environment": (os.environ.get("DD_ENV") or "staging"),
            "service.version": (os.environ.get("DD_VERSION") or "2.7.0"),
            "host.name": (os.environ.get("DD_HOSTNAME") or "workshop-node-07"),
            "telemetry.sdk.name": "opentelemetry",
            "telemetry.sdk.language": "python",
        }
    )


def main() -> int:
    base = (os.environ.get("WORKSHOP_ALLOY_OTLP_HTTP") or "http://127.0.0.1:4318").rstrip("/")
    resource = _resource()
    interval = float((os.environ.get("WORKSHOP_DD_OTEL_INTERVAL_SEC") or "12").strip() or "12")

    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{base}/v1/traces"))
    )
    trace.set_tracer_provider(trace_provider)

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{base}/v1/metrics"),
        export_interval_millis=max(5_000, int(interval * 1000)),
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
    meter = metrics.get_meter(__name__, "1.0.0")

    checkout_counter = meter.create_counter(
        "dd.checkout.completed",
        description="Datadog-style custom counter (maps to custom metric in Elastic)",
    )
    latency_hist = meter.create_histogram(
        "dd.http.server.request.duration",
        unit="ms",
        description="Request duration (Datadog-style naming; OTel histogram)",
    )

    log_provider = LoggerProvider(resource=resource)
    log_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{base}/v1/logs"))
    )
    set_logger_provider(log_provider)
    py_log = logging.getLogger("datadog_otel_to_elastic")
    py_log.handlers.clear()
    py_log.setLevel(logging.INFO)
    py_log.addHandler(LoggingHandler(logger_provider=log_provider))
    py_log.propagate = False

    tracer = trace.get_tracer(__name__, "1.0.0")
    rng = random.Random(7)

    routes = [("/api/cart", "GET"), ("/api/checkout", "POST"), ("/api/orders", "GET")]
    print(
        f"Datadog-style OTLP → {base} (service={resource.attributes.get('service.name')!r}, every {interval}s)",
        flush=True,
    )

    n = 0
    while True:
        n += 1
        route, method = routes[n % len(routes)]
        status = rng.choice([200, 200, 201, 404, 500])
        duration_ms = round(rng.uniform(5, 180), 2)

        with tracer.start_as_current_span("dd.http.server.request") as span:
            span.set_attribute("http.request.method", method)
            span.set_attribute("http.route", route)
            span.set_attribute("http.response.status_code", status)
            span.set_attribute("net.host.name", str(resource.attributes.get("host.name") or ""))
            # Tags many teams still send when mirroring DD on OTLP:
            span.set_attribute("dd.service", str(resource.attributes.get("service.name") or ""))
            span.set_attribute("dd.env", str(resource.attributes.get("deployment.environment") or ""))
            span.set_attribute("dd.span_type", "web")
            span.set_attribute("workshop.sequence", n)

            checkout_counter.add(
                1,
                {
                    "env": str(resource.attributes.get("deployment.environment") or ""),
                    "service": str(resource.attributes.get("service.name") or ""),
                    "http.route": route,
                    "http.status_code": str(status),
                },
            )
            latency_hist.record(
                duration_ms,
                {
                    "http.route": route,
                    "http.request.method": method,
                },
            )

        py_log.info(
            "checkout pipeline event (Datadog-style log → OTLP → Elastic)",
            extra={
                "http.route": route,
                "http.method": method,
                "http.status_code": status,
                "duration_ms": duration_ms,
                "dd.service": str(resource.attributes.get("service.name") or ""),
                "dd.env": str(resource.attributes.get("deployment.environment") or ""),
            },
        )
        time.sleep(interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(0)
