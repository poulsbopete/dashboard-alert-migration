#!/usr/bin/env python3
"""
Bulk-index minimal ECS-style documents into Observability data streams so Discover and
ES|QL (e.g. FROM logs-*,metrics-*,traces-*) have @timestamp-backed data.

Fallback when Grafana Alloy → managed OTLP is not configured (see assets/alloy/workshop.alloy
and track_scripts/setup-es3-api). Prefer OTLP ingest for parity with elastic-autonomous-observability.

Uses ES_URL + ES_API_KEY, or ES_USERNAME + ES_PASSWORD (same as workshop ~/.bashrc).

Usage:
  cd /root/workshop && source ~/.bashrc
  python3 tools/seed_workshop_telemetry.py
"""
from __future__ import annotations

import argparse
import json
import os
import random
import secrets
import sys
from datetime import datetime, timedelta, timezone

import requests


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
    ap.add_argument("--metric-docs", type=int, default=200, help="Number of synthetic metric documents")
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

    for i in range(args.log_docs):
        ts = now - timedelta(minutes=rng.randint(0, window_mins))
        ts_s = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        add_create(
            "logs-workshop-default",
            {
                "@timestamp": ts_s,
                "message": f"workshop synthetic request id={i}",
                "log.level": rng.choice(["info", "info", "warn", "error"]),
                "service.name": "workshop-service",
                "host.name": f"host-{rng.randint(1, 5)}",
                "url.path": rng.choice(["/api/health", "/api/orders", "/api/users"]),
                "http.response.status_code": rng.choice([200, 200, 200, 404, 500]),
            },
        )

    for i in range(args.metric_docs):
        ts = now - timedelta(minutes=rng.randint(0, window_mins))
        ts_s = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        add_create(
            "metrics-workshop-default",
            {
                "@timestamp": ts_s,
                "workshop.requests": {"rate": round(rng.uniform(10, 500), 2)},
            },
        )

    n_spans = max(0, min(int(args.spans_per_trace), 8))
    trace_docs = 0
    for _ in range(max(0, args.trace_transactions)):
        base_m = rng.randint(0, window_mins)
        ts0 = now - timedelta(minutes=base_m)
        trace_id = _hex_trace_id()
        trans_id = _hex_id16()
        svc = rng.choice(["workshop-checkout", "workshop-api", "workshop-service"])
        trans_ts = ts0.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
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
                "transaction.result": rng.choice(["success", "success", "failure"]),
                "event.outcome": rng.choice(["success", "success", "failure"]),
                "service.name": svc,
                "service.environment": "workshop",
                "http.response.status_code": rng.choice([200, 200, 201, 404, 500]),
            },
        )
        trace_docs += 1
        for s in range(n_spans):
            span_ts = ts0 + timedelta(milliseconds=5 + s * 12)
            span_ts_s = span_ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            span_id = _hex_id16()
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
                    "event.outcome": "success",
                    "service.name": svc,
                    "service.environment": "workshop",
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
        f"{args.metric_docs} → metrics-workshop-default, "
        f"{trace_docs} → traces-workshop-default "
        f"({args.trace_transactions} transactions × (1 + {n_spans}) docs; last {args.days}d window)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
