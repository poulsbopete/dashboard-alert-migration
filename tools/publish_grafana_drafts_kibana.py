#!/usr/bin/env python3
"""
Publish workshop Grafana→Elastic *draft* JSON into Kibana.

**Primary:** **POST /api/dashboards?apiVersion=1** with **Markdown** plus **mixed Lens** panels (rotating **line**, **area**,
**bar**, **metric**, multi-series **line** with **breakdown**, and optional **AVG(workshop.requests.rate)** when the resolved
`FROM` includes metrics). The same `FROM` clause as each volume probe is reused so panels stay consistent. If mixed layouts
fail validation, the publisher falls back to **uniform line** charts only. **`WORKSHOP_SIMPLE_LENS=1`** skips mixed panels.

**Probes:** **`logs-*`**, **`metrics-*`**, workshop streams, unions, then **`traces-*`**. Override with **`WORKSHOP_ESQL_FROM`**.
PromQL in drafts is **not** executed.

**Fallback:** **saved_objects/_import** then **PUT** the same attempts. Env: **`WORKSHOP_DISABLE_LENS=1`**, **`WORKSHOP_MIN_LENS_PANELS`**
(pad short Grafana drafts so more mixed charts appear), **`WORKSHOP_MAX_LENS_PANELS`**, **`WORKSHOP_SIMPLE_LENS`**, **`WORKSHOP_ESQL_FROM`**,
**`WORKSHOP_ESQL_TIME_FIELD`** (default **`@timestamp`**).

Requires (after `source ~/.bashrc` on es3-api):
  KIBANA_URL
  ES_API_KEY  (preferred), or ES_USERNAME + ES_PASSWORD

Usage:
  python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-dashboards
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


def kibana_client() -> tuple[str, dict[str, str], Any]:
    kibana = (os.environ.get("KIBANA_URL") or "").rstrip("/")
    if not kibana:
        print("ERROR: KIBANA_URL is not set. Run: source ~/.bashrc", file=sys.stderr)
        sys.exit(1)

    api_key = (os.environ.get("ES_API_KEY") or "").strip()
    user = (os.environ.get("ES_USERNAME") or "").strip()
    password = (os.environ.get("ES_PASSWORD") or "").strip()

    headers: dict[str, str] = {"kbn-xsrf": "true", "Content-Type": "application/json"}
    auth: Any = None
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"
    elif user and password:
        auth = (user, password)
    else:
        print(
            "ERROR: Set ES_API_KEY or ES_USERNAME+ES_PASSWORD (source ~/.bashrc on the workshop VM).",
            file=sys.stderr,
        )
        sys.exit(1)
    return kibana, headers, auth


def api_headers_no_content_type(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() != "content-type"}


def fetch_core_migration_version(kibana: str, headers: dict[str, str], auth: Any) -> str:
    """Stack version string for saved-object import metadata (e.g. 9.0.0)."""
    h = api_headers_no_content_type(headers)
    try:
        r = requests.get(f"{kibana}/api/status", headers=h, auth=auth, timeout=30)
        if r.ok:
            data = r.json()
            ver = (data.get("version") or {}).get("number")
            if isinstance(ver, str) and ver.strip():
                return ver.strip()
    except (requests.RequestException, TypeError, ValueError, AttributeError):
        pass
    return "9.0.0"


def sanitize_id(stem: str) -> str:
    base = stem.replace("-elastic-draft", "").lower().replace("_", "-")
    s = re.sub(r"[^a-z0-9-]+", "-", base)
    s = re.sub(r"-+", "-", s).strip("-")[:80] or "dash"
    return f"w-grafana-{s}"


def build_description(draft: dict[str, Any]) -> str:
    parts: list[str] = []
    for pan in (draft.get("panels") or [])[:24]:
        if not isinstance(pan, dict):
            continue
        title = pan.get("title") or "panel"
        mig = pan.get("migration") or {}
        promql = mig.get("promql") or ""
        note = pan.get("note") or ""
        parts.append(f"### {title}\n\nPromQL: `{promql}`\n\n{note}")
    body = "\n\n".join(parts)
    return body[:50000]


def markdown_for_canvas(description: str) -> str:
    """Non-empty Markdown for a dashboard panel so the canvas is not blank."""
    header = """## Grafana → Elastic (import draft)

