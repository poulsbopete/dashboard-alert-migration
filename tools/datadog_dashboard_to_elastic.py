#!/usr/bin/env python3
"""
CLI: Datadog dashboard JSON (widgets with `q` / query strings) -> Elastic dashboard draft JSON.

Pairs with workshop Agent Skills + Cursor for bulk refinement toward Kibana / Observability Serverless.

Usage:
  python3 tools/datadog_dashboard_to_elastic.py assets/datadog/dashboards/*.json --out-dir build/elastic-datadog-dashboards
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def iter_dd_queries(dashboard: dict[str, Any]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []

    def add_q(widget_title: str, q: str) -> None:
        q = str(q).strip()
        if q:
            found.append({"panel": widget_title, "query": q})

    def walk_widget(w: dict[str, Any]) -> None:
        d = w.get("definition") or {}
        wtype = str(d.get("type") or "widget")
        title = str(d.get("title") or wtype)
        if wtype == "timeseries":
            for req in d.get("requests") or []:
                if isinstance(req, dict) and "q" in req:
                    add_q(title, req["q"])
        if wtype == "query_value":
            rq = d.get("requests") or []
            for req in rq if isinstance(rq, list) else []:
                if isinstance(req, dict) and "q" in req:
                    add_q(title, req["q"])
        if wtype == "toplist":
            for req in d.get("requests") or []:
                if isinstance(req, dict) and "q" in req:
                    add_q(title, req["q"])

    for w in dashboard.get("widgets") or []:
        if isinstance(w, dict):
            walk_widget(w)

    # Fallback: scrape any "q": "..." in tree
    if not found:

        def scrape(obj: Any) -> None:
            if isinstance(obj, dict):
                if "q" in obj and isinstance(obj["q"], str):
                    add_q("scraped", obj["q"])
                for v in obj.values():
                    scrape(v)
            elif isinstance(obj, list):
                for i in obj:
                    scrape(i)

        scrape(dashboard)

    return found


def query_to_note(q: str) -> str:
    if q.startswith("logs("):
        return "Datadog logs() → Elastic: map to data stream / ES|QL on logs-*; preserve filters as WHERE/KQL."
    if "trace." in q or "span" in q.lower():
        return "APM-style metric → Elastic APM or OTel traces; align service.name / transaction.name fields."
    if re.search(r"\b(avg|sum|p95|p99):", q):
        return "Datadog metric query → Elastic TSDB / metrics-*; rewrite rollup and group-by to TS | STATS patterns or PromQL-native views."
    return "Rewrite metric name and tags to your Elastic schema; validate in Discover / Metrics explorer."


def build_elastic_dashboard(title: str, queries: list[dict[str, str]]) -> dict[str, Any]:
    panels: list[dict[str, Any]] = []
    for i, row in enumerate(queries):
        panels.append(
            {
                "type": "lens",
                "title": row["panel"],
                "description": "Imported from Datadog dashboard. Source query:\n" + row["query"],
                "note": query_to_note(row["query"]),
                "migration": {"source": "datadog-dashboard", "datadog_query": row["query"]},
            }
        )
        if i >= 49:
            break
    return {
        "title": f"{title} (Datadog dashboard import draft)",
        "panels": panels,
        "time_range": {"from": "now-24h", "to": "now"},
        "tags": ["workshop", "datadog-dashboard-import", "elastic-serverless-migration-lab"],
    }


def convert_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    title = str(data.get("title") or path.stem)
    queries = iter_dd_queries(data)
    if not queries:
        queries = [{"panel": "placeholder", "query": "avg:system.cpu.user{*}"}]
    return build_elastic_dashboard(title, queries)


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert Datadog-style dashboard JSON to Elastic dashboard draft JSON.")
    ap.add_argument("inputs", nargs="+", help="Datadog dashboard JSON files")
    ap.add_argument("--out-dir", type=Path, required=True, help="Output directory")
    args = ap.parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    for raw in args.inputs:
        p = Path(raw)
        elastic = convert_file(p)
        target = out_dir / f"{p.stem}-elastic-draft.json"
        target.write_text(json.dumps(elastic, indent=2) + "\n", encoding="utf-8")
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
