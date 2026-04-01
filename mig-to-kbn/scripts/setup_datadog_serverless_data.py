#!/usr/bin/env python3
"""
Extracts metrics from Datadog-migrated dashboards (compiled YAML) and ingests
synthetic time-series data into an Elastic Serverless cluster so the migrated
Kibana dashboards render meaningful visualisations.

Reads all YAML files from datadog_migration_output/integrations/yaml/ (or
$DASHBOARD_YAML_DIR), discovers required metric names and their likely types
(counter vs gauge), then generates 6 hours of data at 30-second intervals with
realistic diurnal patterns.

Usage:
    set -a && source serverless_creds.env && set +a
    DATA_HOURS=6 INTERVAL_SEC=30 python scripts/setup_datadog_serverless_data.py
"""

import json
import math
import os
import random
import re
import sys
import time
import datetime
import urllib.request
import urllib.error
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml

from observability_migration.adapters.source.datadog.field_map import load_profile
from observability_migration.adapters.source.datadog.monitor_seed import (
    discover_monitor_artifact,
    load_monitor_seed_requirements,
)

ES_ENDPOINT = os.environ["ELASTICSEARCH_ENDPOINT"]
API_KEY = os.environ["KEY"]

HEADERS = {
    "Authorization": f"ApiKey {API_KEY}",
    "Content-Type": "application/json",
}
CTX = ssl.create_default_context()

INDEX_NAME = "metrics-otel-default"
LOGS_INDEX_NAME = "logs-generic-default"

DATA_HOURS = float(os.environ.get("DATA_HOURS", "6"))
INTERVAL_SEC = int(os.environ.get("INTERVAL_SEC", "30"))
BULK_WORKERS = int(os.environ.get("BULK_WORKERS", "4"))
BATCH_DOC_LIMIT = int(os.environ.get("BATCH_DOC_LIMIT", "8000"))
METRICS_PER_DOC = int(os.environ.get("METRICS_PER_DOC", "100000"))
DASHBOARD_YAML_DIR = os.environ.get("DASHBOARD_YAML_DIR", "datadog_migration_output/integrations/yaml")
RECREATE_DATA_STREAMS = os.environ.get("RECREATE_DATA_STREAMS", "").strip() == "1"
FIELD_PROFILE = os.environ.get("FIELD_PROFILE", "otel")

COUNTER_HINTS = {
    "_total", "_count", "_sum", "bytes_sent", "bytes_rcvd",
    "requests", "errors", "dropped", "accepted", "refused",
    "sent", "received", "connections", "restarts", "retrans",
    "completed", "failed", "rejected", "timeout", "evictions",
}

GAUGE_HINTS = {
    "percent", "ratio", "usage", "utilization", "size",
    "free", "available", "used", "capacity", "current",
    "temperature", "load", "latency", "duration", "uptime",
    "active", "idle", "state", "status", "count",
    "in_use", "limit", "threshold",
}

HOSTS = ["web-01", "web-02", "db-01", "cache-01", "worker-01"]
NAMESPACES = ["default", "monitoring", "production"]
SERVICES = ["api", "frontend", "backend", "worker", "cache"]
_IDENT_RE = r"(?:`[^`]+`|[A-Za-z_][\w.-]*)"

DIMENSION_VALUE_POOLS: dict[str, list[str]] = {
    "docker_image": ["nginx:1.25", "redis:7.2", "postgres:16", "envoy:1.28", "consul:1.17"],
    "container_name": ["app", "sidecar", "proxy", "cache", "db"],
    "datacenter": ["us-east-1", "us-west-2", "eu-west-1"],
    "environment": ["production", "staging", "development"],
    "region": ["us-east", "us-west", "eu-west", "ap-south"],
    "direction": ["inbound", "outbound"],
    "rcode": ["NOERROR", "NXDOMAIN", "SERVFAIL", "REFUSED"],
    "outcome": ["success", "failure", "timeout"],
    "server": ["server-01", "server-02", "server-03"],
    "zone": ["zone-a", "zone-b", "zone-c"],
    "type": ["tcp", "udp", "http", "grpc"],
    "proto": ["tcp", "udp"],
    "method": ["GET", "POST", "PUT", "DELETE"],
    "status_code": ["200", "301", "404", "500"],
    "kube_stateful_set": ["statefulset-redis", "statefulset-kafka", "statefulset-zk"],
    "kube_service": ["svc-api", "svc-frontend", "svc-backend", "svc-cache"],
    "label": ["app:web", "app:api", "env:prod", "env:staging", "tier:frontend"],
}


