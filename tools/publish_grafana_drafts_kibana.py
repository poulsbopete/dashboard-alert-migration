#!/usr/bin/env python3
"""
Publish workshop Grafana→Elastic or Datadog→Elastic *draft* JSON into Kibana.

**Primary:** **POST /api/dashboards?apiVersion=1** with **Markdown** plus **mixed Lens** panels: each widget’s **ES|QL** is
chosen from that panel’s **PromQL or Datadog query string + title** (e.g. Go/GC → OTLP **system.cpu.utilization** / **http.server.request.count**, HTTP → **http.server.request.count** by **service.name** (or **`WORKSHOP_ESQL_HTTP_STATUS_COLUMN`** when set), latency
→ **http.server.request.duration** or APM transactions). Type-specific panels use **narrow** ``FROM`` targets (**``metrics-*``**, **``logs-*``**, **``traces-*``**) so **logs|metrics** unions do not trip ES|QL verification. Padded “extra” panels still **vary** by index. If mixed layouts fail validation, **uniform line** fallback still shows **per-panel titles**.
**`WORKSHOP_SIMPLE_LENS=1`** skips mixed panels.

**Probes:** **`logs-*`**, **`metrics-*`**, workshop streams, unions, then **`traces-*`**. Override with **`WORKSHOP_ESQL_FROM`**.
PromQL in drafts is **not** executed.

**Fallback:** **saved_objects/_import** then **PUT** the same attempts. Env: **`WORKSHOP_DISABLE_LENS=1`**, **`WORKSHOP_MIN_LENS_PANELS`**
(pad short Grafana drafts so more mixed charts appear), **`WORKSHOP_MAX_LENS_PANELS`**, **`WORKSHOP_SIMPLE_LENS`**, **`WORKSHOP_ESQL_FROM`**,
**`WORKSHOP_ESQL_TIME_FIELD`** (default **`@timestamp`**).
**`WORKSHOP_ESQL_HTTP_STATUS_COLUMN`** — optional ES|QL column for HTTP status bars (e.g. **`http.response.status_code`**). If unset, HTTP panels use **request volume by `service.name`** (avoids **Unknown column [attributes.http.…]** on some Serverless mappings).
**`WORKSHOP_ESQL_HTTP_ROUTE_COLUMN`** — optional (default **`http.route`**) for route breakdown panels on **metrics-***.

Requires (after `source ~/.bashrc` on es3-api):
  KIBANA_URL
  ES_API_KEY  (preferred), or ES_USERNAME + ES_PASSWORD

Usage:
  python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-dashboards
  python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-datadog-dashboards
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


def _migration_source_query(mig: dict[str, Any]) -> str:
    """Grafana drafts use migration.promql; Datadog drafts use migration.datadog_query."""
    if not isinstance(mig, dict):
        return ""
    return str(mig.get("promql") or mig.get("datadog_query") or "").strip()


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
        src = _migration_source_query(mig)
        note = pan.get("note") or ""
        if (mig.get("datadog_query") or "").strip() and not (mig.get("promql") or "").strip():
            qline = f"Datadog: `{src}`" if src else "Datadog: _(no query)_"
        else:
            qline = f"PromQL: `{src}`" if src else "PromQL: _(none)_"
        parts.append(f"### {title}\n\n{qline}\n\n{note}")
    body = "\n\n".join(parts)
    return body[:50000]


def _short_listing_description(draft: dict[str, Any], title: str) -> str:
    """Kibana dashboard list subtitle — unique per import (avoid identical blobs under every title)."""
    lines: list[str] = []
    panels = draft.get("panels") or []
    if isinstance(panels, list):
        for pan in panels[:5]:
            if not isinstance(pan, dict):
                continue
            mig = pan.get("migration") or {}
            pq = _migration_source_query(mig)
            ptitle = (pan.get("title") or "").strip()
            if pq:
                lines.append(pq[:110] + ("…" if len(pq) > 110 else ""))
            elif ptitle:
                lines.append(ptitle[:72])
    tags = draft.get("tags") or []
    is_dd = isinstance(tags, list) and any(
        isinstance(t, str) and "datadog-dashboard" in t.lower() for t in tags
    )
    prefix = "Datadog→Elastic — " if is_dd else "Grafana→Elastic — "
    if lines:
        return (prefix + " · ".join(lines[:2]))[:300]
    return (prefix + (title.strip() or "import draft"))[:300]


def markdown_for_canvas(detail: str, *, dashboard_title: str) -> str:
    """Compact Markdown panel: unique title line + rotating one-liner; full PromQL detail below."""
    tips = (
        "Lens panels use **ES|QL**; PromQL below is the Grafana source for migration.",
        "Use **Edit** to swap queries. Publisher options (**WORKSHOP_***) are in the repo **README**.",
        "Live data: **`./scripts/start_workshop_otel.sh`** on the workshop VM (OTLP → mOTLP).",
        "Force a data pattern: **`export WORKSHOP_ESQL_FROM=…`** then re-run **`publish_grafana_drafts_kibana.py`**.",
        "Many charts? Short Grafana JSON is padded — **`WORKSHOP_MIN_LENS_PANELS`** / **`WORKSHOP_MAX_LENS_PANELS`** in README.",
        "Duplicate lines only: **`WORKSHOP_SIMPLE_LENS=1`** when debugging.",
        "Community JSON: **assignment B5b** — same **`grafana_to_elastic.py`** pipeline.",
        "Path A parity: mixed Lens types match **`migrate_grafana_dashboards_to_serverless.sh`** output.",
    )
    idx = sum(ord(c) for c in dashboard_title) % len(tips)
    tip = tips[idx]
    is_dd = "datadog" in dashboard_title.lower()
    ttl = (dashboard_title.strip() or ("Datadog import draft" if is_dd else "Grafana import draft")).replace("\n", " ")[:200]
    header = f"## {'Datadog' if is_dd else 'Grafana'} → Elastic\n\n**{ttl}** — {tip}\n\n---\n\n"
    body = (
        detail.strip()
        if detail.strip()
        else (
            "_No per-panel source queries were captured in this export._"
            if is_dd
            else "_No per-panel PromQL was captured in this export._"
        )
    )
    return (header + body)[:50000]


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


def _esql_ident(name: str) -> str:
    """Quote a possibly dotted field name for ES|QL."""
    n = (name or "").strip()
    if not n:
        return "`service.name`"
    if n.startswith("`") and n.endswith("`"):
        return n
    return f"`{n.replace('`', '')}`"


def _esql_http_status_column() -> str | None:
    """
    When set, GROUP BY this column for HTTP status–style Lens bars.
    Native mOTLP metrics often do not expose ``attributes.http.response.status_code`` as an ES|QL column
    (mapping uses ECS top-level fields or omits status on aggregates).
    """
    raw = (os.environ.get("WORKSHOP_ESQL_HTTP_STATUS_COLUMN") or "").strip()
    return raw if raw else None


def _esql_http_route_column() -> str:
    """Metric attribute / ECS field for HTTP route bars (OTel: http.route)."""
    raw = (os.environ.get("WORKSHOP_ESQL_HTTP_ROUTE_COLUMN") or "http.route").strip()
    return raw if raw else "http.route"


def _esql_service_name_column() -> str:
    """Service dimension on metrics (OTel resource → often service.name)."""
    raw = (os.environ.get("WORKSHOP_ESQL_SERVICE_NAME_COLUMN") or "service.name").strip()
    return raw if raw else "service.name"


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


def _from_capabilities(fc: str) -> dict[str, bool]:
    low = fc.lower()
    return {"logs": "logs" in low, "metrics": "metrics" in low, "traces": "trace" in low}


def _truncate_lens_title(panel_title: str, promql: str, *, max_len: int = 118) -> str:
    pt = (panel_title or "").strip().replace("\n", " ") or "Grafana panel"
    base = pt[:72]
    if promql and len(promql.strip()) > 0:
        pq = promql.strip().replace("\n", " ")
        if len(pq) > 55:
            pq = pq[:52] + "…"
        s = f"{base} — {pq}"
    else:
        s = base
    return s[:max_len]


def _classify_grafana_panel(promql: str, panel_title: str) -> str:
    """Coarse bucket from PromQL + title so each dashboard gets panel-appropriate ES|QL (workshop data)."""
    s = f"{promql} {panel_title}".lower()
    if re.search(r"go_gc|gc_duration|memstats|goroutines?|go_mem|process_cpu|runtime\.mem", s):
        return "go_runtime"
    if re.search(r"histogram_quantile|_bucket\b|quantile|p9[05]|p99|latency|duration_second", s):
        return "latency"
    if re.search(r"operation_errors", s):
        return "operation_errors"
    if re.search(r"\bentity_id\b", s):
        if re.search(r"histogram|quantile|duration_second|_bucket", s):
            return "by_entity_latency"
        return "by_entity"
    if re.search(r"http_|http\.|requests_total|status_code|5xx|4xx|response_code", s):
        return "http"
    if re.search(r"\berror\b|exception|failed|failures|5[0-9]{2}\b", s) and "http" not in s[:80]:
        return "errors"
    if re.search(r"node_cpu|container_cpu|cpu_usage|cpu\.usage", s):
        return "cpu"
    if re.search(r"memory|mem_usage|heap|working_set|ram\b", s):
        return "memory"
    if re.search(r"disk|filesystem|pvc_|volume_|iops|io_", s):
        return "storage"
    if re.search(r"kube_|k8s|pod_|namespace_|container_", s):
        return "k8s"
    if re.search(r"mysql|postgres|redis|mongo|db_|jdbc|sql_", s):
        return "db"
    if re.search(r"probe_success|^up\b|scrape_duration|targets?$", s):
        return "scrape"
    if re.search(r"network|tcp_|bandwidth|transmit|receive", s):
        return "network"
    return "generic"


def _spec_xy(
    fc: str,
    tf: str,
    *,
    layer: str,
    query: str,
    x: str,
    ys: list[tuple[str, str | None]],
    breakdown: str | None,
    lens_title: str,
) -> dict[str, Any]:
    return {
        "viz": "xy",
        "layer": layer,
        "query": query,
        "x": x,
        "ys": ys,
        "breakdown": breakdown,
        "lens_title": lens_title,
    }


def _spec_metric(fc: str, query: str, col: str, lens_title: str) -> dict[str, Any]:
    return {"viz": "metric", "query": query, "col": col, "lens_title": lens_title}


def _panel_esql_spec(
    pan: dict[str, Any],
    *,
    from_clause: str,
    tf: str,
    panel_index: int,
    cap: dict[str, bool],
) -> dict[str, Any]:
    """Pick one Lens recipe from this Grafana panel’s PromQL/title + resolved FROM capabilities."""
    fc = from_clause.strip()
    pq = _migration_source_query(pan.get("migration") or {})
    ptitle = str(pan.get("title") or "")
    cat = _classify_grafana_panel(pq, ptitle)
    lt = _truncate_lens_title(ptitle, pq)
    q_b = f"BUCKET({tf}, 75, ?_tstart, ?_tend)"

    def vol_line(layer: str) -> dict[str, Any]:
        return _spec_xy(
            fc,
            tf,
            layer=layer,
            query=f"FROM {fc} | STATS c = COUNT(*) BY bucket = {q_b}",
            x="bucket",
            ys=[("c", None)],
            breakdown=None,
            lens_title=lt,
        )

    def vol_area() -> dict[str, Any]:
        return vol_line("area")

    # --- category-specific (OTLP-backed logs/metrics/traces probes) ---
    if cat == "go_runtime":
        if cap["metrics"]:
            if panel_index % 2 == 0:
                return _spec_xy(
                    "metrics-*",
                    tf,
                    layer="line",
                    query=(
                        f"FROM metrics-* | STATS m = AVG(`system.cpu.utilization`) "
                        f"BY bucket = {q_b}"
                    ),
                    x="bucket",
                    ys=[("m", None)],
                    breakdown=None,
                    lens_title=f"{lt} (CPU utilization — OTLP fleet gauge)",
                )
            return _spec_xy(
                "metrics-*",
                tf,
                layer="line",
                query=(
                    f"FROM metrics-* | STATS c = SUM(`http.server.request.count`) "
                    f"BY bucket = {q_b}"
                ),
                x="bucket",
                ys=[("c", None)],
                breakdown=None,
                lens_title=f"{lt} (HTTP request count — workshop proxy for Go/runtime)",
            )
        if cap["logs"]:
            return _spec_xy(
                "logs-*",
                tf,
                layer="line",
                query=(
                    f"FROM logs-* | STATS c = COUNT(*) BY bucket = {q_b}, svc = service.name"
                ),
                x="bucket",
                ys=[("c", None)],
                breakdown="svc",
                lens_title=f"{lt} (events by service — proxy)",
            )

    if cat == "latency":
        # Narrow indices: unions break when processor.event / histogram fields exist on one side only.
        if cap["traces"] and not cap["logs"]:
            return _spec_xy(
                "traces-*",
                tf,
                layer="line",
                query=(
                    f'FROM traces-* | WHERE processor.event == "transaction" '
                    f"| STATS m = AVG(transaction.duration.us) BY bucket = {q_b}"
                ),
                x="bucket",
                ys=[("m", None)],
                breakdown=None,
                lens_title=f"{lt} (avg txn duration µs)",
            )
        if cap["metrics"]:
            return _spec_xy(
                "metrics-*",
                tf,
                layer="line",
                query=(
                    f"FROM metrics-* | STATS m = AVG(`http.server.request.duration`) "
                    f"BY bucket = {q_b}"
                ),
                x="bucket",
                ys=[("m", None)],
                breakdown=None,
                lens_title=f"{lt} (avg HTTP duration — latency proxy)",
            )

    if cat == "http":
        # mOTLP metric mappings vary: attributes.http.response.status_code often does not exist as a column.
        # Default: SUM(http.server.request.count) BY service — matches workshop OTLP; optional status column via env.
        status_src = _esql_http_status_column()
        svc = _esql_ident(_esql_service_name_column())
        if cap["metrics"]:
            if status_src:
                st = _esql_ident(status_src)
                return _spec_xy(
                    "metrics-*",
                    tf,
                    layer="bar",
                    query=(
                        f"FROM metrics-* | STATS c = SUM(`http.server.request.count`) BY code = {st} "
                        f"| SORT c DESC | LIMIT 12"
                    ),
                    x="code",
                    ys=[("c", None)],
                    breakdown=None,
                    lens_title=f"{lt} (HTTP requests by status)",
                )
            return _spec_xy(
                "metrics-*",
                tf,
                layer="bar",
                query=(
                    f"FROM metrics-* | STATS c = SUM(`http.server.request.count`) BY svc = {svc} "
                    f"| SORT c DESC | LIMIT 12"
                ),
                x="svc",
                ys=[("c", None)],
                breakdown=None,
                lens_title=f"{lt} (HTTP request volume by service — availability proxy)",
            )
        if cap["logs"]:
            if status_src:
                st = _esql_ident(status_src)
                return _spec_xy(
                    "logs-*",
                    tf,
                    layer="bar",
                    query=(
                        f"FROM logs-* | STATS c = COUNT(*) BY code = {st} | SORT c DESC | LIMIT 12"
                    ),
                    x="code",
                    ys=[("c", None)],
                    breakdown=None,
                    lens_title=f"{lt} (HTTP status — logs)",
                )
            return _spec_xy(
                "logs-*",
                tf,
                layer="bar",
                query=(
                    f"FROM logs-* | STATS c = COUNT(*) BY svc = {svc} | SORT c DESC | LIMIT 12"
                ),
                x="svc",
                ys=[("c", None)],
                breakdown=None,
                lens_title=f"{lt} (log volume by service — HTTP proxy)",
            )

    if cat == "operation_errors" and cap["metrics"]:
        # Prefer workshop OTLP counter operation_errors_total{reason,entity_id}; fallback-style HTTP status otherwise.
        if panel_index % 2 == 0:
            return _spec_xy(
                "metrics-*",
                tf,
                layer="bar",
                query=(
                    "FROM metrics-* | STATS c = SUM(`operation_errors_total`) "
                    "BY reason = `attributes.reason` "
                    "| SORT c DESC | LIMIT 12"
                ),
                x="reason",
                ys=[("c", None)],
                breakdown=None,
                lens_title=f"{lt} (operation_errors_total by reason)",
            )
        return _spec_xy(
            "metrics-*",
            tf,
            layer="bar",
            query=(
                "FROM metrics-* | STATS c = SUM(`operation_errors_total`) "
                "BY e = `attributes.entity_id` "
                "| SORT c DESC | LIMIT 10"
            ),
            x="e",
            ys=[("c", None)],
            breakdown=None,
            lens_title=f"{lt} (operation_errors_total by entity_id)",
        )

    if cat == "by_entity" and cap["metrics"]:
        return _spec_xy(
            "metrics-*",
            tf,
            layer="bar",
            query=(
                "FROM metrics-* | STATS c = COUNT(*) BY e = `attributes.entity_id` | SORT c DESC | LIMIT 10"
            ),
            x="e",
            ys=[("c", None)],
            breakdown=None,
            lens_title=f"{lt} (volume by entity_id — http_requests_total proxy)",
        )

    if cat == "by_entity_latency" and cap["metrics"]:
        return _spec_xy(
            "metrics-*",
            tf,
            layer="line",
            query=(
                f"FROM metrics-* | STATS m = AVG(`http.server.request.duration`) "
                f"BY bucket = {q_b}, e = `attributes.entity_id`"
            ),
            x="bucket",
            ys=[("m", None)],
            breakdown="e",
            lens_title=f"{lt} (avg request duration by entity_id — p95 proxy)",
        )

    if cat == "operation_errors" and cap["traces"] and not cap["metrics"]:
        return _spec_xy(
            "traces-*",
            tf,
            layer="bar",
            query=(
                "FROM traces-* | STATS c = COUNT(*) BY name = span.name | SORT c DESC | LIMIT 12"
            ),
            x="name",
            ys=[("c", None)],
            breakdown=None,
            lens_title=f"{lt} (trace spans — operation_errors proxy)",
        )

    if cat == "errors" and cap["logs"]:
        return _spec_xy(
            "logs-*",
            tf,
            layer="bar",
            query=(
                "FROM logs-* | STATS c = COUNT(*) BY lvl = log.level | SORT c DESC | LIMIT 8"
            ),
            x="lvl",
            ys=[("c", None)],
            breakdown=None,
            lens_title=f"{lt} (log level)",
        )

    if cat == "cpu" and cap["metrics"]:
        return _spec_xy(
            "metrics-*",
            tf,
            layer="line",
            query=(
                f"FROM metrics-* | STATS m = AVG(`system.cpu.utilization`) BY bucket = {q_b}"
            ),
            x="bucket",
            ys=[("m", None)],
            breakdown=None,
            lens_title=f"{lt} (CPU utilization — OTLP)",
        )

    if cat == "memory" and cap["metrics"]:
        return _spec_xy(
            "metrics-*",
            tf,
            layer="area",
            query=(
                f"FROM metrics-* | STATS m = AVG(`system.memory.utilization`) BY bucket = {q_b}"
            ),
            x="bucket",
            ys=[("m", None)],
            breakdown=None,
            lens_title=f"{lt} (memory utilization — OTLP)",
        )

    if cat == "storage" and cap["metrics"]:
        return vol_line("line")

    if cat == "k8s" and cap["logs"]:
        return _spec_xy(
            "logs-*",
            tf,
            layer="bar",
            query="FROM logs-* | STATS c = COUNT(*) BY h = host.name | SORT c DESC | LIMIT 10",
            x="h",
            ys=[("c", None)],
            breakdown=None,
            lens_title=f"{lt} (by host — K8s proxy)",
        )

    if cat == "db":
        if cap["logs"]:
            return _spec_xy(
                "logs-*",
                tf,
                layer="line",
                query=(
                    f"FROM logs-* | STATS c = COUNT(*) BY bucket = {q_b}, svc = service.name"
                ),
                x="bucket",
                ys=[("c", None)],
                breakdown="svc",
                lens_title=f"{lt} (by service — DB proxy)",
            )
        if cap["traces"] and not cap["logs"]:
            return _spec_xy(
                "traces-*",
                tf,
                layer="bar",
                query=(
                    "FROM traces-* | STATS c = COUNT(*) BY name = span.name "
                    "| SORT c DESC | LIMIT 10"
                ),
                x="name",
                ys=[("c", None)],
                breakdown=None,
                lens_title=f"{lt} (span names — DB proxy)",
            )

    if cat == "scrape":
        if cap["metrics"]:
            return _spec_xy(
                "metrics-*",
                tf,
                layer="line",
                query=(
                    f"FROM metrics-* | STATS c = SUM(`http.server.request.count`) "
                    f"BY bucket = {q_b}"
                ),
                x="bucket",
                ys=[("c", None)],
                breakdown=None,
                lens_title=f"{lt} (HTTP request volume — scrape proxy)",
            )

    if cat == "network" and cap["metrics"]:
        return _spec_xy(
            "metrics-*",
            tf,
            layer="area",
            query=(
                f"FROM metrics-* | STATS c = SUM(`http.server.request.count`) "
                f"BY bucket = {q_b}"
            ),
            x="bucket",
            ys=[("c", None)],
            breakdown=None,
            lens_title=f"{lt} (HTTP request volume — traffic proxy)",
        )

    # generic: vary chart type / breakdown so padded panels on one dashboard still differ
    # OTLP fleet sets http.route on metrics, not url.path (legacy bulk seed field).
    if panel_index % 3 == 1:
        if cap["metrics"]:
            return _spec_xy(
                "metrics-*",
                tf,
                layer="bar",
                query=(
                    f"FROM metrics-* | STATS c = SUM(`http.server.request.count`) "
                    f"BY path = {_esql_ident(_esql_http_route_column())} | SORT c DESC | LIMIT 10"
                ),
                x="path",
                ys=[("c", None)],
                breakdown=None,
                lens_title=f"{lt} (HTTP route)",
            )
        if cap["logs"]:
            return _spec_xy(
                "logs-*",
                tf,
                layer="bar",
                query=(
                    "FROM logs-* | STATS c = COUNT(*) BY path = service.name | SORT c DESC | LIMIT 10"
                ),
                x="path",
                ys=[("c", None)],
                breakdown=None,
                lens_title=f"{lt} (top services)",
            )
    if cap["logs"] and panel_index % 3 == 2:
        return _spec_xy(
            "logs-*",
            tf,
            layer="line",
            query=(
                f"FROM logs-* | STATS c = COUNT(*) BY bucket = {q_b}, svc = service.name"
            ),
            x="bucket",
            ys=[("c", None)],
            breakdown="svc",
            lens_title=f"{lt} (by service)",
        )
    if cap["traces"] and not cap["logs"] and panel_index % 5 == 4:
        return _spec_xy(
            "traces-*",
            tf,
            layer="bar",
            query=(
                "FROM traces-* | STATS c = COUNT(*) BY name = span.name | SORT c DESC | LIMIT 10"
            ),
            x="name",
            ys=[("c", None)],
            breakdown=None,
            lens_title=f"{lt} (span.name)",
        )

    return vol_line("line") if panel_index % 2 == 0 else vol_area()


def _lens_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    title = str(spec.get("lens_title") or "")[:255]
    if spec["viz"] == "metric":
        return {
            "type": "lens",
            "uid": str(uuid.uuid4()),
            "config": {
                "attributes": {
                    "title": title,
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
    return {
        "type": "lens",
        "uid": str(uuid.uuid4()),
        "config": {
            "attributes": {
                "title": title,
                "type": "xy",
                "layers": [layer],
            }
        },
    }


def build_mixed_esql_panels(
    draft: dict[str, Any], *, from_clause: str, time_field: str
) -> list[dict[str, Any]]:
    """Lens panels: ES|QL + chart type chosen per Grafana panel (PromQL/title), not the same rotation on every dashboard."""
    if (os.environ.get("WORKSHOP_DISABLE_LENS") or "").strip() in ("1", "true", "yes"):
        return []
    if (os.environ.get("WORKSHOP_SIMPLE_LENS") or "").strip() in ("1", "true", "yes"):
        return []
    panel_rows = _expand_draft_panels_for_lens(draft)
    tf = time_field
    fc = from_clause.strip()
    cap = _from_capabilities(fc)
    out: list[dict[str, Any]] = []
    for i, pan in enumerate(panel_rows):
        if not isinstance(pan, dict):
            continue
        spec = _panel_esql_spec(pan, from_clause=fc, tf=tf, panel_index=i, cap=cap)
        out.append(_lens_from_spec(spec))
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
    for pan in panel_rows:
        if not isinstance(pan, dict):
            continue
        pq = _migration_source_query(pan.get("migration") or {})
        ptitle = str(pan.get("title") or "")
        lens_title = _truncate_lens_title(ptitle, pq)
        out.append(
            {
                "type": "lens",
                "uid": str(uuid.uuid4()),
                "config": {
                    "attributes": {
                        "title": lens_title[:255],
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
    md = markdown_for_canvas(description, dashboard_title=title)
    listing_desc = _short_listing_description(draft, title)
    base: dict[str, Any] = {
        "title": title[:255],
        "description": listing_desc,
        "time_range": {"from": "now-30d", "to": "now"},
    }
    note_compact: list[tuple[str, list[dict[str, Any]]]] = [
        (
            "markdown",
            [
                {
                    "grid": {"x": 0, "y": 0, "w": 48, "h": 8},
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
                    "grid": {"x": 0, "y": 0, "w": 48, "h": 8},
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

    for _lbl, panels in _note_only_fallback_panels(md, listing_desc):
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
    ap = argparse.ArgumentParser(
        description="Create Kibana dashboards from Grafana or Datadog migration drafts (*-elastic-draft.json) via HTTP API."
    )
    ap.add_argument(
        "--drafts-dir",
        type=Path,
        default=Path("build/elastic-dashboards"),
        help="Directory containing *-elastic-draft.json (e.g. build/elastic-dashboards or build/elastic-datadog-dashboards)",
    )
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
        try:
            raw = path.read_text(encoding="utf-8")
            draft = json.loads(raw)
        except OSError as e:
            failed.append(f"{path.name}: read error: {e}")
            print("FAIL", path.name, e, file=sys.stderr)
            continue
        except json.JSONDecodeError as e:
            failed.append(f"{path.name}: invalid JSON: {e}")
            print("FAIL", path.name, e, file=sys.stderr)
            continue
        if not isinstance(draft, dict):
            failed.append(f"{path.name}: draft root must be a JSON object")
            print("FAIL", path.name, "expected object at root", file=sys.stderr)
            continue
        title = str(draft.get("title") or path.stem)
        list_desc = _short_listing_description(draft, title)
        dash_id = sanitize_id(path.stem)
        body = dashboard_payload(title, list_desc)

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
