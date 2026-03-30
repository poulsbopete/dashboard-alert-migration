#!/usr/bin/env python3
"""
Discover which workshop OTLP patterns (`logs-*`, `metrics-*`, …) return data, then create one
Kibana dashboard with ES|QL Lens panels tailored to those patterns — no Grafana/Datadog JSON required.

Uses the same conventions as `publish_grafana_drafts_kibana.py` (BUCKET duration, `service.name`, mOTLP metrics).

Environment (after `source ~/.bashrc` on es3-api):
  ES_URL, ES_API_KEY (or ES_USERNAME + ES_PASSWORD) — ES|QL probe
  KIBANA_URL, ES_API_KEY — Dashboards API

Optional:
  WORKSHOP_ESQL_FROM — skip probing; force FROM clause (e.g. metrics-*)
  WORKSHOP_ESQL_BUCKET_DURATION, WORKSHOP_ESQL_TIME_FIELD, WORKSHOP_ESQL_SERVICE_NAME_COLUMN — same as publisher
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from publish_grafana_drafts_kibana import (
    _esql_bucket_expr,
    _esql_http_route_column,
    _esql_ident,
    _esql_service_name_column,
    _esql_time_bucket_field,
    _esql_volume_probe_queries,
    _from_clause_from_probe,
    _from_capabilities,
    _layout_note_and_data_panels,
    _lens_from_spec,
    _short_listing_description,
    _spec_xy,
    build_description,
    dashboards_api_headers,
    kibana_client,
    markdown_for_canvas,
)


def _es_base() -> str:
    es = (os.environ.get("ES_URL") or "").rstrip("/")
    if not es:
        print("ERROR: ES_URL is not set (needed to probe ES|QL). Run: source ~/.bashrc", file=sys.stderr)
        sys.exit(1)
    return es


def _es_auth_headers() -> tuple[dict[str, str], Any]:
    api_key = (os.environ.get("ES_API_KEY") or "").strip()
    user = (os.environ.get("ES_USERNAME") or "").strip()
    password = (os.environ.get("ES_PASSWORD") or "").strip()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    auth: Any = None
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"
    elif user and password:
        auth = (user, password)
    else:
        print(
            "ERROR: Set ES_API_KEY or ES_USERNAME+ES_PASSWORD for ES|QL probe.",
            file=sys.stderr,
        )
        sys.exit(1)
    return headers, auth


def _esql_ok(es_base: str, headers: dict[str, str], auth: Any, query: str) -> bool:
    h = {k: v for k, v in headers.items() if k.lower() == "authorization"}
    h["Content-Type"] = "application/json"
    try:
        r = requests.post(
            f"{es_base}/_query",
            headers=h,
            auth=auth,
            json={"query": query},
            timeout=90,
        )
    except requests.RequestException:
        return False
    return r.status_code == 200


def _first_working_from_clause() -> tuple[str, str]:
    """Return (from_clause, probe_esql_line)."""
    override = (os.environ.get("WORKSHOP_ESQL_FROM") or "").strip()
    es_base = _es_base()
    h, auth = _es_auth_headers()
    if override:
        tf = _esql_time_bucket_field()
        probe = f"FROM {override} | STATS c = COUNT(*) BY bucket = {_esql_bucket_expr(tf)}"
        if _esql_ok(es_base, h, auth, probe):
            return override, probe
        print(f"ERROR: WORKSHOP_ESQL_FROM={override!r} did not return a valid ES|QL result.", file=sys.stderr)
        sys.exit(1)

    for probe in _esql_volume_probe_queries():
        if _esql_ok(es_base, h, auth, probe):
            return _from_clause_from_probe(probe), probe
    print(
        "ERROR: No workshop pattern returned data (tried logs-*, metrics-*, …). "
        "Start OTLP (./scripts/start_workshop_otel.sh) or set WORKSHOP_ESQL_FROM.",
        file=sys.stderr,
    )
    sys.exit(1)


def _markdown_panel(from_clause: str, probe_sql: str) -> str:
    lines = [
        "## Dynamic observability dashboard",
        "",
        f"This dashboard was generated from **live data** in your Serverless project.",
        "",
        f"- **Resolved `FROM`:** `{from_clause}`",
        f"- **Probe query:** `{probe_sql[:100]}{'…' if len(probe_sql) > 100 else ''}`",
        "",
        "Panels use ES|QL aligned with **OTLP / mOTLP** field names (`service.name`, `http.server.request.count`, …). "
        "Re-run after ingest changes: `python3 tools/generate_dynamic_o11y_dashboard.py`.",
    ]
    return "\n".join(lines)


def _build_specs_for_capabilities(from_clause: str) -> list[dict[str, Any]]:
    tf = _esql_time_bucket_field()
    qb = _esql_bucket_expr(tf)
    svc = _esql_ident(_esql_service_name_column())
    route = _esql_ident(_esql_http_route_column())
    cap = _from_capabilities(from_clause)
    specs: list[dict[str, Any]] = []

    if cap["metrics"]:
        specs.append(
            _spec_xy(
                "metrics-*",
                tf,
                layer="line",
                query=(
                    f"FROM metrics-* | STATS c = COUNT(*) BY bucket = {qb}, svc = {svc}"
                ),
                x="bucket",
                ys=[("c", None)],
                breakdown="svc",
                lens_title="Metric datapoints by service",
            )
        )
        specs.append(
            _spec_xy(
                "metrics-*",
                tf,
                layer="line",
                query=(
                    f"FROM metrics-* | STATS m = AVG(`system.cpu.utilization`) "
                    f"BY bucket = {qb}, svc = {svc}"
                ),
                x="bucket",
                ys=[("m", None)],
                breakdown="svc",
                lens_title="CPU utilization by service (OTel)",
            )
        )
        specs.append(
            _spec_xy(
                "metrics-*",
                tf,
                layer="area",
                query=(
                    f"FROM metrics-* | STATS c = SUM(`http.server.request.count`) "
                    f"BY bucket = {qb}, svc = {svc}"
                ),
                x="bucket",
                ys=[("c", None)],
                breakdown="svc",
                lens_title="HTTP server requests by service",
            )
        )
        specs.append(
            _spec_xy(
                "metrics-*",
                tf,
                layer="bar",
                query=(
                    f"FROM metrics-* | STATS c = SUM(`http.server.request.count`) "
                    f"BY path = {route} | SORT c DESC | LIMIT 12"
                ),
                x="path",
                ys=[("c", None)],
                breakdown=None,
                lens_title="HTTP requests by route",
            )
        )

    if cap["logs"]:
        specs.append(
            _spec_xy(
                "logs-*",
                tf,
                layer="line",
                query=(
                    f"FROM logs-* | STATS c = COUNT(*) BY bucket = {qb}, svc = {svc}"
                ),
                x="bucket",
                ys=[("c", None)],
                breakdown="svc",
                lens_title="Log volume by service",
            )
        )

    traces_in_from = "trace" in from_clause.lower()
    if cap["traces"] and traces_in_from:
        specs.append(
            _spec_xy(
                "traces-*",
                tf,
                layer="line",
                query=(
                    f'FROM traces-* | WHERE processor.event == "transaction" '
                    f"| STATS m = AVG(transaction.duration.us) BY bucket = {qb}, svc = {svc}"
                ),
                x="bucket",
                ys=[("m", None)],
                breakdown="svc",
                lens_title="Avg transaction duration (µs)",
            )
        )
        specs.append(
            _spec_xy(
                "traces-*",
                tf,
                layer="bar",
                query=(
                    "FROM traces-* | STATS c = COUNT(*) BY name = span.name "
                    "| SORT c DESC | LIMIT 12"
                ),
                x="name",
                ys=[("c", None)],
                breakdown=None,
                lens_title="Top span names",
            )
        )

    if not specs:
        specs.append(
            _spec_xy(
                from_clause,
                tf,
                layer="line",
                query=f"FROM {from_clause} | STATS c = COUNT(*) BY bucket = {qb}",
                x="bucket",
                ys=[("c", None)],
                breakdown=None,
                lens_title="Event volume",
            )
        )

    return specs


def _attempt_post(
    kibana: str,
    headers: dict[str, str],
    auth: Any,
    *,
    title: str,
    listing_desc: str,
    panels: list[dict[str, Any]],
) -> tuple[bool, str]:
    base: dict[str, Any] = {
        "title": title[:255],
        "description": listing_desc,
        "time_range": {"from": "now-30d", "to": "now"},
        "panels": panels,
    }
    h = dashboards_api_headers(headers)
    r = requests.post(
        f"{kibana}/api/dashboards?apiVersion=1",
        headers=h,
        auth=auth,
        json=base,
        timeout=180,
    )
    if r.status_code in (200, 201):
        return True, (r.json().get("id") or r.json().get("data", {}).get("id") or "")
    return False, f"HTTP {r.status_code} {r.text[:900]}"


def _post_with_fallback(
    kibana: str,
    headers: dict[str, str],
    auth: Any,
    *,
    title: str,
    listing_desc: str,
    lens_panels: list[dict[str, Any]],
    note_rows: list[dict[str, Any]],
) -> tuple[bool, str, str]:
    """Try full layout, then drop Lens panels from the end until POST succeeds."""
    last_err = ""
    for n in range(len(lens_panels), 0, -1):
        subset = lens_panels[:n]
        merged = _layout_note_and_data_panels(note_rows, subset)
        ok, err_or_id = _attempt_post(
            kibana, headers, auth, title=title, listing_desc=listing_desc, panels=merged
        )
        if ok:
            return True, "", str(err_or_id)
        last_err = err_or_id
    return False, last_err, ""


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Create a Kibana dashboard from live logs/metrics/traces patterns (workshop OTLP)."
    )
    ap.add_argument(
        "--title",
        default="Workshop OTLP overview (dynamic)",
        help="Dashboard title",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved FROM + panel queries; do not call Kibana",
    )
    args = ap.parse_args()
    title = str(args.title).strip() or "Workshop OTLP overview (dynamic)"

    from_clause, probe_sql = _first_working_from_clause()
    specs = _build_specs_for_capabilities(from_clause)
    lens_panels = [_lens_from_spec(s) for s in specs]

    if args.dry_run:
        print(json.dumps({"from_clause": from_clause, "probe": probe_sql, "panels": len(lens_panels)}, indent=2))
        for i, s in enumerate(specs):
            print(f"\n--- panel {i + 1}: {s.get('lens_title')} ---\n{s.get('query')}")
        return 0

    kibana, headers, auth = kibana_client()
    draft: dict[str, Any] = {
        "title": title,
        "tags": ["workshop-dynamic-o11y"],
        "panels": [
            {"title": "dynamic", "migration": {"promql": probe_sql[:200]}},
        ],
    }
    md_content = _markdown_panel(from_clause, probe_sql)
    detail = build_description(draft)
    canvas_md = markdown_for_canvas(
        f"{md_content}\n\n---\n\n{detail}",
        dashboard_title=title,
    )
    listing_desc = _short_listing_description(draft, title)
    uid = uuid.uuid4()

    note_variants: list[list[dict[str, Any]]] = [
        [
            {
                "grid": {"x": 0, "y": 0, "w": 48, "h": 9},
                "config": {"content": canvas_md},
                "uid": str(uid),
                "type": "markdown",
            }
        ],
        [
            {
                "grid": {"x": 0, "y": 0, "w": 48, "h": 9},
                "config": {"content": canvas_md},
                "uid": str(uid),
                "type": "DASHBOARD_MARKDOWN",
            }
        ],
        [],
    ]

    last_err = ""
    for note_rows in note_variants:
        ok, err, dash_id = _post_with_fallback(
            kibana,
            headers,
            auth,
            title=title,
            listing_desc=listing_desc,
            lens_panels=lens_panels,
            note_rows=note_rows,
        )
        if ok:
            path = f"/app/dashboards#/view/{quote(dash_id, safe='')}"
            print("OK", dash_id)
            print(f"{kibana.rstrip('/')}{path}")
            return 0
        last_err = err

    print(f"ERROR: Dashboards API failed after fallbacks: {last_err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