def es_request(method, path, body=None, content_type="application/json"):
    url = f"{ES_ENDPOINT}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode() if isinstance(body, dict) else body
    headers = {**HEADERS}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        print(f"  HTTP {e.code}: {err_body[:300]}")
        try:
            return json.loads(err_body) if err_body else {}
        except json.JSONDecodeError:
            return {"error": {"status": e.code, "reason": err_body[:300] or f"HTTP {e.code}"}}


# ---------------------------------------------------------------------------
# Metric extraction from compiled YAMLs
# ---------------------------------------------------------------------------

def extract_metrics_from_yaml(yaml_dir: str) -> dict[str, str]:
    """Extract metric names and classify as counter/gauge from compiled YAML.

    Returns {metric_name: "counter" | "gauge"}.
    """
    metrics: dict[str, str] = {}
    yaml_path = Path(yaml_dir)

    if not yaml_path.exists():
        print(f"YAML directory not found: {yaml_dir}")
        return metrics

    for f in sorted(yaml_path.glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text())
        except Exception as exc:
            print(f"  Skipping unreadable YAML {f.name}: {exc}")
            continue

        for dash in doc.get("dashboards", []):
            _scan_panels(dash.get("panels", []), metrics)

    return metrics


def _scan_panels(panels: list, metrics: dict[str, str]) -> None:
    for panel in panels:
        esql = panel.get("esql", {})
        if isinstance(esql, dict):
            _extract_from_query(esql.get("query", ""), metrics)

        lens = panel.get("lens", {})
        if isinstance(lens, dict):
            _extract_lens_metrics(lens, metrics)

        section = panel.get("section", {})
        if isinstance(section, dict):
            _scan_panels(section.get("panels", []), metrics)


def _extract_lens_metrics(lens: dict, metrics: dict[str, str]) -> None:
    """Extract metric fields from Lens panel schema (primary, metrics, etc.)."""
    skip = {"*", "time_bucket", "@timestamp", ""}

    def _add(field: str, agg: str) -> None:
        if field in skip:
            return
        mtype = _classify_metric(field, agg)
        if field not in metrics:
            metrics[field] = mtype
        elif metrics[field] == "gauge" and mtype == "counter":
            metrics[field] = "counter"

    primary = lens.get("primary", {})
    if isinstance(primary, dict) and primary.get("field"):
        _add(primary["field"], primary.get("aggregation", "avg"))

    metric_cfg = lens.get("metric", {})
    if isinstance(metric_cfg, dict):
        prim = metric_cfg.get("primary", {})
        if isinstance(prim, dict) and prim.get("field"):
            _add(prim["field"], prim.get("aggregation", "avg"))

    for m in lens.get("metrics", []):
        if isinstance(m, dict) and m.get("field"):
            _add(m["field"], m.get("aggregation", "avg"))

    old_mf = lens.get("metric_field", "")
    if old_mf and old_mf not in skip:
        _add(old_mf, lens.get("aggregation", "avg"))


def _extract_lens_dimensions(lens: dict, dims: set[str]) -> None:
    """Extract dimension/breakdown fields from Lens panel schema."""
    skip = {"@timestamp", "time_bucket", "BUCKET", "value", "count", "*", ""}

    def _add(field: str) -> None:
        if field and field not in skip and not field.startswith("?"):
            dims.add(field)

    bd = lens.get("breakdown", {})
    if isinstance(bd, dict) and bd.get("field"):
        _add(bd["field"])

    for b in lens.get("breakdowns", []):
        if isinstance(b, dict) and b.get("field"):
            _add(b["field"])

    dim = lens.get("dimension", {})
    if isinstance(dim, dict) and dim.get("field"):
        f = dim["field"]
        if f != "@timestamp":
            _add(f)

    for gb in lens.get("group_by", []):
        if isinstance(gb, str):
            _add(gb)
        elif isinstance(gb, dict) and gb.get("field"):
            _add(gb["field"])


