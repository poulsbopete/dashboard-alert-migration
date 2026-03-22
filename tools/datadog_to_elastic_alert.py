#!/usr/bin/env python3
"""
CLI: Datadog monitor JSON -> Kibana alerting rule JSON (draft).

Datadog export shapes vary; this handles a common monitor document and maps threshold-style
conditions to Elastic stackAlerts-style documents for follow-up via Kibana APIs.

Usage:
  python3 tools/datadog_to_elastic_alert.py assets/datadog/monitor-high-error-rate.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def coalesce(*vals: Any) -> Any:
    for v in vals:
        if v is not None:
            return v
    return None


def map_threshold_monitor(mon: dict[str, Any]) -> dict[str, Any]:
    name = str(mon.get("name") or mon.get("title") or "datadog-import")
    query = str(mon.get("query") or "")
    critical = None
    opts = mon.get("options")
    if isinstance(opts, dict):
        thr = opts.get("thresholds")
        if isinstance(thr, dict):
            critical = thr.get("critical")
    critical = coalesce(critical, mon.get("threshold"))

    rule_id = name.lower().replace(" ", "-")[:80] or "datadog-imported-monitor"

    # Prefer Elasticsearch query rule as a generic starting point; operators refine in Kibana UI/API.
    return {
        "id": rule_id,
        "name": f"{name} (Datadog import draft)",
        "rule_type_id": ".es-query",
        "consumer": "observability",
        "schedule": {"interval": "5m"},
        "params": {
            "index": ["metrics-*", "logs-*"],
            "timeField": "@timestamp",
            "esQuery": json.dumps(
                {
                    "query": {
                        "bool": {
                            "filter": [
                                {"range": {"@timestamp": {"gte": "now-15m"}}},
                            ]
                        }
                    }
                }
            ),
            "threshold": [int(critical) if isinstance(critical, (int, float)) else 1],
            "thresholdComparator": ">",
            "timeWindowSize": 15,
            "timeWindowUnit": "m",
            "size": 100,
        },
        "tags": ["workshop", "datadog-import", "merchant-platform-serverless-migration"],
        "migration": {
            "source": "datadog",
            "original_query": query,
            "notes": "Replace esQuery with a concrete ES|QL or KQL translation of the Datadog query. "
            "For metrics, consider observability threshold rule types once signal types are chosen.",
        },
    }


def convert(mon: dict[str, Any]) -> dict[str, Any]:
    mtype = str(mon.get("type") or "query alert")
    if "anomaly" in mtype.lower():
        return {
            "id": (mon.get("name") or "anomaly").lower().replace(" ", "-")[:80],
            "name": str(mon.get("name")),
            "rule_type_id": "xpack.ml.anomaly_detection_alert",
            "consumer": "ml",
            "schedule": {"interval": "15m"},
            "params": {
                "job_id": "REPLACE_WITH_ML_JOB_ID",
                "severity": 50,
                "include_interim": True,
            },
            "tags": ["workshop", "datadog-anomaly-import"],
            "migration": {
                "source": "datadog",
                "note": "Datadog anomaly monitors map to Elastic anomaly detection jobs + rules where ML is enabled.",
            },
        }
    return map_threshold_monitor(mon)


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert Datadog monitor JSON to Elastic alert draft JSON.")
    ap.add_argument("input", help="Datadog monitor JSON file")
    ap.add_argument("-o", "--output", type=Path, help="Write JSON to this path")
    args = ap.parse_args()
    src = Path(args.input)
    mon = json.loads(src.read_text(encoding="utf-8"))
    rule = convert(mon)
    text = json.dumps(rule, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(args.output)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