**Panels** mix **ES|QL** **line**, **area**, **bar**, **metric**, and **breakdown** charts (not PromQL). Short Grafana exports are **padded**
to **WORKSHOP_MIN_LENS_PANELS** (default **8**) up to **WORKSHOP_MAX_LENS_PANELS** (default **12**) so you see more chart types.
**Traces (no lab restart):** `cd /root/workshop && git pull && source ~/.bashrc` → **`python3 tools/seed_workshop_telemetry.py`**
(writes **traces-workshop-default**). Optionally **`export WORKSHOP_ESQL_FROM=traces-workshop-default`** (or **`traces-*`**) then re-run
**`python3 tools/publish_grafana_drafts_kibana.py`**. **WORKSHOP_SIMPLE_LENS=1** = duplicate line charts only.

---

"""
    detail = description.strip() if description.strip() else "_No per-panel PromQL was captured in this export._"
    return (header + detail)[:50000]


def dashboard_payload(title: str, description: str) -> dict[str, Any]:
    """Classic saved-object-shaped attributes (import fallback only)."""
    options = {
        "useMargins": True,
        "syncColors": False,
        "syncCursor": True,
        "syncTooltips": False,
        "hidePanelTitles": False,
    }
    search_source = {"query": {"query": "", "language": "kuery"}, "filter": []}
    return {
        "attributes": {
            "title": title[:255],
            "description": description,
            "panelsJSON": "[]",
            "optionsJSON": json.dumps(options),
            "version": 1,
            "timeRestore": False,
            "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps(search_source)},
        },
        "references": [],
    }


def dashboards_api_headers(base: dict[str, str]) -> dict[str, str]:
    h = api_headers_no_content_type(base)
    h["Content-Type"] = "application/json"
    h["Elastic-Api-Version"] = "1"
    h["X-Elastic-Internal-Origin"] = "true"
    return h


def _esql_string_literal(s: str) -> str:
    """Escape for ES|QL double-quoted string."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _plain_preview_from_markdown(md: str) -> str:
    p = re.sub(r"[_*`#]+", " ", md)
    p = " ".join(p.split())
    return (p[:2000].strip() or "Grafana migration draft — add Lens panels via Edit.")


def _min_lens_panels() -> int:
    """Pad Grafana drafts (often 2 panels) so we still emit enough Lens slots to cycle templates."""
    raw = (os.environ.get("WORKSHOP_MIN_LENS_PANELS") or "8").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 8
    return max(1, min(n, 24))


def _max_lens_panels() -> int:
    raw = (os.environ.get("WORKSHOP_MAX_LENS_PANELS") or "12").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 12
    return max(0, min(n, 24))


def _expand_draft_panels_for_lens(draft: dict[str, Any]) -> list[dict[str, Any]]:
    raw = draft.get("panels") or []
    if not isinstance(raw, list):
        raw = []
    panels: list[dict[str, Any]] = [p for p in raw if isinstance(p, dict)]
    if not panels:
        panels = [{"title": "Observability volume", "migration": {"promql": ""}}]
    min_n = _min_lens_panels()
    max_n = _max_lens_panels()
    if max_n == 0:
        return []
    target_min = min(min_n, max_n)
    k = 1
    while len(panels) < target_min:
        panels.append({"title": f"Workshop insights {k}", "migration": {"promql": ""}})
        k += 1
    return panels[:max_n]


def _esql_time_bucket_field() -> str:
    """Time column for BUCKET(); ECS default is @timestamp."""
    raw = (os.environ.get("WORKSHOP_ESQL_TIME_FIELD") or "@timestamp").strip()
    return raw if raw else "@timestamp"