def _extract_from_query(query: str, metrics: dict[str, str]) -> None:
    agg_pattern = re.compile(
        rf'(AVG|SUM|MAX|MIN|COUNT|RATE|IRATE)\(\s*({_IDENT_RE})\s*\)|PERCENTILE\(\s*({_IDENT_RE})\s*,',
        re.IGNORECASE,
    )
    for match in agg_pattern.finditer(query):
        agg_fn = match.group(1) or "PERCENTILE"
        metric_name = match.group(2) or match.group(3) or ""
        metric_name = _strip_identifier_quotes(metric_name)
        if metric_name in ("*", "time_bucket", "BUCKET"):
            continue
        mtype = _classify_metric(metric_name, agg_fn)
        if metric_name not in metrics:
            metrics[metric_name] = mtype
        elif metrics[metric_name] == "gauge" and mtype == "counter":
            metrics[metric_name] = "counter"


def extract_dimensions_from_yaml(yaml_dir: str) -> set[str]:
    """Extract non-metric field names used in BY and WHERE clauses."""
    dims: set[str] = set()
    yaml_path = Path(yaml_dir)
    if not yaml_path.exists():
        return dims

    for f in sorted(yaml_path.glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text())
        except Exception as exc:
            print(f"  Skipping unreadable YAML {f.name}: {exc}")
            continue
        for dash in doc.get("dashboards", []):
            _scan_dimensions(dash.get("panels", []), dims)
            for ctrl in dash.get("controls", []):
                field = ctrl.get("field", "")
                if field and not field.startswith("@"):
                    dims.add(field)
    return dims


def _scan_dimensions(panels: list, dims: set[str]) -> None:
    for panel in panels:
        esql = panel.get("esql", {})
        if isinstance(esql, dict):
            _extract_dims_from_query(esql.get("query", ""), dims)
        lens = panel.get("lens", {})
        if isinstance(lens, dict):
            _extract_lens_dimensions(lens, dims)
        section = panel.get("section", {})
        if isinstance(section, dict):
            _scan_dimensions(section.get("panels", []), dims)


_SKIP_DIMS = {
    "@timestamp", "time_bucket", "BUCKET", "value", "count", "*",
    "message", "log.level", "http.url", "http.status_code",
}


def _extract_dims_from_query(query: str, dims: set[str]) -> None:
    by_pattern = re.compile(r'\bBY\b\s+(.+?)(?=\n\s*\||\|$|$)', re.IGNORECASE | re.DOTALL)
    where_pattern = re.compile(
        rf'({_IDENT_RE})\s*(?:==|!=|>=|<=|>|<|LIKE|NOT LIKE)\s*(?:\"|\(|-?\d|TRUE\b|FALSE\b)',
        re.IGNORECASE | re.DOTALL,
    )
    agg_pattern = re.compile(
        rf'(?:AVG|SUM|MAX|MIN|COUNT|RATE|IRATE)\(\s*({_IDENT_RE})\s*\)|PERCENTILE\(\s*({_IDENT_RE})\s*,',
        re.IGNORECASE,
    )

    metric_fields = {
        _strip_identifier_quotes(m.group(1) or m.group(2) or "")
        for m in agg_pattern.finditer(query)
        if (m.group(1) or m.group(2))
    }

    for m in by_pattern.finditer(query):
        by_clause = m.group(1)
        depth = 0
        parts: list[str] = []
        current: list[str] = []
        for ch in by_clause:
            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append("".join(current))

        for part in parts:
            part = part.strip()
            if "=" in part:
                rhs = part.split("=", 1)[1].strip()
                if "BUCKET(" not in rhs.upper() and "(" not in rhs:
                    dims.add(_strip_identifier_quotes(rhs))
            elif "(" not in part and part not in _SKIP_DIMS:
                dims.add(_strip_identifier_quotes(part))

    for m in where_pattern.finditer(query):
        field_name = _strip_identifier_quotes(m.group(1))
        if field_name not in _SKIP_DIMS and field_name not in metric_fields:
            dims.add(field_name)

    dims -= _SKIP_DIMS
    dims -= metric_fields


