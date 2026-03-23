#!/usr/bin/env python3
"""
Multiple synthetic microservices → OTLP → local Grafana Alloy → Elastic mOTLP.

Launches one Python subprocess per service (each has distinct service.name + host.name) so
**Applications**, **Infrastructure**, and **Hosts** in Observability show multiple entities.

Parent process only supervises; workers are spawned with this same file + "worker" + JSON spec
so `pkill -f otel_workshop_fleet.py` stops the whole fleet.

Env:
  WORKSHOP_ALLOY_OTLP_HTTP — default http://127.0.0.1:4318
  WORKSHOP_EMIT_INTERVAL_SEC — base sleep between trace ticks per worker (default 8)
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

FLEET: list[dict[str, str]] = [
    {"service": "checkout-api", "host": "workshop-node-01", "version": "1.4.2", "lang": "python"},
    {"service": "inventory-api", "host": "workshop-node-02", "version": "2.0.1", "lang": "python"},
    {"service": "notifications-worker", "host": "workshop-node-03", "version": "0.9.8", "lang": "go"},
    {"service": "frontend-web", "host": "workshop-node-04", "version": "3.2.0", "lang": "nodejs"},
    {"service": "pricing-api", "host": "workshop-node-05", "version": "1.1.0", "lang": "python"},
    {"service": "auth-service", "host": "workshop-node-06", "version": "4.0.0", "lang": "python"},
]


def _run_worker(spec: dict[str, str]) -> int:
    import math
    import random

    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.metrics import Observation
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    base = (os.environ.get("WORKSHOP_ALLOY_OTLP_HTTP") or "http://127.0.0.1:4318").rstrip("/")
    service = spec["service"]
    host = spec["host"]
    version = spec["version"]
    lang = spec["lang"]
    seed = hash(service) % (2**32)
    rng = random.Random(seed)
    t0 = time.time()

    resource = Resource.create(
        {
            "service.name": service,
            "service.version": version,
            "deployment.environment": "instruqt",
            "host.name": host,
            "host.type": "linux",
            "os.type": "linux",
            "telemetry.sdk.name": "opentelemetry",
            "telemetry.sdk.language": lang,
            "cloud.provider": "aws",
            "cloud.region": "us-east-1",
            "cloud.availability_zone": "us-east-1a",
        }
    )

    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{base}/v1/traces"))
    )
    trace.set_tracer_provider(trace_provider)
    tracer = trace.get_tracer(__name__, version)

    def cpu_obs(_options: object):
        phase = (time.time() - t0) / 42.0 + (seed % 5)
        v = 0.22 + 0.38 * math.sin(phase) + rng.uniform(-0.06, 0.06)
        yield Observation(max(0.06, min(0.94, v)))

    def mem_obs(_options: object):
        phase = (time.time() - t0) / 55.0
        v = 0.38 + 0.28 * math.sin(phase * 0.85) + rng.uniform(-0.05, 0.05)
        yield Observation(max(0.18, min(0.93, v)))

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{base}/v1/metrics"),
        export_interval_millis=12_000,
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
    meter = metrics.get_meter(__name__, version)

    meter.create_observable_gauge(
        "system.cpu.utilization",
        unit="1",
        description="CPU utilization (0–1) for host correlation",
        callbacks=[cpu_obs],
    )
    meter.create_observable_gauge(
        "system.memory.utilization",
        unit="1",
        description="Memory utilization (0–1) for host correlation",
        callbacks=[mem_obs],
    )

    duration_hist = meter.create_histogram(
        "http.server.request.duration",
        unit="s",
        description="HTTP server request duration",
    )
    req_counter = meter.create_counter(
        "http.server.request.count",
        description="HTTP server requests",
    )

    routes = ["/health", "/api/v1/orders", "/api/v1/users", "/api/v1/cart", "/readyz"]
    interval = float((os.environ.get("WORKSHOP_EMIT_INTERVAL_SEC") or "8").strip() or "8")

    print(f"fleet worker {service} @ {host} → {base}", flush=True)
    n = 0
    while True:
        n += 1
        route = routes[n % len(routes)]
        duration_s = round(rng.uniform(0.006, 0.42), 4)
        status = rng.choice([200, 200, 200, 201, 204, 429, 500])
        method = "GET" if n % 3 else "POST"
        span_name = f"{method} {route}"
        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("http.request.method", method)
            span.set_attribute("http.route", route)
            span.set_attribute("http.response.status_code", status)
            span.set_attribute("url.scheme", "http")
            span.set_attribute("server.address", host)

        duration_hist.record(
            duration_s,
            {
                "http.route": route,
                "http.request.method": method,
                "http.response.status_code": str(status),
            },
        )
        req_counter.add(
            1,
            {
                "http.route": route,
                "http.response.status_code": str(status),
            },
        )
        time.sleep(max(2.0, interval + rng.uniform(-1.0, 2.0)))


def _supervise() -> int:
    myself = str(Path(__file__).resolve())
    repo_root = str(Path(__file__).resolve().parent.parent)
    exe = sys.executable
    children: list[subprocess.Popen[str]] = []
    log_path = os.environ.get("WORKSHOP_FLEET_LOG") or "/tmp/workshop-fleet.log"
    log_f = open(log_path, "a", encoding="utf-8", buffering=1)

    for spec in FLEET:
        cmd = [exe, myself, "worker", json.dumps(spec)]
        children.append(
            subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                cwd=repo_root,
            )
        )

    print(
        f"otel_workshop_fleet: started {len(children)} workers → Alloy :4318 (log {log_path})",
        flush=True,
    )

    def _terminate_children() -> None:
        for c in children:
            if c.poll() is None:
                c.terminate()
        deadline = time.time() + 12
        for c in children:
            remaining = max(0.1, deadline - time.time())
            try:
                c.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                c.kill()
        try:
            log_f.close()
        except OSError:
            pass

    def _on_signal(_sig: int | None = None, _frame: object | None = None) -> None:
        _terminate_children()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    try:
        while True:
            time.sleep(5)
            for c in children:
                if c.poll() is not None:
                    print(f"WARN: fleet worker exited code={c.returncode}, stopping fleet", flush=True)
                    _terminate_children()
                    sys.exit(1)
    except KeyboardInterrupt:
        _terminate_children()
        sys.exit(0)


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "worker":
        _run_worker(json.loads(sys.argv[2]))
        return 0
    return _supervise()


if __name__ == "__main__":
    raise SystemExit(main())