def _esql_volume_probe_queries() -> list[str]:
    """
    Ordered ES|QL lines for Lens (save succeeds only when @timestamp exists on the resolved union).
    traces-* last — it often yields Unknown column [@timestamp] on Serverless when merged with logs/metrics.
    """
    override = (os.environ.get("WORKSHOP_ESQL_FROM") or "").strip()
    tf = _esql_time_bucket_field()
    if override:
        return [
            f"FROM {override} "
            f"| STATS c = COUNT(*) BY bucket = BUCKET({tf}, 75, ?_tstart, ?_tend)"
        ]
    # Try narrow workshop streams after wildcards so empty/new projects still validate once any logs exist.
    return [
        f"FROM logs-* "
        f"| STATS c = COUNT(*) BY bucket = BUCKET({tf}, 75, ?_tstart, ?_tend)",
        f"FROM metrics-* "
        f"| STATS c = COUNT(*) BY bucket = BUCKET({tf}, 75, ?_tstart, ?_tend)",
        f"FROM logs-workshop-default,metrics-workshop-default "
        f"| STATS c = COUNT(*) BY bucket = BUCKET({tf}, 75, ?_tstart, ?_tend)",
        f"FROM logs-workshop-default,metrics-workshop-default,traces-workshop-default "
        f"| STATS c = COUNT(*) BY bucket = BUCKET({tf}, 75, ?_tstart, ?_tend)",
        f"FROM logs-*,metrics-* "
        f"| STATS c = COUNT(*) BY bucket = BUCKET({tf}, 75, ?_tstart, ?_tend)",
        f"FROM logs-*,metrics-*,traces-* "
        f"| STATS c = COUNT(*) BY bucket = BUCKET({tf}, 75, ?_tstart, ?_tend)",
    ]