def _dimension_values(field_name: str) -> list[str]:
    """Return realistic values for a dimension field."""
    base = field_name.rsplit(".", 1)[-1].lower().replace("_", "")
    for key, vals in DIMENSION_VALUE_POOLS.items():
        if key.replace("_", "") in base or base in key.replace("_", ""):
            return vals
    return [f"{field_name}-val-{i}" for i in range(1, 6)]


def _strip_identifier_quotes(field_name: str) -> str:
    field_name = field_name.strip().rstrip("|").strip()
    if not field_name:
        return field_name
    parts = []
    for part in field_name.split("."):
        part = part.strip()
        if part.startswith("`") and part.endswith("`") and len(part) >= 2:
            part = part[1:-1].replace("``", "`")
        parts.append(part)
    return ".".join(parts)


def _classify_metric(name: str, agg_fn: str) -> str:
    name_lower = name.lower()
    if agg_fn in ("RATE", "IRATE"):
        return "counter"
    for hint in COUNTER_HINTS:
        if hint in name_lower:
            return "counter"
    for hint in GAUGE_HINTS:
        if hint in name_lower:
            return "gauge"
    return "gauge"


# ---------------------------------------------------------------------------
# Realistic value generators
# ---------------------------------------------------------------------------

def diurnal(hour_of_day):
    return 0.5 + 0.5 * math.sin(math.pi * (hour_of_day - 4) / 12)


def gauge_val(base, amplitude, hour, noise_frac=0.1):
    d = diurnal(hour)
    noise = random.gauss(0, base * noise_frac) if noise_frac else 0
    return max(0, base + amplitude * d + noise)


def counter_incr(rate_per_sec, interval, hour):
    d = diurnal(hour)
    effective_rate = rate_per_sec * (0.3 + 0.7 * d)
    return max(0, random.gauss(effective_rate * interval, effective_rate * interval * 0.1))


# ---------------------------------------------------------------------------
# Index template
# ---------------------------------------------------------------------------

