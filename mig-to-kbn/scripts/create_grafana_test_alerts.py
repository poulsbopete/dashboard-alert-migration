"""Create realistic Grafana Unified Alerting rules for migration testing."""
import requests
import json
import sys

GRAFANA_URL = "http://localhost:23000"
session = requests.Session()
session.auth = ("admin", "admin")
session.headers.update({"Content-Type": "application/json"})

PROM_UID = "PBFA97CFB590B2093"
LOKI_UID = "P8E80F9AEF21F6940"
FOLDER_UID = "dfhraua26uneob"

ALERT_RULES = [
    {
        "title": "High CPU Usage",
        "ruleGroup": "infrastructure",
        "condition": "C",
        "for": "5m",
        "annotations": {
            "summary": "CPU usage is above 80% on {{ $labels.instance }}",
            "description": "Instance {{ $labels.instance }} has had CPU usage above 80% for more than 5 minutes.",
        },
        "labels": {"severity": "warning", "team": "infra"},
        "data": [
            {
                "refId": "A",
                "datasourceUid": PROM_UID,
                "model": {
                    "refId": "A",
                    "expr": '100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
                    "instant": False,
                    "range": True,
                    "intervalMs": 1000,
                    "maxDataPoints": 43200,
                },
                "relativeTimeRange": {"from": 600, "to": 0},
            },
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "B",
                    "type": "reduce",
                    "expression": "A",
                    "reducer": "last",
                    "conditions": [{"evaluator": {"type": "gt", "params": [0]}}],
                },
                "relativeTimeRange": {"from": 0, "to": 0},
            },
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "C",
                    "type": "threshold",
                    "expression": "B",
                    "conditions": [
                        {
                            "evaluator": {"type": "gt", "params": [80]},
                            "operator": {"type": "and"},
                            "reducer": {"type": "last"},
                        }
                    ],
                },
                "relativeTimeRange": {"from": 0, "to": 0},
            },
        ],
    },
    {
        "title": "Memory Usage Critical",
        "ruleGroup": "infrastructure",
        "condition": "C",
        "for": "10m",
        "annotations": {
            "summary": "Memory usage is above 90% on {{ $labels.instance }}",
        },
        "labels": {"severity": "critical", "team": "infra"},
        "data": [
            {
                "refId": "A",
                "datasourceUid": PROM_UID,
                "model": {
                    "refId": "A",
                    "expr": "(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100",
                    "instant": False,
                    "range": True,
                },
                "relativeTimeRange": {"from": 600, "to": 0},
            },
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "B",
                    "type": "reduce",
                    "expression": "A",
                    "reducer": "last",
                },
                "relativeTimeRange": {"from": 0, "to": 0},
            },
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "C",
                    "type": "threshold",
                    "expression": "B",
                    "conditions": [
                        {
                            "evaluator": {"type": "gt", "params": [90]},
                            "operator": {"type": "and"},
                            "reducer": {"type": "last"},
                        }
                    ],
                },
                "relativeTimeRange": {"from": 0, "to": 0},
            },
        ],
    },
    {
        "title": "Disk Space Low",
        "ruleGroup": "infrastructure",
        "condition": "C",
        "for": "15m",
        "annotations": {
            "summary": "Disk space below 20% on {{ $labels.mountpoint }}",
        },
        "labels": {"severity": "warning"},
        "data": [
            {
                "refId": "A",
                "datasourceUid": PROM_UID,
                "model": {
                    "refId": "A",
                    "expr": '(node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes) * 100',
                    "instant": False,
                    "range": True,
                },
                "relativeTimeRange": {"from": 600, "to": 0},
            },
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "B",
                    "type": "reduce",
                    "expression": "A",
                    "reducer": "last",
                },
                "relativeTimeRange": {"from": 0, "to": 0},
            },
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "C",
                    "type": "threshold",
                    "expression": "B",
                    "conditions": [
                        {
                            "evaluator": {"type": "lt", "params": [20]},
                            "operator": {"type": "and"},
                            "reducer": {"type": "last"},
                        }
                    ],
                },
                "relativeTimeRange": {"from": 0, "to": 0},
            },
        ],
    },
    {
        "title": "Prometheus Target Down",
        "ruleGroup": "monitoring",
        "condition": "C",
        "for": "3m",
        "annotations": {
            "summary": "Target {{ $labels.job }}/{{ $labels.instance }} is down",
        },
        "labels": {"severity": "critical", "team": "platform"},
        "data": [
            {
                "refId": "A",
                "datasourceUid": PROM_UID,
                "model": {
                    "refId": "A",
                    "expr": "up == 0",
                    "instant": True,
                    "range": False,
                },
                "relativeTimeRange": {"from": 60, "to": 0},
            },
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "B",
                    "type": "reduce",
                    "expression": "A",
                    "reducer": "last",
                },
                "relativeTimeRange": {"from": 0, "to": 0},
            },
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "C",
                    "type": "threshold",
                    "expression": "B",
                    "conditions": [
                        {
                            "evaluator": {"type": "gt", "params": [0]},
                            "operator": {"type": "and"},
                            "reducer": {"type": "last"},
                        }
                    ],
                },
                "relativeTimeRange": {"from": 0, "to": 0},
            },
        ],
    },
    {
        "title": "High Error Rate in Logs",
        "ruleGroup": "application",
        "condition": "C",
        "for": "5m",
        "annotations": {
            "summary": "Error rate in logs exceeds threshold",
        },
        "labels": {"severity": "warning", "team": "app"},
        "data": [
            {
                "refId": "A",
                "datasourceUid": LOKI_UID,
                "model": {
                    "refId": "A",
                    "expr": 'count_over_time({job=~".+"} |= "error" [5m])',
                    "instant": False,
                    "range": True,
                },
                "relativeTimeRange": {"from": 600, "to": 0},
            },
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "B",
                    "type": "reduce",
                    "expression": "A",
                    "reducer": "last",
                },
                "relativeTimeRange": {"from": 0, "to": 0},
            },
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "C",
                    "type": "threshold",
                    "expression": "B",
                    "conditions": [
                        {
                            "evaluator": {"type": "gt", "params": [100]},
                            "operator": {"type": "and"},
                            "reducer": {"type": "last"},
                        }
                    ],
                },
                "relativeTimeRange": {"from": 0, "to": 0},
            },
        ],
    },
]


def main():
    created = 0
    for rule_def in ALERT_RULES:
        payload = {
            "folderUID": FOLDER_UID,
            "ruleGroup": rule_def["ruleGroup"],
            "title": rule_def["title"],
            "condition": rule_def["condition"],
            "noDataState": "NoData",
            "execErrState": "Error",
            "for": rule_def["for"],
            "annotations": rule_def.get("annotations", {}),
            "labels": rule_def.get("labels", {}),
            "data": rule_def["data"],
        }

        resp = session.post(
            f"{GRAFANA_URL}/api/v1/provisioning/alert-rules",
            json=payload,
        )
        if resp.status_code in (200, 201):
            result = resp.json()
            print(f"  Created: {result['title']} (uid={result['uid']})")
            created += 1
        else:
            print(f"  FAILED ({resp.status_code}): {rule_def['title']}")
            print(f"    {resp.text[:300]}")

    print(f"\nCreated {created}/{len(ALERT_RULES)} alert rules")


if __name__ == "__main__":
    main()