def _from_clause_from_probe(esql: str) -> str:
    m = re.search(r"^\s*FROM\s+(.+?)\s*\|", esql, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return "logs-*"


def _mixed_esql_templates(from_clause: str, tf: str) -> list[dict[str, Any]]:
    """Rotating panel recipes; only include log- or metrics-specific ES|QL when the FROM pattern plausibly has those fields."""
    fc = from_clause.strip()
    low = fc.lower()
    has_logs = "logs" in low
    has_metrics = "metrics" in low
    has_traces = "trace" in low
    q_vol = f"FROM {fc} | STATS c = COUNT(*) BY bucket = BUCKET({tf}, 75, ?_tstart, ?_tend)"
    tpls: list[dict[str, Any]] = [
        {
            "viz": "xy",
            "layer": "line",
            "query": q_vol,
            "x": "bucket",
            "ys": [("c", None)],
            "breakdown": None,
        },
        {
            "viz": "xy",
            "layer": "area",
            "query": q_vol,
            "x": "bucket",
            "ys": [("c", None)],
            "breakdown": None,
        },
    ]
    if has_logs:
        tpls.extend(
            [
                {
                    "viz": "xy",
                    "layer": "bar",
                    "query": (
                        f"FROM {fc} | STATS c = COUNT(*) BY code = http.response.status_code "
                        f"| SORT c DESC | LIMIT 10"
                    ),
                    "x": "code",
                    "ys": [("c", None)],
                    "breakdown": None,
                },
                {
                    "viz": "xy",
                    "layer": "bar",
                    "query": (
                        f"FROM {fc} | STATS c = COUNT(*) BY lvl = log.level | SORT c DESC | LIMIT 8"
                    ),
                    "x": "lvl",
                    "ys": [("c", None)],
                    "breakdown": None,
                },
                {
                    "viz": "xy",
                    "layer": "bar",
                    "query": (
                        f"FROM {fc} | STATS c = COUNT(*) BY h = host.name | SORT c DESC | LIMIT 8"
                    ),
                    "x": "h",
                    "ys": [("c", None)],
                    "breakdown": None,
                },
                {
                    "viz": "xy",
                    "layer": "line",
                    "query": (
                        f"FROM {fc} | STATS c = COUNT(*) BY bucket = BUCKET({tf}, 75, ?_tstart, ?_tend), "
                        f"svc = service.name"
                    ),
                    "x": "bucket",
                    "ys": [("c", None)],
                    "breakdown": "svc",
                },
            ]
        )
    if has_traces:
        tpls.append(
            {
                "viz": "xy",
                "layer": "bar",
                "query": (
                    f"FROM {fc} | STATS c = COUNT(*) BY name = span.name | SORT c DESC | LIMIT 10"
                ),
                "x": "name",
                "ys": [("c", None)],
                "breakdown": None,
            }
        )
    tpls.append(
        {
            "viz": "metric",
            "query": f"FROM {fc} | STATS total = COUNT(*)",
            "col": "total",
        }
    )
    if has_metrics:
        tpls.append(
            {
                "viz": "xy",
                "layer": "line",
                "query": (
                    f"FROM {fc} | STATS m = AVG(workshop.requests.rate) "
                    f"BY bucket = BUCKET({tf}, 75, ?_tstart, ?_tend)"
                ),
                "x": "bucket",
                "ys": [("m", None)],
                "breakdown": None,
            }
        )
    return tpls


def build_mixed_esql_panels(
    draft: dict[str, Any], *, from_clause: str, time_field: str
) -> list[dict[str, Any]]:
    """Lens panels with varied ES|QL + chart types (Path A/B richer dashboards than duplicate volume lines)."""
    if (os.environ.get("WORKSHOP_DISABLE_LENS") or "").strip() in ("1", "true", "yes"):
        return []
    if (os.environ.get("WORKSHOP_SIMPLE_LENS") or "").strip() in ("1", "true", "yes"):
        return []
    panel_rows = _expand_draft_panels_for_lens(draft)
    tf = time_field
    templates = _mixed_esql_templates(from_clause, tf)
    if not templates:
        return []
    out: list[dict[str, Any]] = []
    for i, pan in enumerate(panel_rows):
        if not isinstance(pan, dict):
            continue
        spec = templates[i % len(templates)]
        if spec["viz"] == "metric":
            out.append(
                {
                    "type": "lens",
                    "uid": str(uuid.uuid4()),
                    "config": {
                        "attributes": {
                            "type": "metric",
                            "dataset": {"type": "esql", "query": spec["query"]},
                            "metrics": [
                                {
                                    "type": "primary",
                                    "operation": "value",
                                    "column": spec["col"],
                                }
                            ],
                        }
                    },
                }
            )
            continue
        layer: dict[str, Any] = {
            "type": spec["layer"],
            "dataset": {"type": "esql", "query": spec["query"]},
            "x": {"operation": "value", "column": spec["x"]},
            "y": [],
        }
        for col, label in spec["ys"]:
            y_ent: dict[str, Any] = {"operation": "value", "column": col}
            if label:
                y_ent["label"] = label
            layer["y"].append(y_ent)
        br = spec.get("breakdown")
        if isinstance(br, str) and br.strip():
            layer["breakdown_by"] = {"operation": "value", "column": br.strip()}
        out.append(
            {
                "type": "lens",
                "uid": str(uuid.uuid4()),
                "config": {
                    "attributes": {
                        "type": "xy",
                        "layers": [layer],
                    }
                },
            }
        )
    return out


def build_esql_xy_panels(draft: dict[str, Any], *, esql_query: str) -> list[dict[str, Any]]:
    """
    Inline Lens `xy` line panels for POST/PUT /api/dashboards — must use type ``lens`` + ``config.attributes``
    (root ``type: xy`` is rejected / stripped; see kibana-dashboards skill examples).
    """
    if (os.environ.get("WORKSHOP_DISABLE_LENS") or "").strip() in ("1", "true", "yes"):
        return []
    panel_rows = _expand_draft_panels_for_lens(draft)
    out: list[dict[str, Any]] = []
    for i, pan in enumerate(panel_rows):
        if not isinstance(pan, dict):
            continue
        # Match kibana-dashboards API reference: xy + line layer only (extra keys can 400 on Serverless).
        out.append(
            {
                "type": "lens",
                "uid": str(uuid.uuid4()),
                "config": {
                    "attributes": {
                        "type": "xy",
                        "layers": [
                            {
                                "type": "line",
                                "dataset": {"type": "esql", "query": esql_query},
                                "x": {"operation": "value", "column": "bucket"},
                                "y": [{"operation": "value", "column": "c"}],
                            }
                        ],
                    }
                },
            }
        )
    return out


def _layout_note_and_data_panels(
    note_rows: list[dict[str, Any]], data_panels: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Place optional note row(s) at top; tile data panels below in two columns."""
    laid: list[dict[str, Any]] = []
    y_off = 0
    for p in note_rows:
        row = dict(p)
        g = dict(row.get("grid") or {})
        g.setdefault("x", 0)
        g["y"] = y_off
        g.setdefault("w", 48)
        g.setdefault("h", 10)
        row["grid"] = g
        laid.append(row)
        y_off += int(g.get("h") or 10)
    for i, p in enumerate(data_panels):
        row = dict(p)
        r, c = divmod(i, 2)
        row["grid"] = {
            "x": c * 24,
            "y": y_off + r * 15,
            "w": 24,
            "h": 14,
        }
        laid.append(row)
    return laid


def _note_only_fallback_panels(md: str, plain_one_line: str) -> list[tuple[str, list[dict[str, Any]]]]:
    """Legacy: full-dashboard note-only variants (no ES|QL charts)."""
    plain_esql = _esql_string_literal(plain_one_line[:500])
    q = f'ROW "{plain_esql}" AS workshop_note'
    metric_panel: dict[str, Any] = {
        "type": "lens",
        "uid": str(uuid.uuid4()),
        "grid": {"x": 0, "y": 0, "w": 48, "h": 18},
        "config": {
            "attributes": {
                "title": "",
                "type": "metric",
                "dataset": {"type": "esql", "query": q},
                "metrics": [{"type": "primary", "operation": "value", "column": "workshop_note"}],
            }
        },
    }
    return [
        (
            "markdown",
            [
                {
                    "grid": {"x": 0, "y": 0, "w": 48, "h": 28},
                    "config": {"content": md},
                    "uid": str(uuid.uuid4()),
                    "type": "markdown",
                }
            ],
        ),
        (
            "DASHBOARD_MARKDOWN",
            [
                {
                    "grid": {"x": 0, "y": 0, "w": 48, "h": 28},
                    "config": {"content": md},
                    "uid": str(uuid.uuid4()),
                    "type": "DASHBOARD_MARKDOWN",
                }
            ],
        ),
        ("metric_esql_note", [metric_panel]),
    ]


def _push_dashboards_api(
    kibana: str,
    headers: dict[str, str],
    auth: Any,
    *,
    method: str,
    dashboard_id: str | None,
    title: str,
    draft: dict[str, Any],
) -> tuple[bool, str]:
    """POST/PUT with Markdown notes + ES|QL xy probes; falls back to note-only if API rejects combo."""
    h = dashboards_api_headers(headers)
    description = build_description(draft)
    md = markdown_for_canvas(description)
    plain_preview = _plain_preview_from_markdown(md)
    base: dict[str, Any] = {
        "title": title[:255],
        "description": plain_preview[:1000] or "Grafana migration draft",
        "time_range": {"from": "now-30d", "to": "now"},
    }
    note_compact: list[tuple[str, list[dict[str, Any]]]] = [
        (
            "markdown",
            [
                {
                    "grid": {"x": 0, "y": 0, "w": 48, "h": 10},
                    "config": {"content": md},
                    "uid": str(uuid.uuid4()),
                    "type": "markdown",
                }
            ],
        ),
        (
            "DASHBOARD_MARKDOWN",
            [
                {
                    "grid": {"x": 0, "y": 0, "w": 48, "h": 10},
                    "config": {"content": md},
                    "uid": str(uuid.uuid4()),
                    "type": "DASHBOARD_MARKDOWN",
                }
            ],
        ),
        ("no_note", []),
    ]

    attempts: list[list[dict[str, Any]]] = []
    tf = _esql_time_bucket_field()
    for esql in _esql_volume_probe_queries():
        fc = _from_clause_from_probe(esql)
        mixed = build_mixed_esql_panels(draft, from_clause=fc, time_field=tf)
        if mixed:
            for _lbl, prefix in note_compact:
                attempts.append(_layout_note_and_data_panels(prefix, mixed))
            attempts.append(_layout_note_and_data_panels([], mixed))
            attempts.append(_layout_note_and_data_panels([], mixed[:1]))
        data_panels = build_esql_xy_panels(draft, esql_query=esql)
        if not data_panels:
            continue
        for _lbl, prefix in note_compact:
            attempts.append(_layout_note_and_data_panels(prefix, data_panels))
        attempts.append(_layout_note_and_data_panels([], data_panels))
        attempts.append(_layout_note_and_data_panels([], data_panels[:1]))

    last_err = ""
    for panels in attempts:
        if not panels:
            continue
        body = {**base, "panels": panels}
        if method.upper() == "POST":
            r = requests.post(
                f"{kibana}/api/dashboards?apiVersion=1",
                headers=h,
                auth=auth,
                json=body,
                timeout=180,
            )
        else:
            if not dashboard_id:
                return False, "PUT requires dashboard_id"
            rid = quote(dashboard_id, safe="")
            r = requests.put(
                f"{kibana}/api/dashboards/{rid}?apiVersion=1",
                headers=h,
                auth=auth,
                json=body,
                timeout=180,
            )
        if r.status_code in (200, 201):
            return True, ""
        last_err = f"HTTP {r.status_code} {r.text[:700]}"

    for _lbl, panels in _note_only_fallback_panels(md, plain_preview):
        body = {**base, "panels": panels}
        if method.upper() == "POST":
            r = requests.post(
                f"{kibana}/api/dashboards?apiVersion=1",
                headers=h,
                auth=auth,
                json=body,
                timeout=120,
            )
        else:
            rid = quote(dashboard_id or "", safe="")
            r = requests.put(
                f"{kibana}/api/dashboards/{rid}?apiVersion=1",
                headers=h,
                auth=auth,
                json=body,
                timeout=120,
            )
        if r.status_code in (200, 201):
            return True, ""
        last_err = f"HTTP {r.status_code} {r.text[:700]}"
    return False, last_err


def publish_one_dashboards_api(
    kibana: str,
    headers: dict[str, str],
    auth: Any,
    title: str,
    draft: dict[str, Any],
) -> tuple[bool, str]:
    """Create a dashboard via POST /api/dashboards?apiVersion=1 (notes + ES|QL xy probes)."""
    return _push_dashboards_api(
        kibana, headers, auth, method="POST", dashboard_id=None, title=title, draft=draft
    )


def put_dashboard_markdown_canvas(
    kibana: str,
    headers: dict[str, str],
    auth: Any,
    dashboard_id: str,
    title: str,
    draft: dict[str, Any],
) -> tuple[bool, str]:
    """Replace dashboard contents after saved-object import (notes + ES|QL probes)."""
    return _push_dashboards_api(
        kibana,
        headers,
        auth,
        method="PUT",
        dashboard_id=dashboard_id,
        title=title,
        draft=draft,
    )


def saved_object_minimal_import_line(
    dash_id: str, body: dict[str, Any], core_migration_version: str
) -> dict[str, Any]:
    """Minimal NDJSON line—avoids typeMigrationVersion / controlGroupInput / namespaces (common 500 causes)."""
    return {
        "type": "dashboard",
        "id": dash_id,
        "attributes": dict(body["attributes"]),
        "references": body.get("references") or [],
        "coreMigrationVersion": core_migration_version,
    }


def import_one_ndjson(
    kibana: str,
    headers: dict[str, str],
    auth: Any,
    record: dict[str, Any],
) -> tuple[bool, str, str | None]:
    """Returns (ok, error_message, dashboard_id_for_api) — id may be None if response omits it."""
    h = api_headers_no_content_type(headers)
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
    r = requests.post(
        f"{kibana}/api/saved_objects/_import",
        params={"overwrite": "true", "compatibilityMode": "true"},
        headers=h,
        auth=auth,
        files={"file": ("one.ndjson", line.encode("utf-8"), "application/ndjson")},
        timeout=120,
    )
    if r.status_code not in (200, 201):
        return False, f"HTTP {r.status_code} {r.text[:600]}", None
    try:
        payload = r.json()
    except json.JSONDecodeError:
        return False, "non-JSON import response", None
    errs = payload.get("errors") or []
    if errs:
        return False, str(errs[0])[:600], None
    if payload.get("success") is False and int(payload.get("successCount") or 0) < 1:
        return False, str(payload)[:600], None
    imp_id: str | None = None
    for row in payload.get("successResults") or []:
        if row.get("type") == "dashboard":
            imp_id = str(row.get("id") or row.get("destinationId") or "") or None
            break
    return True, "", imp_id


def main() -> int:
    ap = argparse.ArgumentParser(description="Create Kibana dashboards from Grafana migration drafts via HTTP API.")
    ap.add_argument("--drafts-dir", type=Path, default=Path("build/elastic-dashboards"))
    args = ap.parse_args()
    drafts_dir: Path = args.drafts_dir

    if not drafts_dir.is_dir():
        print(f"ERROR: drafts dir missing: {drafts_dir}", file=sys.stderr)
        return 1

    files = sorted(drafts_dir.glob("*-elastic-draft.json"))
    if not files:
        print(f"ERROR: no *-elastic-draft.json under {drafts_dir}", file=sys.stderr)
        return 1

    kibana, headers, auth = kibana_client()
    core_ver = fetch_core_migration_version(kibana, headers, auth)

    ok = 0
    failed: list[str] = []
    for path in files:
        draft = json.loads(path.read_text(encoding="utf-8"))
        title = str(draft.get("title") or path.stem)
        desc = build_description(draft)
        dash_id = sanitize_id(path.stem)
        body = dashboard_payload(title, desc)

        try:
            good, err_dash = publish_one_dashboards_api(kibana, headers, auth, title, draft)
        except requests.RequestException as e:
            good, err_dash = False, str(e)

        if good:
            ok += 1
            print("OK", dash_id, title[:70])
            continue

        print(
            "WARN",
            dash_id,
            "Dashboards API (Lens) failed — import fallback; stderr tail:",
            err_dash[:500],
            file=sys.stderr,
        )

        rec = saved_object_minimal_import_line(dash_id, body, core_ver)
        try:
            good_imp, err_imp, imported_id = import_one_ndjson(kibana, headers, auth, rec)
        except requests.RequestException as e:
            good_imp, err_imp, imported_id = False, str(e), None

        if good_imp:
            api_id = imported_id or dash_id
            hg, herr = put_dashboard_markdown_canvas(kibana, headers, auth, api_id, title, draft)
            if hg:
                print("OK", dash_id, title[:70], "(fallback: import + Dashboards API panels)")
            else:
                print(
                    "OK",
                    dash_id,
                    title[:70],
                    "(fallback: import only; Dashboards PUT failed — canvas may be blank)",
                    file=sys.stderr,
                )
                print("  ", herr[:200], file=sys.stderr)
            ok += 1
            continue

        failed.append(f"{path.name}: Dashboards API: {err_dash} | import: {err_imp}")
        print("FAIL", dash_id, file=sys.stderr)

    print(f"\nPublished {ok}/{len(files)} dashboards to Kibana.")
    if failed:
        print("\nFailures:", file=sys.stderr)
        for msg in failed[:12]:
            print(f"  {msg}", file=sys.stderr)
        if len(failed) > 12:
            print(f"  ... and {len(failed) - 12} more", file=sys.stderr)
        return 1

    if ok == len(files):
        marker = Path("build/.published_grafana_to_kibana_ok")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"count": ok, "drafts": len(files)}), encoding="utf-8")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
