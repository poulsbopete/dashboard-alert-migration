#!/usr/bin/env python3
"""
Legacy: bulk-index ECS-shaped documents directly into Elasticsearch (bypasses OTLP).

The workshop default is OpenTelemetry SDK → Grafana Alloy → managed OTLP. Track bootstrap runs this
script only when WORKSHOP_ALLOW_BULK_SEED=1. Prefer ./scripts/start_workshop_otel.sh for real OTLP.

Uses ES_URL + ES_API_KEY, or ES_USERNAME + ES_PASSWORD (same as workshop ~/.bashrc).

Usage:
  cd /root/workshop && source ~/.bashrc
  python3 tools/seed_workshop_telemetry.py
  # Continuous metric history for Discover **ts metrics-*** (bulk, same service names as OTLP fleet):
  python3 tools/seed_workshop_telemetry.py --metrics-time-series --days 30 --metric-time-step-minutes 60
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import secrets
import sys
from datetime import datetime, timedelta, timezone

import requests

# Align names with tools/otel_workshop_fleet.py so Discover / ES|QL match live OTLP.
_FLEET_SERVICES_HOSTS: tuple[tuple[str, str], ...] = (
    ("checkout-api", "workshop-node-01"),
    ("inventory-api", "workshop-node-02"),
    ("notifications-worker", "workshop-node-03"),
    ("frontend-web", "workshop-node-04"),
    ("pricing-api", "workshop-node-05"),
    ("auth-service", "workshop-node-06"),
)


def es_client() -> tuple[str, dict[str, str], object]:
    es = (os.environ.get("ES_URL") or "").rstrip("/")
    if not es:
        print("ERROR: ES_URL is not set.", file=sys.stderr)
        sys.exit(1)
    api_key = (os.environ.get("ES_API_KEY") or "").strip()
    user = (os.environ.get("ES_USERNAME") or "admin").strip()
    password = (os.environ.get("ES_PASSWORD") or "").strip()
    headers: dict[str, str] = {}
    auth: object = None
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"
    elif password:
        auth = (user, password)
    else:
        print("ERROR: Set ES_API_KEY or ES_PASSWORD (source ~/.bashrc on the workshop VM).", file=sys.stderr)
        sys.exit(1)
    return es, headers, auth


def _hex_trace_id() -> str:
    return secrets.token_hex(16)


def _hex_id16() -> str:
    return secrets.token_hex(8)


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed workshop logs + metrics + traces for Discover / ES|QL demos.")
    ap.add_argument("--log-docs", type=int, default=400, help="Number of synthetic log documents")
    ap.add_argument(
        "--metric-docs",
        type=int,
        default=200,
        help="Number of synthetic metric documents (random mode only)",
    )
    ap.add_argument(
        "--metrics-time-series",
        action="store_true",
        help="Emit metrics on a regular time grid (fleet service × time step) for full-width TS in Discover / Lens",
    )
    ap.add_argument(
        "--metric-time-step-minutes",
        type=int,
        default=60,
        help="Minutes between grid points when --metrics-time-series (default 60)",
    )
    ap.add_argument(
        "--metric-series-cap",
        type=int,
        default=20000,
        help="Max metric documents when --metrics-time-series (default 20000; full grid may be smaller)",
    )
    ap.add_argument(
        "--trace-transactions",
        type=int,
        default=80,
        help="Number of synthetic trace trees (each adds 1 transaction + spans)",
    )
    ap.add_argument(
        "--spans-per-trace",
        type=int,
        default=2,
        help="Child spans per transaction (fixed count, 0-8)",
    )
    ap.add_argument(
        "--days",
        type=int,
        default=14,
        help="Spread @timestamp over this many days (relative to now, UTC)",
    )
    args = ap.parse_args()

    es, headers, auth = es_client()
    rng = random.Random(42)
    now = datetime.now(timezone.utc)
    window_mins = max(1, args.days * 24 * 60)

    bulk_lines: list[str] = []

    def add_create(index: str, doc: dict[str, object]) -> None:
        bulk_lines.append(json.dumps({"create": {"_index": index}}))
        bulk_lines.append(json.dumps(doc, default=str))

    services_log = ["workshop-api", "workshop-checkout", "workshop-worker", "workshop-billing"]
    hosts = [f"workshop-host-{n}" for n in range(1, 6)]

    for i in range(args.log_docs):
        ts = now - timedelta(minutes=rng.randint(0, window_mins))
        ts_s = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        hn = rng.choice(hosts)
        add_create(
            "logs-workshop-default",
            {
                "@timestamp": ts_s,
                "message": f"workshop synthetic request id={i}",
                "log.level": rng.choice(["info", "info", "warn", "error"]),
                "service.name": rng.choice(services_log),
                "service.version": "1.0.0-workshop",
                "host.name": hn,
                "host.hostname": hn,
                "agent.type": "workshop-seed",
                "url.path": rng.choice(["/api/health", "/api/orders", "/api/users"]),
                "http.response.status_code": rng.choice([200, 200, 200, 404, 500]),
            },
        )

    metric_docs_written = 0
    if args.metrics_time_series:
        step = max(1, int(args.metric_time_step_minutes))
        slots = (window_mins // step) + 1
        planned = slots * len(_FLEET_SERVICES_HOSTS)
        ts_cap = min(max(1, args.metric_series_cap), planned)
        routes = ["/health", "/api/v1/orders", "/api/v1/users", "/api/v1/cart", "/readyz"]
        for mn in range(0, window_mins + 1, step):
            for si, (svc, hn) in enumerate(_FLEET_SERVICES_HOSTS):
                if metric_docs_written >= ts_cap:
                    break
                ts = now - timedelta(minutes=mn)
                ts_s = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                phase = (mn / 180.0) + si * 0.7
                cpu_pct = 0.28 + 0.35 * math.sin(phase) + rng.uniform(-0.04, 0.04)
                mem_pct = 0.42 + 0.22 * math.sin(phase * 0.83 + 1.1) + rng.uniform(-0.03, 0.03)
                rate_v = max(5.0, 120.0 + 180.0 * (0.5 + 0.5 * math.sin(phase * 0.5)) + rng.uniform(-20, 20))
                add_create(
                    "metrics-workshop-default",
                    {
                        "@timestamp": ts_s,
                        "host.name": hn,
                        "host.hostname": hn,
                        "service.name": svc,
                        "service.version": "workshop-seed",
                        "agent.type": "workshop-seed",
                        "event.dataset": "workshop.synthetic",
                        "http.route": routes[(mn + si) % len(routes)],
                        "workshop.requests": {"rate": round(rate_v, 2)},
                        "system.cpu.total.norm.pct": round(max(0.02, min(0.98, cpu_pct)), 4),
                        "system.memory.actual.used.pct": round(max(0.05, min(0.98, mem_pct)), 4),
                    },
                )
                metric_docs_written += 1
            if metric_docs_written >= ts_cap:
                break
    else:
        for i in range(args.metric_docs):
            ts = now - timedelta(minutes=rng.randint(0, window_mins))
            ts_s = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            hn = rng.choice(hosts)
            svc = rng.choice(services_log)
            add_create(
                "metrics-workshop-default",
                {
                    "@timestamp": ts_s,
                    "host.name": hn,
                    "host.hostname": hn,
                    "service.name": svc,
                    "agent.type": "workshop-seed",
                    "event.dataset": "workshop.synthetic",
                    "workshop.requests": {"rate": round(rng.uniform(10, 500), 2)},
                    # Common numeric shape so Lens / metrics views can aggregate something beyond custom workshop.* :
                    "system.cpu.total.norm.pct": round(rng.uniform(0.05, 0.85), 4),
                    "system.memory.actual.used.pct": round(rng.uniform(0.2, 0.92), 4),
                },
            )
            metric_docs_written += 1

    n_spans = max(0, min(int(args.spans_per_trace), 8))
    trace_docs = 0
    for _ in range(max(0, args.trace_transactions)):
        base_m = rng.randint(0, window_mins)
        ts0 = now - timedelta(minutes=base_m)
        trace_id = _hex_trace_id()
        trans_id = _hex_id16()
        svc = rng.choice(["workshop-checkout", "workshop-api", "workshop-service"])
        trans_ts = ts0.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        thost = rng.choice(hosts)
        dur_us = rng.randint(8_000, 900_000)
        add_create(
            "traces-workshop-default",
            {
                "@timestamp": trans_ts,
                "processor.event": "transaction",
                "trace.id": trace_id,
                "transaction.id": trans_id,
                "transaction.type": "request",
                "transaction.name": rng.choice(
                    ["GET /checkout", "POST /orders", "GET /users", "internal.poll"]
                ),
                "transaction.duration.us": dur_us,
                "transaction.result": rng.choice(["success", "success", "failure"]),
                "event.outcome": rng.choice(["success", "success", "failure"]),
                "service.name": svc,
                "service.environment": "workshop",
                "host.name": thost,
                "host.hostname": thost,
                "agent.name": "workshop-seed",
                "http.response.status_code": rng.choice([200, 200, 201, 404, 500]),
            },
        )
        trace_docs += 1
        for s in range(n_spans):
            span_ts = ts0 + timedelta(milliseconds=5 + s * 12)
            span_ts_s = span_ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            span_id = _hex_id16()
            sdur = rng.randint(500, 120_000)
            add_create(
                "traces-workshop-default",
                {
                    "@timestamp": span_ts_s,
                    "processor.event": "span",
                    "trace.id": trace_id,
                    "transaction.id": trans_id,
                    "span.id": span_id,
                    "parent.id": trans_id,
                    "span.type": rng.choice(["app", "db", "external"]),
                    "span.name": rng.choice(
                        ["validate_cart", "charge_card", "fetch_inventory", "redis.get", "http.client"]
                    ),
                    "span.duration.us": sdur,
                    "event.outcome": "success",
                    "service.name": svc,
                    "service.environment": "workshop",
                    "host.name": thost,
                    "host.hostname": thost,
                },
            )
            trace_docs += 1

    body = "\n".join(bulk_lines) + "\n"
    h = {**headers, "Content-Type": "application/x-ndjson"}
    r = requests.post(
        f"{es}/_bulk?refresh=wait_for",
        headers=h,
        auth=auth,
        data=body.encode("utf-8"),
        timeout=180,
    )
    if not r.ok:
        print(f"ERROR: bulk HTTP {r.status_code} {r.text[:1200]}", file=sys.stderr)
        return 1
    try:
        payload = r.json()
    except json.JSONDecodeError:
        print("ERROR: non-JSON bulk response", file=sys.stderr)
        return 1
    if payload.get("errors"):
        for item in (payload.get("items") or [])[:5]:
            err = (item.get("create") or item.get("index") or {}).get("error")
            if err:
                print("ERROR item:", json.dumps(err)[:500], file=sys.stderr)
        print("ERROR: bulk reported errors (see above; first 5 shown)", file=sys.stderr)
        return 1

    print(
        f"OK: indexed {args.log_docs} → logs-workshop-default, "
        f"{metric_docs_written} → metrics-workshop-default, "
        f"{trace_docs} → traces-workshop-default "
        f"({args.trace_transactions} transactions × (1 + {n_spans}) docs; last {args.days}d window"
        f"{'; metrics-time-series grid' if args.metrics_time_series else ''})."
    )
    print(
        "\nDiscover / data views:\n"
        "  • If **traces-*** is missing from the Data view dropdown: **Stack Management → Data views → Create data view**\n"
        "    → Index pattern **traces-*** (or **traces-workshop-default**) → Time field **@timestamp**.\n"
        "  • **Applications**, **Infrastructure**, and curated **APM/hosts** screens expect **OTLP** (Alloy → mOTLP) or\n"
        "    **Elastic Agent** integrations — not bulk JSON. For live services/hosts: set **WORKSHOP_OTLP_ENDPOINT** and run\n"
        "    **./scripts/start_workshop_otel.sh** on the workshop VM (see README).\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