def setup_index_template(metrics: dict[str, str], dimension_fields: set[str]):
    print("Setting up index template...")

    props: dict[str, Any] = {
        "@timestamp": {"type": "date"},
        "host.name": {"type": "keyword", "time_series_dimension": True},
        "service.name": {"type": "keyword", "time_series_dimension": True},
        "migration.chunk_id": {"type": "keyword", "time_series_dimension": True},
        "k8s.namespace.name": {"type": "keyword"},
        "k8s.pod.name": {"type": "keyword"},
        "k8s.node.name": {"type": "keyword"},
        "container.name": {"type": "keyword"},
        "container.id": {"type": "keyword"},
        "kubernetes.cluster.name": {"type": "keyword"},
        "kubernetes.namespace": {"type": "keyword"},
        "kubernetes.pod.name": {"type": "keyword"},
        "kubernetes.deployment.name": {"type": "keyword"},
        "log.level": {"type": "keyword"},
        "data_stream.type": {"type": "constant_keyword", "value": "metrics"},
        "data_stream.dataset": {"type": "constant_keyword", "value": "otel"},
        "data_stream.namespace": {"type": "constant_keyword", "value": "default"},
    }

    for dim in sorted(dimension_fields):
        if dim not in props and "." not in dim:
            props[dim] = {"type": "keyword"}
        elif dim not in props and "." in dim:
            parts = dim.split(".")
            if parts[0] in ("data_stream",):
                continue
            props[dim] = {"type": "keyword"}

    for metric_name in sorted(metrics):
        props[metric_name] = {"type": "double"}

    print(f"  Dimension fields added to template: {len(dimension_fields)}")

    template = {
        "index_patterns": [INDEX_NAME],
        "data_stream": {},
        "priority": 500,
        "template": {
            "settings": {
                "index": {"codec": "best_compression"},
            },
            "mappings": {
                "properties": props,
            },
        },
    }

    result = es_request("PUT", "/_index_template/datadog-dashboard-metrics", template)
    print(f"  Template: {result.get('acknowledged', result)}")


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def generate_and_ingest(metrics: dict[str, str], dimension_fields: set[str]) -> int:
    total_points = int(DATA_HOURS * 3600 // INTERVAL_SEC)
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(hours=DATA_HOURS)

    counter_accumulators: dict[str, dict[str, float]] = {}
    for m in metrics:
        if metrics[m] == "counter":
            counter_accumulators[m] = {h: 0.0 for h in HOSTS}

    dim_values: dict[str, list[str]] = {}
    for dim in dimension_fields:
        dim_values[dim] = _dimension_values(dim)

    print(f"\nGenerating {total_points} time points × {len(metrics)} metrics × {len(HOSTS)} hosts")
    print(f"  Time range: {start.isoformat()} → {now.isoformat()}")
    print(f"  Counters: {sum(1 for v in metrics.values() if v == 'counter')}")
    print(f"  Gauges: {sum(1 for v in metrics.values() if v == 'gauge')}")
    print(f"  Dimension fields: {len(dim_values)}")

    batch: list[str] = []
    total_docs = 0
    batches_queue: list[bytes] = []
    total_bulk_errors = 0

    metric_list = sorted(metrics.keys())
    metric_chunks = [
        metric_list[i:i + METRICS_PER_DOC]
        for i in range(0, len(metric_list), METRICS_PER_DOC)
    ]
    print(f"  Metrics per doc: {METRICS_PER_DOC} ({len(metric_chunks)} chunk(s) per host/time step)")

    for t_idx in range(total_points):
        ts = start + datetime.timedelta(seconds=t_idx * INTERVAL_SEC)
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        hour = ts.hour + ts.minute / 60.0

        for host_idx, host in enumerate(HOSTS):
            ns = NAMESPACES[host_idx % len(NAMESPACES)]
            svc = SERVICES[host_idx % len(SERVICES)]

            base_doc: dict[str, Any] = {
                "@timestamp": ts_str,
                "host.name": host,
                "service.name": svc,
                "k8s.namespace.name": ns,
                "k8s.pod.name": f"{svc}-{host}-pod",
                "k8s.node.name": host,
                "container.name": f"{svc}-container",
                "container.id": f"{svc}-{host}-cid",
                "kubernetes.cluster.name": "migration-cluster",
                "kubernetes.namespace": ns,
                "kubernetes.pod.name": f"{svc}-{host}-pod",
                "kubernetes.deployment.name": svc,
                "log.level": random.choice(["info", "warn", "error", "debug"]),
            }

            for dim, vals in dim_values.items():
                if dim.startswith("data_stream."):
                    continue
                base_doc[dim] = vals[(host_idx + t_idx) % len(vals)]

            multi_chunk = len(metric_chunks) > 1
            for chunk_idx, metric_chunk in enumerate(metric_chunks):
                doc = dict(base_doc)
                if multi_chunk:
                    doc["migration.chunk_id"] = f"chunk-{chunk_idx}"
                for metric_name in metric_chunk:
                    mtype = metrics[metric_name]
                    base = hash(metric_name) % 1000 + 10
                    amplitude = base * 0.3

                    if mtype == "counter":
                        incr = counter_incr(base / 100, INTERVAL_SEC, hour)
                        counter_accumulators[metric_name][host] += incr
                        doc[metric_name] = round(counter_accumulators[metric_name][host], 2)
                    else:
                        doc[metric_name] = round(gauge_val(base, amplitude, hour), 4)

                action = json.dumps({"create": {"_index": INDEX_NAME}})
                payload = json.dumps(doc)
                batch.append(action)
                batch.append(payload)
                total_docs += 1

                if total_docs % BATCH_DOC_LIMIT == 0:
                    body = "\n".join(batch) + "\n"
                    batches_queue.append(body.encode())
                    batch = []

                    if len(batches_queue) >= BULK_WORKERS * 2:
                        total_bulk_errors += _flush_batches(batches_queue)
                        batches_queue = []

        if t_idx > 0 and t_idx % 100 == 0:
            pct = t_idx / total_points * 100
            print(f"  Progress: {pct:.0f}% ({total_docs:,} docs)")

    if batch:
        body = "\n".join(batch) + "\n"
        batches_queue.append(body.encode())

    if batches_queue:
        total_bulk_errors += _flush_batches(batches_queue)

    print(f"\n  Total docs ingested: {total_docs:,}")
    return total_bulk_errors


def _flush_batches(batches: list[bytes]) -> int:
    def _send(body):
        result = es_request("POST", "/_bulk", body, content_type="application/x-ndjson")
        errors = result.get("errors", False)
        if errors:
            items = result.get("items", [])
            err_count = sum(1 for i in items if "error" in i.get("create", i.get("index", {})))
            return err_count
        return 0

    with ThreadPoolExecutor(max_workers=BULK_WORKERS) as pool:
        futures = {pool.submit(_send, b): i for i, b in enumerate(batches)}
        total_errs = 0
        for fut in as_completed(futures):
            total_errs += fut.result()
        if total_errs:
            print(f"  Bulk errors: {total_errs}")
        return total_errs


# ---------------------------------------------------------------------------
# Log data generation
# ---------------------------------------------------------------------------

def setup_logs_template(dimension_fields: set[str]):
    """Ensure the logs index has proper field mappings for log queries."""
    props: dict[str, Any] = {
        "@timestamp": {"type": "date"},
        "host.name": {"type": "keyword"},
        "service.name": {"type": "keyword"},
        "log.level": {"type": "keyword"},
        "message": {"type": "text"},
        "http.url": {"type": "keyword"},
        "http.status_code": {"type": "integer"},
        "container.name": {"type": "keyword"},
        "source": {"type": "keyword"},
        "data_stream.type": {"type": "constant_keyword", "value": "logs"},
        "data_stream.dataset": {"type": "constant_keyword", "value": "generic"},
        "data_stream.namespace": {"type": "constant_keyword", "value": "default"},
    }
    for dim in sorted(dimension_fields):
        if dim.startswith("data_stream.") or dim in props:
            continue
        props[dim] = {"type": "keyword"}

    template = {
        "index_patterns": [LOGS_INDEX_NAME],
        "data_stream": {},
        "priority": 500,
        "template": {
            "settings": {"index": {"codec": "best_compression"}},
            "mappings": {
                "properties": props,
            },
        },
    }
    result = es_request("PUT", "/_index_template/datadog-dashboard-logs", template)
    print(f"  Log template: {result.get('acknowledged', result)}")


def generate_logs(dimension_fields: set[str]) -> int:
    total_points = int(min(DATA_HOURS * 60, 1000))
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(hours=DATA_HOURS)

    print(f"\nGenerating {total_points} log entries...")

    log_sources = ["apache", "nginx", "consul", "envoy", "etcd", "haproxy",
                   "istio", "mongodb", "mysql", "postgres", "rabbitmq", "redis",
                   "elasticsearch", "kafka", "web", "docker", "kubernetes"]
    log_levels = ["info", "warn", "error", "debug"]
    log_messages = [
        "Connection accepted from client",
        "Request processed successfully",
        "Timeout waiting for upstream",
        "Authentication failed for user",
        "Rate limit exceeded",
        "Cache miss for key",
        "Replication lag detected",
        "Health check passed",
        "Connection pool exhausted",
        "Query execution completed",
    ]

    dim_values = {dim: _dimension_values(dim) for dim in dimension_fields if not dim.startswith("data_stream.")}
    batch: list[str] = []
    for i in range(total_points):
        ts = start + datetime.timedelta(seconds=i * (DATA_HOURS * 3600 / total_points))
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        host = random.choice(HOSTS)
        source = random.choice(log_sources)
        level = random.choices(log_levels, weights=[50, 25, 15, 10])[0]

        doc = {
            "@timestamp": ts_str,
            "host.name": host,
            "source": source,
            "service.name": source,
            "log.level": level,
            "message": f"[{source}] {random.choice(log_messages)}",
            "http.url": f"/api/{random.choice(['users', 'data', 'health', 'metrics'])}",
            "http.status_code": random.choice([200, 200, 200, 201, 301, 400, 404, 500]),
            "container.name": f"{source}-container",
        }
        for dim, vals in dim_values.items():
            doc.setdefault(dim, vals[i % len(vals)])

        action = json.dumps({"create": {"_index": LOGS_INDEX_NAME}})
        payload = json.dumps(doc)
        batch.append(action)
        batch.append(payload)

    if batch:
        body = "\n".join(batch) + "\n"
        result = es_request("POST", "/_bulk", body.encode(), content_type="application/x-ndjson")
        errs = result.get("errors", False)
        err_count = 0
        if errs:
            items = result.get("items", [])
            err_count = sum(1 for it in items if "error" in it.get("create", it.get("index", {})))
            print(f"  Log bulk errors: {err_count}")
        print(f"  Log entries ingested: {total_points}")
        return err_count
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== Datadog Migration — Serverless Data Setup ===\n")

    print(f"ES endpoint: {ES_ENDPOINT[:50]}...")
    print(f"YAML dir: {DASHBOARD_YAML_DIR}")
    print(f"Field profile: {FIELD_PROFILE}")
    print(f"Data hours: {DATA_HOURS}, interval: {INTERVAL_SEC}s")

    metrics = extract_metrics_from_yaml(DASHBOARD_YAML_DIR)
    if not metrics:
        print("\nNo metrics found in compiled YAML. Run the migration first:")
        print("  python -m observability_migration.adapters.source.datadog.cli --source files --input-dir infra/datadog/dashboards/integrations --output-dir datadog_migration_output/integrations --field-profile otel --compile")
        sys.exit(1)

    print(f"\nExtracted {len(metrics)} unique metrics")
    counters = sum(1 for v in metrics.values() if v == "counter")
    gauges = sum(1 for v in metrics.values() if v == "gauge")
    print(f"  Counters: {counters}, Gauges: {gauges}")

    dimensions = extract_dimensions_from_yaml(DASHBOARD_YAML_DIR)

    monitor_artifact = discover_monitor_artifact(DASHBOARD_YAML_DIR)
    if monitor_artifact is not None:
        field_map = load_profile(FIELD_PROFILE)
        monitor_metrics, monitor_dimensions = load_monitor_seed_requirements(
            monitor_artifact,
            field_map,
        )
        for metric_name, metric_type in monitor_metrics.items():
            if metric_name not in metrics:
                metrics[metric_name] = metric_type
            elif metrics[metric_name] == "gauge" and metric_type == "counter":
                metrics[metric_name] = "counter"
        dimensions |= monitor_dimensions
        print(
            f"\nLoaded monitor seed requirements from {monitor_artifact}: "
            f"{len(monitor_metrics)} metrics, {len(monitor_dimensions)} dimensions"
        )

    known_fields = {"@timestamp", "host.name", "service.name",
                    "k8s.namespace.name", "k8s.pod.name", "k8s.node.name",
                    "container.name", "container.id"} | set(metrics.keys())
    dimensions -= known_fields
    print(f"\nExtracted {len(dimensions)} dimension fields from queries")
    for d in sorted(dimensions)[:15]:
        print(f"  {d}")
    if len(dimensions) > 15:
        print(f"  ... and {len(dimensions) - 15} more")

    if RECREATE_DATA_STREAMS:
        _delete_data_stream(LOGS_INDEX_NAME)
        _delete_data_stream(INDEX_NAME)

    setup_index_template(metrics, dimensions)
    setup_logs_template(dimensions)
    metric_errors = generate_and_ingest(metrics, dimensions)
    log_errors = generate_logs(dimensions)

    if metric_errors or log_errors:
        print(
            f"\nData setup finished with ingest errors: metric_bulk_errors={metric_errors}, "
            f"log_bulk_errors={log_errors}"
        )
        sys.exit(1)

    print("\n=== Data setup complete ===")


def _delete_data_stream(index_name: str) -> None:
    exists = es_request("GET", f"/_data_stream/{index_name}")
    if "error" in exists:
        return
    result = es_request("DELETE", f"/_data_stream/{index_name}")
    print(f"  Recreated {index_name}: {result.get('acknowledged', result)}")


if __name__ == "__main__":
    main()
