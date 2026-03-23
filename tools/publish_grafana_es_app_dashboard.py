#!/usr/bin/env python3
"""
Publish a Grafana **app platform** dashboard (apiVersion dashboard.grafana.app/v2beta1) whose panels use the
**Elasticsearch** datasource into **Kibana Serverless** via **POST /api/dashboards?apiVersion=1**.

Grafana Lucene/Kibana query strings and aggregation JSON are **best-effort** translated into **ES|QL** for Lens.
Validate field names against your index mapping (`metrics-*`, `logs-*`); override index with **`GRAFANA_IMPORT_FROM`**.

Requires (same as workshop publisher):
  KIBANA_URL
  ES_API_KEY  (or ES_USERNAME + ES_PASSWORD)

Usage:
  # Save the Grafana JSON export to a file, then:
  python3 tools/publish_grafana_es_app_dashboard.py --input ./prom-demo.app-v2.json

Optional:
  --title "Override dashboard title"
  GRAFANA_IMPORT_FROM=metrics-*   # default; use logs-* if panels are log-only
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.publish_grafana_drafts_kibana import (
    _esql_bucket_expr,
    _esql_time_bucket_field,
    _lens_from_spec,
    _spec_xy,
    dashboards_api_headers,
    kibana_client,
)


def _ident(field: str) -> str:
    n = (field or "").strip().replace("`", "")
    if not n:
        return "`@timestamp`"
    return f"`{n}`"


def _lucene_to_where(lucene: str) -> str:
    """Very small Lucene → ES|QL WHERE fragment (field:value AND …)."""
    q = (lucene or "").strip()
    if not q:
        return ""
    parts: list[str] = []
    for segment in re.split(r"\s+AND\s+", q, flags=re.IGNORECASE):
        segment = segment.strip()
        if not segment:
            continue
        m = re.match(r"^([\w.]+):(.+)$", segment)
        if not m:
            continue
        field, val = m.group(1), m.group(2).strip()
        f = _ident(field)
        if val == "*":
            parts.append(f"{f} IS NOT NULL")
        elif val.startswith('"') and val.endswith('"'):
            parts.append(f'{f} == {val}')
        else:
            parts.append(f'{f} == "{val}"')
    if not parts:
        return ""
    return " | WHERE " + " AND ".join(parts)


def _first_es_query(panel_spec: dict[str, Any]) -> dict[str, Any] | None:
    data = panel_spec.get("data") or {}
    qg = data.get("spec") or {}
    queries = qg.get("queries") or []
    for q in queries:
        if not isinstance(q, dict):
            continue
        inner = (q.get("spec") or {}).get("query") or {}
        if str(inner.get("group") or "").lower() != "elasticsearch":
            continue
        spec = inner.get("spec")
        if isinstance(spec, dict):
            return spec
    return None


def _split_aggs(bucket_aggs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    terms = [a for a in bucket_aggs if a.get("type") == "terms"]
    dhs = [a for a in bucket_aggs if a.get("type") == "date_histogram"]
    return terms, dhs[0] if dhs else None


def _metric_primary(metrics: list[dict[str, Any]]) -> dict[str, Any] | None:
    for m in metrics:
        if isinstance(m, dict) and m.get("type") not in (None, "raw_data"):
            return m
    return None


def _viz_kind(panel_spec: dict[str, Any]) -> str:
    vc = panel_spec.get("vizConfig") or {}
    return str(vc.get("group") or "timeseries")


def _draw_style(panel_spec: dict[str, Any]) -> str:
    try:
        d = (
            (panel_spec.get("vizConfig") or {})
            .get("spec", {})
            .get("fieldConfig", {})
            .get("defaults", {})
            .get("custom", {})
            .get("drawStyle")
        )
        return str(d or "line")
    except (TypeError, AttributeError):
        return "line"


def esql_for_grafana_es_panel(
    title: str,
    es_spec: dict[str, Any],
    *,
    viz: str,
    draw: str,
    default_from: str,
) -> tuple[dict[str, Any] | None, str]:
    """
    Returns (spec dict for _lens_from_spec, error_reason) or (None, reason).
    """
    lucene = str(es_spec.get("query") or "")
    time_field = str(es_spec.get("timeField") or "@timestamp")
    tf = time_field if time_field == _esql_time_bucket_field() else time_field
    bucket_aggs = es_spec.get("bucketAggs") or []
    if not isinstance(bucket_aggs, list):
        bucket_aggs = []
    metrics = es_spec.get("metrics") or []
    if not isinstance(metrics, list):
        metrics = []

    terms_aggs, dh = _split_aggs(bucket_aggs)
    pm = _metric_primary(metrics)
    if not pm:
        return None, "no primary metric"

    mtype = str(pm.get("type") or "")
    mfield = str(pm.get("field") or "")

    where = _lucene_to_where(lucene)
    from_clause = default_from
    if mtype == "logs":
        from_clause = "logs-*"
    q_b = _esql_bucket_expr(tf)

    # --- Stat single-number style (date_histogram + cardinality/sum often used for gauge) ---
    if viz == "stat" and dh and mtype == "cardinality" and mfield:
        fq = _ident(mfield)
        esql = f"FROM {from_clause}{where} | STATS c = COUNT_DISTINCT({fq})"
        return (
            {
                "viz": "metric",
                "query": esql,
                "col": "c",
                "lens_title": title[:240],
            },
            "",
        )

    if viz == "stat" and dh and mtype == "max" and mfield == "@timestamp":
        esql = f"FROM {from_clause}{where} | STATS c = MAX({_ident(time_field)})"
        return {"viz": "metric", "query": esql, "col": "c", "lens_title": title[:240]}, ""

    # --- Table: terms + multiple metrics ---
    if viz == "table" and terms_aggs:
        t0 = terms_aggs[0]
        key_field = str((t0.get("field") or ""))
        if not key_field:
            return None, "table missing terms field"
        key = _ident(key_field)
        stats_parts: list[str] = []
        for m in metrics:
            if not isinstance(m, dict):
                continue
            mt = str(m.get("type") or "")
            mf = str(m.get("field") or "")
            mid = str(m.get("id") or "")
            if mt == "cardinality" and mf:
                stats_parts.append(f"pods = COUNT_DISTINCT({_ident(mf)})")
            elif mt == "min" and mf:
                stats_parts.append(f"first_seen = MIN({_ident(mf)})")
            elif mt == "max" and mf:
                stats_parts.append(f"last_seen = MAX({_ident(mf)})")
        if not stats_parts:
            return None, "table: no supported metrics"
        sort_col = "pods" if any("pods =" in p for p in stats_parts) else stats_parts[0].split("=")[0].strip()
        esql = (
            f"FROM {from_clause}{where} | STATS {', '.join(stats_parts)} BY dep = {key} "
            f"| SORT {sort_col} DESC NULLS LAST | LIMIT 25"
        )
        return (
            {
                "viz": "xy",
                "layer": "bar",
                "query": esql,
                "x": "dep",
                "ys": [("pods", "pods")],
                "breakdown": None,
                "lens_title": title[:240],
            },
            "",
        )

    # --- Pie / donut → horizontal bar top-N ---
    if viz == "piechart" and terms_aggs:
        t0 = terms_aggs[0]
        key_field = str((t0.get("field") or ""))
        if not key_field or mtype != "cardinality" or not mfield:
            return None, "pie: need terms + cardinality"
        key = _ident(key_field)
        fq = _ident(mfield)
        esql = (
            f"FROM {from_clause}{where} | STATS c = COUNT_DISTINCT({fq}) BY b = {key} "
            f"| SORT c DESC | LIMIT 12"
        )
        return (
            {
                "viz": "xy",
                "layer": "bar",
                "query": esql,
                "x": "b",
                "ys": [("c", None)],
                "breakdown": None,
                "lens_title": title[:240],
            },
            "",
        )

    # --- Time series ---
    if not dh:
        return None, "no date_histogram"

    if mtype == "logs":
        esql = f"FROM logs-*{where} | STATS c = COUNT(*) BY bucket = {q_b}"
        layer = "bar" if draw == "bars" else "line"
        return (
            {
                "viz": "xy",
                "layer": layer,
                "query": esql,
                "x": "bucket",
                "ys": [("c", None)],
                "breakdown": None,
                "lens_title": title[:240],
            },
            "",
        )

    if mtype == "sum" and mfield:
        mf = _ident(mfield)
        if terms_aggs:
            key = _ident(str(terms_aggs[0].get("field") or "service.name"))
            esql = (
                f"FROM {from_clause}{where} | STATS m = SUM({mf}) BY bucket = {q_b}, br = {key}"
            )
            return (
                {
                    "viz": "xy",
                    "layer": "bar" if draw == "bars" else "line",
                    "query": esql,
                    "x": "bucket",
                    "ys": [("m", None)],
                    "breakdown": "br",
                    "lens_title": title[:240],
                },
                "",
            )
        esql = f"FROM {from_clause}{where} | STATS m = SUM({mf}) BY bucket = {q_b}"
        return (
            {
                "viz": "xy",
                "layer": "line",
                "query": esql,
                "x": "bucket",
                "ys": [("m", None)],
                "breakdown": None,
                "lens_title": title[:240],
            },
            "",
        )

    if mtype == "cardinality" and mfield:
        fq = _ident(mfield)
        if terms_aggs:
            key = _ident(str(terms_aggs[0].get("field") or "service.name"))
            esql = (
                f"FROM {from_clause}{where} | STATS m = COUNT_DISTINCT({fq}) BY bucket = {q_b}, br = {key}"
            )
            layer = "bar" if draw == "bars" else "line"
            return (
                {
                    "viz": "xy",
                    "layer": layer,
                    "query": esql,
                    "x": "bucket",
                    "ys": [("m", None)],
                    "breakdown": "br",
                    "lens_title": title[:240],
                },
                "",
            )
        esql = f"FROM {from_clause}{where} | STATS m = COUNT_DISTINCT({fq}) BY bucket = {q_b}"
        return (
            {
                "viz": "xy",
                "layer": "line",
                "query": esql,
                "x": "bucket",
                "ys": [("m", None)],
                "breakdown": None,
                "lens_title": title[:240],
            },
            "",
        )

    if mtype in ("avg", "max", "min") and mfield:
        mf = _ident(mfield)
        op = mtype.upper()
        if terms_aggs:
            key = _ident(str(terms_aggs[0].get("field") or "service.name"))
            esql = (
                f"FROM {from_clause}{where} | STATS m = {op}({mf}) BY bucket = {q_b}, br = {key}"
            )
            return (
                {
                    "viz": "xy",
                    "layer": "bar" if draw == "bars" else "line",
                    "query": esql,
                    "x": "bucket",
                    "ys": [("m", None)],
                    "breakdown": "br",
                    "lens_title": title[:240],
                },
                "",
            )
        esql = f"FROM {from_clause}{where} | STATS m = {op}({mf}) BY bucket = {q_b}"
        return (
            {
                "viz": "xy",
                "layer": "line",
                "query": esql,
                "x": "bucket",
                "ys": [("m", None)],
                "breakdown": None,
                "lens_title": title[:240],
            },
            "",
        )

    return None, f"unsupported metric/layout combo (type={mtype})"


def iter_panels_in_layout_order(doc: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    spec = doc.get("spec") or {}
    elements = spec.get("elements") or {}
    layout = ((spec.get("layout") or {}).get("spec") or {}).get("items") or []
    out: list[tuple[str, dict[str, Any], int, int]] = []
    for item in layout:
        if not isinstance(item, dict):
            continue
        sp = item.get("spec") or {}
        ref = (sp.get("element") or {}).get("name") or ""
        if not ref or ref not in elements:
            continue
        el = elements[ref]
        if not isinstance(el, dict) or str(el.get("kind")) != "Panel":
            continue
        pspec = el.get("spec") or {}
        title = str(pspec.get("title") or ref)
        x = int(sp.get("x") or 0)
        y = int(sp.get("y") or 0)
        out.append((title, pspec, y, x))
    out.sort(key=lambda t: (t[2], t[3]))
    return [(t[0], t[1]) for t in out]


def grafana_grid_to_kibana(sp: dict[str, Any]) -> dict[str, int]:
    """Grafana layout uses 24-wide grid; Kibana API examples use 48-wide."""
    return {
        "x": int(sp.get("x") or 0) * 2,
        "y": int(sp.get("y") or 0) * 2,
        "w": int(sp.get("width") or 12) * 2,
        "h": int(sp.get("height") or 8) * 2,
    }


def build_dashboard(doc: dict[str, Any], *, title_override: str | None, default_from: str) -> dict[str, Any]:
    meta = doc.get("metadata") or {}
    spec = doc.get("spec") or {}
    base_title = title_override or str(spec.get("title") or meta.get("name") or "Grafana ES import")
    uid = str(meta.get("uid") or "")

    md = (
        f"## Grafana → Kibana (Elasticsearch panels)\n\n"
        f"Imported from **Grafana app** dashboard `{meta.get('name', '')}`"
        f"{f' (`uid={uid}`)' if uid else ''}.\n\n"
        f"Panels were translated **best-effort** from Grafana Elasticsearch queries to **ES|QL**. "
        f"If a chart errors, fix field names or index (`GRAFANA_IMPORT_FROM`, currently **`{default_from}`**) "
        f"to match your **metrics-*** / **logs-*** mapping.\n"
    )

    note = {
        "type": "markdown",
        "uid": str(uuid.uuid4()),
        "grid": {"x": 0, "y": 0, "w": 48, "h": 10},
        "config": {"content": md[:50000]},
    }

    panels: list[dict[str, Any]] = [note]
    y_cursor = 10

    for panel_title, pspec in iter_panels_in_layout_order(doc):
        es_spec = _first_es_query(pspec)
        if not es_spec:
            continue
        viz = _viz_kind(pspec)
        draw = _draw_style(pspec)
        spec_dict, err = esql_for_grafana_es_panel(
            panel_title,
            es_spec,
            viz=viz,
            draw=draw,
            default_from=default_from,
        )
        if not spec_dict:
            fallback = (
                f'ROW "{panel_title}: could not map ({err})" AS workshop_note'
            )
            spec_dict = {
                "viz": "metric",
                "query": fallback,
                "col": "workshop_note",
                "lens_title": panel_title[:240],
            }
        if spec_dict["viz"] == "metric":
            lens = _lens_from_spec(
                {
                    "viz": "metric",
                    "query": spec_dict["query"],
                    "col": spec_dict["col"],
                    "lens_title": spec_dict["lens_title"],
                }
            )
        else:
            lens = _lens_from_spec(
                _spec_xy(
                    default_from,
                    _esql_time_bucket_field(),
                    layer=spec_dict["layer"],
                    query=spec_dict["query"],
                    x=spec_dict["x"],
                    ys=spec_dict["ys"],
                    breakdown=spec_dict.get("breakdown"),
                    lens_title=spec_dict["lens_title"],
                )
            )
        # Re-find layout item for this panel title / order — match by iterating layout again
        panels.append(lens)

    # Apply grid: two columns below note
    idx = 0
    for i, p in enumerate(panels):
        if i == 0:
            continue
        r, c = divmod(idx, 2)
        p["grid"] = {"x": c * 24, "y": y_cursor + r * 16, "w": 24, "h": 14}
        idx += 1

    ts = spec.get("timeSettings") or {}
    return {
        "title": base_title[:255],
        "description": "Grafana app v2 dashboard — Elasticsearch datasource → ES|QL Lens",
        "time_range": {
            "from": str(ts.get("from") or "now-30d"),
            "to": str(ts.get("to") or "now"),
        },
        "panels": panels,
    }


def post_dashboard(body: dict[str, Any]) -> tuple[bool, str, str | None]:
    kibana, headers, auth = kibana_client()
    h = dashboards_api_headers(headers)
    r = requests.post(
        f"{kibana}/api/dashboards?apiVersion=1",
        headers=h,
        auth=auth,
        json=body,
        timeout=180,
    )
    if r.status_code not in (200, 201):
        return False, f"HTTP {r.status_code} {r.text[:1200]}", None
    try:
        data = r.json()
    except json.JSONDecodeError:
        return True, "", None
    did = data.get("id") or (data.get("data") or {}).get("id")
    return True, "", str(did) if did else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Import Grafana app v2 Elasticsearch dashboards into Kibana.")
    ap.add_argument("--input", type=Path, required=True, help="Path to Grafana app dashboard JSON")
    ap.add_argument("--title", type=str, default="", help="Override Kibana dashboard title")
    ap.add_argument("--dry-run", action="store_true", help="Print panel count and exit")
    args = ap.parse_args()

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    default_from = (os.environ.get("GRAFANA_IMPORT_FROM") or "metrics-*").strip() or "metrics-*"

    body = build_dashboard(
        raw,
        title_override=(args.title.strip() or None),
        default_from=default_from,
    )
    if args.dry_run:
        print(f"panels: {len(body['panels'])} title={body['title']!r}")
        return 0

    ok, err, did = post_dashboard(body)
    if not ok:
        print(err, file=sys.stderr)
        return 1
    kibana, _, _ = kibana_client()
    print(f"OK: dashboard id={did!r} title={body['title']!r}")
    if did:
        print(f"Open: {kibana}/app/dashboards#/view/{quote(str(did), safe='')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
