#!/usr/bin/env python3
"""
CLI: Grafana dashboard JSON -> Elastic dashboard draft (Kibana HTTP API friendly JSON).

This mirrors workflows described in the Elastic Agent Skills pack for this workshop. It extracts
PromQL expressions and produces a minimal dashboard document you can refine in Kibana or extend
with https://github.com/elastic/agent-skills (kibana-dashboards skill patterns).

Usage:
  python3 tools/grafana_to_elastic.py path/to/grafana-dashboard.json
  python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def iter_promql(dashboard: dict[str, Any]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []

    def walk(obj: Any, panel_title: str | None = None) -> None:
        if isinstance(obj, dict):
            title = obj.get("title") or panel_title
            if "targets" in obj and isinstance(obj["targets"], list):
                for t in obj["targets"]:
                    if isinstance(t, dict) and "expr" in t:
                        found.append(
                            {
                                "panel": str(title or "panel"),
                                "expr": str(t["expr"]),
                                "legend": str(t.get("legendFormat") or ""),
                            }
                        )
            for v in obj.values():
                walk(v, str(title) if title else panel_title)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, panel_title)

    walk(dashboard.get("panels", []) or [], dashboard.get("title"))
    return found


def promql_to_esql_note(expr: str) -> str:
    """
    Lightweight translation hints (workshop narrative). Full PromQL->ES|QL is context-dependent;
    Elastic Observability also supports PromQL against Prometheus-compatible metric stores.
    """
    if "rate(" in expr:
        return (
            "PromQL uses rate(); in ES|QL use METRICS indices with TS counters and derivative/windowed aggregates. "
            "On Elastic Serverless, prefer native PromQL where enabled for Prometheus-backed metrics, or model "
            "the same series in TSDB."
        )
    if "histogram_quantile" in expr:
        return "histogram_quantile in PromQL maps to percentile aggregation over histogram buckets in ES|QL."
    return "Map label selectors to dimensions (e.g., entity_id) and use time-bucketed aggregations."


def build_elastic_dashboard(title: str, queries: list[dict[str, str]]) -> dict[str, Any]:
    panels: list[dict[str, Any]] = []
    for i, q in enumerate(queries):
        panels.append(
            {
                "type": "lens",
                "title": q["panel"],
                "description": "Imported from Grafana. Source PromQL:\n" + q["expr"],
                "note": promql_to_esql_note(q["expr"]),
                "migration": {
                    "source": "grafana",
                    "promql": q["expr"],
                    "legend": q["legend"],
                },
            }
        )
        if i >= 49:
            break
    return {
        "title": f"{title} (Grafana import draft)",
        "panels": panels,
        "time_range": {"from": "now-24h", "to": "now"},
        "tags": ["workshop", "grafana-import", "elastic-serverless-migration-lab"],
    }


def convert_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    title = str(data.get("title") or path.stem)
    queries = iter_promql(data)
    if not queries:
        queries = [
            {
                "panel": "placeholder",
                "expr": 'sum(rate(http_requests_total[5m]))',
                "legend": "",
            }
        ]
    return build_elastic_dashboard(title, queries)


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert Grafana dashboard JSON to Elastic dashboard draft JSON.")
    ap.add_argument("inputs", nargs="+", help="Grafana dashboard JSON files")
    ap.add_argument("--out-dir", type=Path, help="Write one JSON file per input")
    args = ap.parse_args()

    out_dir: Path | None = args.out_dir
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    for raw in args.inputs:
        p = Path(raw)
        elastic = convert_file(p)
        if out_dir:
            target = out_dir / f"{p.stem}-elastic-draft.json"
            target.write_text(json.dumps(elastic, indent=2) + "\n", encoding="utf-8")
            print(target)
        else:
            json.dump(elastic, sys.stdout, indent=2)
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
