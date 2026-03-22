#!/usr/bin/env python3
"""Generate sample Datadog dashboard JSON (widgets with `q` queries) for the workshop."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "datadog" / "dashboards"

# (filename, title, datadog query strings per widget)
DASHBOARDS: list[tuple[str, str, list[str]]] = [
    ("01-service-overview.json", "Service overview", ["avg:trace.http.request.duration{*} by {service}", "sum:trace.http.request.hits{*}.as_count()"]),
    ("02-error-budget.json", "Error budget view", ["sum:trace.http.request.errors{*}.as_count()", "sum:trace.http.request.hits{*}.as_count()"]),
    ("03-latency-p95.json", "Latency p95", ["p95:trace.http.request.duration{*} by {resource_name}"]),
    ("04-apdex-style.json", "Apdex-style satisfaction", ["avg:app.apdex.score{*} by {service}"]),
    ("05-host-cpu.json", "Host CPU", ["avg:system.cpu.user{*} by {host}", "avg:system.load.1{*} by {host}"]),
    ("06-host-memory.json", "Host memory", ["avg:system.mem.pct_usable{*} by {host}"]),
    ("07-disk-io.json", "Disk I/O", ["avg:system.disk.io{*} by {device}", "avg:system.disk.in_use{*} by {device}"]),
    ("08-network-bytes.json", "Network bytes", ["sum:system.net.bytes_sent{*}.as_rate()", "sum:system.net.bytes_rcvd{*}.as_rate()"]),
    ("09-container-throttle.json", "Container CPU throttle", ["avg:container.cpu.throttled{*} by {container_name}"]),
    ("10-log-error-spike.json", "Log error spike", ["logs(\"status:error service:checkout\").index(\"*\").rollup(\"count\").by(\"@http.url_details.path\")"]),
]


def widget_timeseries(title: str, queries: list[str]) -> dict:
    return {
        "definition": {
            "type": "timeseries",
            "title": title,
            "requests": [{"q": q, "display_type": "line"} for q in queries],
        },
        "layout": {"x": 0, "y": 0, "width": 12, "height": 4},
    }


def build_dashboard(title: str, queries: list[str]) -> dict:
    # Split queries across 1–2 widgets for variety
    w: list[dict] = []
    if len(queries) == 1:
        w.append(widget_timeseries("Primary", queries))
    else:
        w.append(widget_timeseries("Series A", [queries[0]]))
        w.append(widget_timeseries("Series B", queries[1:]))
    return {
        "title": title,
        "description": "Synthetic Datadog-style export for migration workshop",
        "widgets": w,
        "template_variables": [{"name": "env", "default": "*", "prefix": "env"}],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, title, queries in DASHBOARDS:
        path = OUT / filename
        path.write_text(json.dumps(build_dashboard(title, queries), indent=2) + "\n", encoding="utf-8")
        print("wrote", path)


if __name__ == "__main__":
    main()
