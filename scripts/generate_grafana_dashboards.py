#!/usr/bin/env python3
"""Generate sample Grafana dashboard JSON files (Prometheus datasource) for the workshop.

Each dashboard is a small "mini-operations" view: markdown context, a stat KPI, two time
series (aggregate + dimensional breakdown), and a table snapshot. PromQL avoids ``topk`` /
``bottomk`` so mig-to-kbn native PROMQL translation can migrate every panel (those
aggregates are not supported by the ES PROMQL bridge — see mig-to-kbn panels.py).

**PromQL label keys** must match **Elasticsearch column names** for native ``PROMQL`` on
Serverless. The OTLP fleet sets OpenTelemetry semantic attributes (``http.request.method``, …),
which appear as dotted fields (not ``http.request.method`` / ``http.route``). Use
``service.name`` for per-service breakdown (same cardinality as workshop ``entity_id``).

**Multi-label ``sum by (a, b, ...)``** is avoided for non-histogram panels: Kibana Lens with
native **PROMQL** can error with ``unresolved_exception`` / ``?label`` when more than one
breakdown column is expected (Elasticsearch 9.x). Use one grouping label per chart; compare
dimensions across panels instead.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "grafana"

# (filename, title, intro_md, stat_title, stat_expr, ts1_title, ts1_expr, ts2_title, ts2_expr, table_title, table_expr)
DASH_SPECS: list[tuple[str, str, str, str, str, str, str, str, str, str, str]] = [
    (
        "01-overview.json",
        "Traffic overview",
        "**Traffic overview** — end-to-end HTTP volume from the workshop emitters. Compare the headline KPI with dimensional splits.",
        "Requests/sec (total)",
        "sum(rate(http_requests_total[5m]))",
        "Total request rate",
        "sum(rate(http_requests_total[5m]))",
        "By HTTP method",
        "sum by (http.request.method) (rate(http_requests_total[5m]))",
        "By status code (instant)",
        "sum by (http.response.status_code) (rate(http_requests_total[5m]))",
    ),
    (
        "02-request-rate.json",
        "Request rate by service",
        "**Service throughput** — per-service rate plus **single-label** splits (route and status); multi-label ``sum by`` breaks native PROMQL in Lens.",
        "Requests/sec (all)",
        "sum(rate(http_requests_total[5m]))",
        "Rate by service",
        "sum by (service.name) (rate(http_requests_total[5m]))",
        "Rate by route",
        "sum by (http.route) (rate(http_requests_total[5m]))",
        "By status code (instant)",
        "sum by (http.response.status_code) (rate(http_requests_total[5m]))",
    ),
    (
        "03-latency-p95.json",
        "Latency p95",
        "**Latency** — p95 from histogram buckets; p50 adds a median contrast. Count series tracks observation volume.",
        "Duration samples/sec",
        "sum(rate(http_request_duration_seconds_count[5m]))",
        "p95 by service",
        "histogram_quantile(0.95, sum by (le, service.name) (rate(http_request_duration_seconds_bucket[5m])))",
        "p50 by service",
        "histogram_quantile(0.50, sum by (le, service.name) (rate(http_request_duration_seconds_bucket[5m])))",
        "Mean latency (sum/count)",
        "sum(rate(http_request_duration_seconds_sum[5m])) / sum(rate(http_request_duration_seconds_count[5m]))",
    ),
    (
        "04-error-rate.json",
        "Error rate",
        "**Errors** — 5xx share of traffic plus raw server-error rate for context.",
        "5xx share",
        "sum(rate(http_requests_total{http.response.status_code=~\"5..\"}[5m])) / sum(rate(http_requests_total[5m]))",
        "Error ratio",
        "sum(rate(http_requests_total{http.response.status_code=~\"5..\"}[5m])) / sum(rate(http_requests_total[5m]))",
        "5xx requests/sec",
        "sum(rate(http_requests_total{http.response.status_code=~\"5..\"}[5m]))",
        "Errors by status (instant)",
        "sum by (http.response.status_code) (rate(http_requests_total[5m]))",
    ),
    (
        "05-operation-errors.json",
        "Operation errors by reason",
        "**Business errors** — ``operation_errors_total`` by ``reason``.",
        "Operation errors/sec",
        "sum(rate(operation_errors_total[5m]))",
        "By reason",
        "sum by (reason) (rate(operation_errors_total[5m]))",
        "Errors by service",
        "sum by (service.name) (rate(operation_errors_total[5m]))",
        "Reason snapshot",
        "sum by (reason) (rate(operation_errors_total[5m]))",
    ),
    (
        "06-top-entities.json",
        "Top services by traffic",
        "**Service ranking** — Grafana ``topk`` is omitted so migration stays on the supported PromQL subset; use Lens Top Values or ``LIMIT`` in Kibana for strict top-N.",
        "Total requests/sec",
        "sum(rate(http_requests_total[5m]))",
        "Rate by service",
        "sum by (service.name) (rate(http_requests_total[5m]))",
        "Rate by HTTP method",
        "sum by (http.request.method) (rate(http_requests_total[5m]))",
        "Service snapshot (instant)",
        "sum by (service.name) (rate(http_requests_total[5m]))",
    ),
    (
        "07-post-path.json",
        "POST /api/v1/orders volume",
        "**Hot POST route** — ``POST /api/v1/orders`` (emitted by the fleet) vs all POST traffic.",
        "POST /api/v1/orders rps",
        "sum(rate(http_requests_total{http.route=\"/api/v1/orders\",http.request.method=\"POST\"}[5m]))",
        "Orders POST rate",
        "sum(rate(http_requests_total{http.route=\"/api/v1/orders\",http.request.method=\"POST\"}[5m]))",
        "All POST traffic",
        "sum(rate(http_requests_total{http.request.method=\"POST\"}[5m]))",
        "POST by route (instant)",
        "sum by (http.route) (rate(http_requests_total{http.request.method=\"POST\"}[5m]))",
    ),
    (
        "08-latency-by-path.json",
        "Latency by path",
        "**Path latency** — p99 per path plus a coarser p90 for comparison.",
        "Request count/sec",
        "sum(rate(http_request_duration_seconds_count[5m]))",
        "p99 by path",
        "histogram_quantile(0.99, sum by (le, http.route) (rate(http_request_duration_seconds_bucket[5m])))",
        "p90 by path",
        "histogram_quantile(0.90, sum by (le, http.route) (rate(http_request_duration_seconds_bucket[5m])))",
        "Mean latency (instant)",
        "sum(rate(http_request_duration_seconds_sum[5m])) / sum(rate(http_request_duration_seconds_count[5m]))",
    ),
    (
        "09-status-codes.json",
        "Status codes",
        "**HTTP status mix** — rates per status and per method.",
        "All responses/sec",
        "sum(rate(http_requests_total[5m]))",
        "By status",
        "sum by (http.response.status_code) (rate(http_requests_total[5m]))",
        "By method",
        "sum by (http.request.method) (rate(http_requests_total[5m]))",
        "Status snapshot (instant)",
        "sum by (http.response.status_code) (rate(http_requests_total[5m]))",
    ),
    (
        "10-slo-burn.json",
        "SLO-style availability",
        "**Availability window** — 1h error budget style ratio plus component series.",
        "Availability (1h)",
        "1 - (sum(rate(http_requests_total{http.response.status_code=~\"5..\"}[1h])) / sum(rate(http_requests_total[1h])))",
        "Availability",
        "1 - (sum(rate(http_requests_total{http.response.status_code=~\"5..\"}[1h])) / sum(rate(http_requests_total[1h])))",
        "5xx volume (1h rate)",
        "sum(rate(http_requests_total{http.response.status_code=~\"5..\"}[1h]))",
        "Total traffic (1h rate)",
        "sum(rate(http_requests_total[1h]))",
    ),
    (
        "11-entity-errors.json",
        "Errors by service",
        "**Errors per service** — pairs operation errors with HTTP context.",
        "Op errors/sec",
        "sum(rate(operation_errors_total[5m]))",
        "Op errors by service",
        "sum by (service.name) (rate(operation_errors_total[5m]))",
        "HTTP 5xx by service",
        "sum by (service.name) (rate(http_requests_total{http.response.status_code=~\"5..\"}[5m]))",
        "Service error snapshot",
        "sum by (service.name) (rate(operation_errors_total[5m]))",
    ),
    (
        "12-heatmap-style.json",
        "Request mix",
        "**Request mix** — service volume plus method and status as **separate** single-label charts (see generator docstring).",
        "Requests/sec",
        "sum(rate(http_requests_total[5m]))",
        "Requests by service",
        "sum by (service.name) (rate(http_requests_total[5m]))",
        "By method",
        "sum by (http.request.method) (rate(http_requests_total[5m]))",
        "By status",
        "sum by (http.response.status_code) (rate(http_requests_total[5m]))",
    ),
    (
        "13-cpu-saturation.json",
        "Throughput by host",
        "**Saturation proxy** — HTTP request rate by ``host.name`` (workshop OTLP has no ``process_cpu_seconds_total``).",
        "Requests/sec (total)",
        "sum(rate(http_requests_total[5m]))",
        "Request rate by host",
        "sum by (host.name) (rate(http_requests_total[5m]))",
        "Request rate by service",
        "sum by (service.name) (rate(http_requests_total[5m]))",
        "By host (instant)",
        "sum by (host.name) (rate(http_requests_total[5m]))",
    ),
    (
        "14-memory-working-set.json",
        "Workload mix",
        "**Workload** — HTTP traffic plus operation errors (no ``process_resident_memory_bytes`` in workshop OTLP).",
        "Requests/sec",
        "sum(rate(http_requests_total[5m]))",
        "Operation errors/sec",
        "sum(rate(operation_errors_total[5m]))",
        "Errors by service",
        "sum by (service.name) (rate(operation_errors_total[5m]))",
        "Errors by reason (instant)",
        "sum by (reason) (rate(operation_errors_total[5m]))",
    ),
    (
        "15-gc-pause-rate.json",
        "GC pause indicator",
        "**Why not real Go GC metrics here:** `go_gc_duration_seconds_*` histogram parts are often stored in Elasticsearch as **double** gauges, while ES|QL **RATE** only accepts **counter** fields — migrated panels then fail at query time. "
        "This board keeps the **GC / runtime pressure** story but uses the workshop fleet’s **counter** metrics (`http_requests_total`, `operation_errors_total`) so native PromQL → ES|QL works on Serverless.",
        "HTTP requests/sec",
        "sum(rate(http_requests_total[5m]))",
        "Request burst by host",
        "sum by (host.name) (rate(http_requests_total[5m]))",
        "Operation errors/sec",
        "sum(rate(operation_errors_total[5m]))",
        "Requests by service (instant)",
        "sum by (service.name) (rate(http_requests_total[5m]))",
    ),
    (
        "16-dependency-latency.json",
        "Downstream latency p90",
        "**Server latency** — same histograms as path latency (no outbound ``http_client_duration_*`` in workshop OTLP).",
        "Request count/sec",
        "sum(rate(http_request_duration_seconds_count[5m]))",
        "p90 by route",
        "histogram_quantile(0.90, sum by (le, http.route) (rate(http_request_duration_seconds_bucket[5m])))",
        "p50 by route",
        "histogram_quantile(0.50, sum by (le, http.route) (rate(http_request_duration_seconds_bucket[5m])))",
        "Mean latency (instant)",
        "sum(rate(http_request_duration_seconds_sum[5m])) / sum(rate(http_request_duration_seconds_count[5m]))",
    ),
    (
        "17-queue-depth.json",
        "Queue depth stand-in",
        "**Queues** — request **rate** by route and service (no ``workqueue_depth`` in workshop OTLP).",
        "Total requests/sec",
        "sum(rate(http_requests_total[5m]))",
        "Rate by route",
        "sum by (http.route) (rate(http_requests_total[5m]))",
        "Rate by service",
        "sum by (service.name) (rate(http_requests_total[5m]))",
        "Route snapshot (instant)",
        "sum by (http.route) (rate(http_requests_total[5m]))",
    ),
    (
        "18-cache-hit-ratio.json",
        "Success share (2xx)",
        "**Availability proxy** — 2xx share of traffic (no ``cache_*`` counters in workshop OTLP).",
        "2xx share",
        "sum(rate(http_requests_total{http.response.status_code=~\"2..\"}[5m])) / sum(rate(http_requests_total[5m]))",
        "2xx share",
        "sum(rate(http_requests_total{http.response.status_code=~\"2..\"}[5m])) / sum(rate(http_requests_total[5m]))",
        "2xx requests/sec",
        "sum(rate(http_requests_total{http.response.status_code=~\"2..\"}[5m]))",
        "Non-2xx requests/sec",
        "sum(rate(http_requests_total{http.response.status_code!~\"2..\"}[5m]))",
    ),
    (
        "19-pod-restarts.json",
        "Error churn",
        "**Churn proxy** — operation error rates (no Kubernetes metrics in workshop OTLP).",
        "Operation errors/sec",
        "sum(rate(operation_errors_total[5m]))",
        "Errors by reason",
        "sum by (reason) (rate(operation_errors_total[5m]))",
        "Errors by service",
        "sum by (service.name) (rate(operation_errors_total[5m]))",
        "Reason snapshot (instant)",
        "sum by (reason) (rate(operation_errors_total[5m]))",
    ),
    (
        "20-endpoint-slo.json",
        "Endpoint availability",
        "**Success share** — non-5xx fraction over 30m.",
        "Success ratio (30m)",
        "sum(rate(http_requests_total{http.response.status_code!~\"5..\"}[30m])) / sum(rate(http_requests_total[30m]))",
        "Success ratio",
        "sum(rate(http_requests_total{http.response.status_code!~\"5..\"}[30m])) / sum(rate(http_requests_total[30m]))",
        "Successful rps",
        "sum(rate(http_requests_total{http.response.status_code!~\"5..\"}[30m]))",
        "Total rps",
        "sum(rate(http_requests_total[30m]))",
    ),
]


def _ds() -> dict:
    return {"type": "prometheus", "uid": "${datasource}"}


def _templating() -> dict:
    return {
        "list": [
            {
                "name": "datasource",
                "type": "datasource",
                "query": "prometheus",
                "current": {"selected": True, "text": "Prometheus", "value": "Prometheus"},
            }
        ]
    }


def panel_text(content: str, y: int, h: int = 3) -> dict:
    return {
        "type": "text",
        "title": "",
        "gridPos": {"h": h, "w": 24, "x": 0, "y": y},
        "options": {"mode": "markdown", "content": content},
    }


def panel_stat(title: str, expr: str, x: int, y: int, w: int, h: int) -> dict:
    return {
        "type": "stat",
        "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": _ds(),
        "targets": [{"expr": expr, "legendFormat": "", "refId": "A"}],
        "fieldConfig": {"defaults": {"unit": "short", "decimals": 3}, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "auto",
            "textMode": "auto",
            "colorMode": "value",
            "graphMode": "area",
        },
    }


def panel_timeseries(title: str, expr: str, x: int, y: int, w: int, h: int, legend: str = "") -> dict:
    return {
        "type": "timeseries",
        "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": _ds(),
        "targets": [{"expr": expr, "legendFormat": legend, "refId": "A"}],
        "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
    }


def panel_table(title: str, expr: str, x: int, y: int, w: int, h: int) -> dict:
    return {
        "type": "table",
        "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": _ds(),
        "targets": [
            {
                "expr": expr,
                "format": "table",
                "instant": True,
                "refId": "A",
            }
        ],
        "fieldConfig": {
            "defaults": {"unit": "short", "custom": {"align": "auto", "displayMode": "auto"}},
            "overrides": [],
        },
        "options": {"showHeader": True},
    }


def build_dashboard(uid: str, spec: tuple[str, str, str, str, str, str, str, str, str, str, str]) -> dict:
    (
        _fn,
        title,
        intro,
        stat_title,
        stat_expr,
        ts1_title,
        ts1_expr,
        ts2_title,
        ts2_expr,
        tbl_title,
        tbl_expr,
    ) = spec
    y0 = 0
    h_intro = 3
    y1 = y0 + h_intro
    h_row1 = 8
    y2 = y1 + h_row1
    h_row2 = 8
    panels: list[dict] = [
        panel_text(intro, y=y0, h=h_intro),
        panel_stat(stat_title, stat_expr, x=0, y=y1, w=6, h=h_row1),
        panel_timeseries(ts1_title, ts1_expr, x=6, y=y1, w=18, h=h_row1),
        panel_timeseries(ts2_title, ts2_expr, x=0, y=y2, w=12, h=h_row2),
        panel_table(tbl_title, tbl_expr, x=12, y=y2, w=12, h=h_row2),
    ]
    return {
        "uid": uid,
        "title": title,
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "10s",
        "time": {"from": "now-1h", "to": "now"},
        "templating": _templating(),
        "panels": panels,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for spec in DASH_SPECS:
        filename = spec[0]
        title = spec[1]
        uid = filename.replace(".json", "").replace("/", "-")
        path = OUT / filename
        path.write_text(json.dumps(build_dashboard(uid, spec), indent=2) + "\n", encoding="utf-8")
        print("wrote", path)


if __name__ == "__main__":
    main()
