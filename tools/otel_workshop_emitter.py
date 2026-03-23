#!/usr/bin/env python3
"""
Emit OTLP traces + metrics to local Grafana Alloy (127.0.0.1:4317/4318), which forwards to Elastic mOTLP.

Run on the workshop VM after Alloy starts (see track setup or scripts/start_workshop_otel.sh).

Env:
  WORKSHOP_ALLOY_OTLP_HTTP — default http://127.0.0.1:4318
"""
from __future__ import annotations

import os
import sys
import time

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def main() -> int:
    base = (os.environ.get("WORKSHOP_ALLOY_OTLP_HTTP") or "http://127.0.0.1:4318").rstrip("/")
    resource = Resource.create(
        {
            "service.name": "workshop-otel-emitter",
            "deployment.environment": "instruqt",
        }
    )

    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{base}/v1/traces"))
    )
    trace.set_tracer_provider(trace_provider)

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{base}/v1/metrics"),
        export_interval_millis=10_000,
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
    meter = metrics.get_meter(__name__)
    req_counter = meter.create_counter(
        "workshop.http_requests",
        description="Sample HTTP request counter emitted via OTLP (OpenTelemetry SDK → Alloy → mOTLP)",
    )

    tracer = trace.get_tracer(__name__)
    interval = float((os.environ.get("WORKSHOP_EMIT_INTERVAL_SEC") or "10").strip() or "10")

    print(f"workshop OTLP emitter → {base} (interval {interval}s)", flush=True)
    n = 0
    while True:
        n += 1
        with tracer.start_as_current_span("workshop.tick") as span:
            span.set_attribute("workshop.sequence", n)
            req_counter.add(1, {"route": "/api/demo", "status": "200"})
        time.sleep(interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(0)
