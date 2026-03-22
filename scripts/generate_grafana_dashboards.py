#!/usr/bin/env python3
"""Generate sample Grafana dashboard JSON files (Prometheus datasource) for the workshop."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "grafana"

QUERIES = [
    ("01-overview.json", "Merchant Overview", "sum(rate(http_requests_total[5m]))"),
    ("02-request-rate.json", "Request Rate by Merchant", "sum by (merchant_id) (rate(http_requests_total[5m]))"),
    ("03-latency-p95.json", "Latency p95", "histogram_quantile(0.95, sum by (le, merchant_id) (rate(http_request_duration_seconds_bucket[5m])))"),
    ("04-error-rate.json", "Error Rate", "sum(rate(http_requests_total{status=~\"5..\"}[5m])) / sum(rate(http_requests_total[5m]))"),
    ("05-payment-errors.json", "Payment Errors", "sum by (reason) (rate(payment_errors_total[5m]))"),
    ("06-top-merchants.json", "Top Merchants by Traffic", "topk(10, sum by (merchant_id) (rate(http_requests_total[5m])))"),
    ("07-post-path.json", "POST /v1/payments Volume", "sum(rate(http_requests_total{path=\"/v1/payments\"}[5m]))"),
    ("08-latency-by-path.json", "Latency by Path", "histogram_quantile(0.99, sum by (le, path) (rate(http_request_duration_seconds_bucket[5m])))"),
    ("09-status-codes.json", "Status Codes", "sum by (status) (rate(http_requests_total[5m]))"),
    ("10-slo-burn.json", "SLO-style Availability", "1 - (sum(rate(http_requests_total{status=~\"5..\"}[1h])) / sum(rate(http_requests_total[1h])))"),
    ("11-merchant-errors.json", "Errors by Merchant", "sum by (merchant_id) (rate(payment_errors_total[5m]))"),
    ("12-heatmap-style.json", "Request Mix", "sum by (method, status) (rate(http_requests_total[5m]))"),
]


def panel(title: str, expr: str, grid_pos: list[int]) -> dict:
    return {
        "type": "timeseries",
        "title": title,
        "gridPos": {"h": 8, "w": 12, "x": grid_pos[0], "y": grid_pos[1]},
        "datasource": {"type": "prometheus", "uid": "${datasource}"},
        "targets": [
            {
                "expr": expr,
                "legendFormat": "",
                "refId": "A",
            }
        ],
        "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
    }


def build_dashboard(uid: str, title: str, expr: str) -> dict:
    return {
        "uid": uid,
        "title": title,
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "10s",
        "time": {"from": "now-1h", "to": "now"},
        "templating": {
            "list": [
                {
                    "name": "datasource",
                    "type": "datasource",
                    "query": "prometheus",
                    "current": {"selected": True, "text": "Prometheus", "value": "Prometheus"},
                }
            ]
        },
        "panels": [
            panel("Primary", expr, [0, 0]),
            panel("Same query (comparison)", expr, [12, 0]),
        ],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, title, expr in QUERIES:
        uid = filename.replace(".json", "").replace("/", "-")
        path = OUT / filename
        path.write_text(json.dumps(build_dashboard(uid, title, expr), indent=2) + "\n", encoding="utf-8")
        print("wrote", path)


if __name__ == "__main__":
    main()
