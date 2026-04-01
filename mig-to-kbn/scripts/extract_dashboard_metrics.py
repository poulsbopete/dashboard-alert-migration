#!/usr/bin/env python3
"""
Scans all compiled dashboard YAML files, extracts every metric field and label
referenced in ES|QL queries, classifies metrics as counter vs gauge, and writes
/tmp/dashboard_metrics.json consumed by setup_serverless_data.py.

Strategy:
  - Only extract field names that appear as ARGUMENTS to aggregation functions
    (AVG, SUM, RATE, IRATE, etc.) -- these are the real Elasticsearch fields.
  - Exclude computed alias names (left-side of `alias = FUNC(field)` in STATS/EVAL).
  - Extract labels from WHERE and BY clauses.
"""

import json
import os
import re
import sys
import yaml
from pathlib import Path

try:
    import promql_parser  # pyright: ignore[reportMissingImports]
except ImportError:  # pragma: no cover - exercised in environments without the optional dep
    promql_parser = None


COUNTER_FUNCTIONS = {"RATE", "IRATE", "INCREASE"}
GAUGE_FUNCTIONS = {"AVG", "SUM", "MAX", "MIN", "MEDIAN", "COUNT_DISTINCT",
                   "PERCENTILE", "COUNT", "LAST", "FIRST", "STDDEV",
                   "AVG_OVER_TIME", "MAX_OVER_TIME"}
PROMQL_COUNTER_FUNCTIONS = {"rate", "irate", "increase"}
SPECIAL_METRIC_NAMES = {"up", "ALERTS"}

# Fields that are structural, not metrics
NON_METRIC_FIELDS = {
    "@timestamp", "time_bucket", "computed_value", "_tstart", "_tend",
    "?_tstart", "?_tend",
}

# Regex to extract function calls with their first argument (the actual field)
# Matches: FUNC(field_name) or FUNC(field_name, param2, ...)
FUNC_CALL_RE = re.compile(
    r"\b("
    r"RATE|IRATE|INCREASE|AVG|SUM|MAX|MIN|MEDIAN|COUNT_DISTINCT|"
    r"PERCENTILE|COUNT|LAST|FIRST|STDDEV|AVG_OVER_TIME|MAX_OVER_TIME"
    r")\s*\(\s*"
    r"([a-zA-Z_][a-zA-Z0-9_]*)"  # first argument = actual field
    r"(?:\s*,\s*[^)]*)?",
    re.IGNORECASE,
)

# Known label/dimension field names
KNOWN_LABELS = {
    "job", "instance", "namespace", "node", "pod", "device",
    "fstype", "mountpoint", "mode", "cpu", "phase", "state",
    "handler", "receiver", "exporter", "name", "pool", "area",
    "id", "level", "status", "uri", "application", "operstate",
    "condition", "resource", "reason", "origin_prometheus",
    "nodename", "processor", "hpa", "integration",
    "service_instance_id", "quantile", "alertstate", "exception",
    "component", "tag", "path", "qos_class", "msg_type", "slice",
    "scrape_job", "proto", "rcode", "zone", "qtype", "server",
    "grpc_service", "grpc_type", "datname", "command", "topic",
    "protocol", "queue", "vhost", "destination_service",
    "destination_workload", "destination_workload_namespace",
    "reporter", "source_workload", "entrypoint", "code",
    "exported_namespace", "action", "type", "le",
    "service", "cmd", "db", "release", "activity",
    "container", "image",
    "alertname", "severity", "container_id", "core", "nic",
    "persistentvolumeclaim", "power_supply",
}


def is_real_metric(name: str) -> bool:
    """Heuristic: real Prometheus metric names have underscores and aren't labels."""
    if name in NON_METRIC_FIELDS or name in KNOWN_LABELS:
        return False
    if name.startswith("?"):
        return False
    if name in SPECIAL_METRIC_NAMES:
        return True
    if "_" not in name:
        return False
    # Must look like a prometheus metric (lowercase with underscores, may have CamelCase suffixes)
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]+$', name):
        return False
    return True


def _extract_balanced_segment(text: str, start: int, open_ch: str = "(", close_ch: str = ")") -> tuple[str, int] | tuple[None, None]:
    """Return the balanced substring contents and the closing index."""
    if start >= len(text) or text[start] != open_ch:
        return None, None
    depth = 1
    quote = ""
    escaped = False
    pieces: list[str] = []
    for idx in range(start + 1, len(text)):
        ch = text[idx]
        if quote:
            pieces.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {'"', "'"}:
            quote = ch
            pieces.append(ch)
            continue
        if ch == open_ch:
            depth += 1
            pieces.append(ch)
            continue
        if ch == close_ch:
            depth -= 1
            if depth == 0:
                return "".join(pieces), idx
            pieces.append(ch)
            continue
        pieces.append(ch)
    return None, None


def _extract_promql_command_expr(query: str) -> str | None:
    """Extract the PromQL expression from a `PROMQL ... value=(...)` command."""
    promql_match = re.search(r"\bPROMQL\b", query, flags=re.IGNORECASE)
    if not promql_match:
        return None
    value_match = re.search(r"\bvalue\s*=\s*", query[promql_match.end():], flags=re.IGNORECASE)
    if not value_match:
        return None
    start = promql_match.end() + value_match.end()
    while start < len(query) and query[start].isspace():
        start += 1
    if start >= len(query):
        return None
    if query[start] == "(":
        expr, _ = _extract_balanced_segment(query, start)
        return expr.strip() if expr else None
    end = query.find("\n", start)
    if end == -1:
        end = len(query)
    return query[start:end].strip()


def _collect_promql_matcher_labels(matchers_obj, labels: set[str]) -> None:
    if not matchers_obj:
        return
    for attr in ("matchers", "or_matchers"):
        matchers = getattr(matchers_obj, attr, None) or []
        for matcher in matchers:
            if isinstance(matcher, (list, tuple)):
                for nested in matcher:
                    name = str(getattr(nested, "name", "") or "")
                    if name:
                        labels.add(name)
                continue
            name = str(getattr(matcher, "name", "") or "")
            if name:
                labels.add(name)


def _collect_promql_modifier_labels(modifier, labels: set[str]) -> None:
    if not modifier:
        return
    for attr in ("labels", "include", "exclude"):
        values = getattr(modifier, attr, None) or []
        for value in values:
            name = str(value or "")
            if name:
                labels.add(name)


def _walk_promql_ast(node, counters: set[str], gauges: set[str], labels: set[str], counter_context: bool = False) -> None:
    if node is None:
        return

    node_type = type(node).__name__
    if node_type == "VectorSelector":
        metric = str(getattr(node, "name", "") or "")
        if is_real_metric(metric):
            if counter_context:
                counters.add(metric)
            else:
                gauges.add(metric)
        _collect_promql_matcher_labels(getattr(node, "matchers", None), labels)
        return

    if node_type == "MatrixSelector":
        selector = getattr(node, "vector_selector", None) or getattr(node, "vs", None)
        _walk_promql_ast(selector, counters, gauges, labels, counter_context)
        return

    if node_type == "Call":
        func_name = str(getattr(getattr(node, "func", None), "name", "") or "").lower()
        child_counter_context = counter_context or func_name in PROMQL_COUNTER_FUNCTIONS
        for arg in getattr(node, "args", None) or []:
            _walk_promql_ast(arg, counters, gauges, labels, child_counter_context)
        return

    if node_type == "AggregateExpr":
        _collect_promql_modifier_labels(getattr(node, "modifier", None), labels)
        _walk_promql_ast(getattr(node, "expr", None), counters, gauges, labels, counter_context)
        _walk_promql_ast(getattr(node, "param", None), counters, gauges, labels, counter_context)
        return

    if node_type == "BinaryExpr":
        _collect_promql_modifier_labels(getattr(node, "modifier", None), labels)
        _walk_promql_ast(getattr(node, "lhs", None), counters, gauges, labels, counter_context)
        _walk_promql_ast(getattr(node, "rhs", None), counters, gauges, labels, counter_context)
        return

    if node_type in {"ParenExpr", "UnaryExpr", "SubqueryExpr"}:
        _walk_promql_ast(getattr(node, "expr", None), counters, gauges, labels, counter_context)


def extract_from_promql(promql_expr: str) -> tuple[set[str], set[str], set[str]]:
    """Extract metrics and labels from a PromQL expression using the AST parser."""
    counters: set[str] = set()
    gauges: set[str] = set()
    labels: set[str] = set()
    if not promql_expr or promql_parser is None:
        return counters, gauges, labels
    try:
        ast = promql_parser.parse(promql_expr)
    except Exception:
        return counters, gauges, labels
    _walk_promql_ast(ast, counters, gauges, labels)
    return counters, gauges, labels


def extract_from_query(query: str) -> tuple[set[str], set[str], set[str]]:
    """
    Extract counters, gauges, and labels from a single ES|QL query string.
    Only captures fields that appear as arguments to aggregation functions.
    """
    counters: set[str] = set()
    gauges: set[str] = set()
    labels: set[str] = set()

    # Extract fields from function calls only
    for match in FUNC_CALL_RE.finditer(query):
        func = match.group(1).upper()
        field = match.group(2)
        if not is_real_metric(field):
            continue
        if func in COUNTER_FUNCTIONS:
            counters.add(field)
        elif func in GAUGE_FUNCTIONS:
            gauges.add(field)

    # Extract labels from WHERE clauses
    where_parts = re.split(r'\bWHERE\b', query, flags=re.IGNORECASE)
    for i, part in enumerate(where_parts):
        if i == 0:
            continue
        clause = re.split(r'\b(?:STATS|EVAL|SORT|LIMIT|KEEP)\b', part, flags=re.IGNORECASE)[0]
        for word in re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', clause):
            if word in KNOWN_LABELS:
                labels.add(word)

    # Extract labels from BY clauses
    by_parts = re.split(r'\bBY\b', query, flags=re.IGNORECASE)
    for i, part in enumerate(by_parts):
        if i == 0:
            continue
        clause = re.split(r'\b(?:EVAL|SORT|LIMIT|KEEP|WHERE|STATS)\b', part, flags=re.IGNORECASE)[0]
        for word in re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', clause):
            if word in KNOWN_LABELS:
                labels.add(word)

    promql_expr = _extract_promql_command_expr(query)
    if promql_expr:
        promql_counters, promql_gauges, promql_labels = extract_from_promql(promql_expr)
        counters |= promql_counters
        gauges |= promql_gauges
        labels |= promql_labels

    return counters, gauges, labels


def extract_queries_from_panel(panel: dict, queries: list[str]):
    """Recursively extract all ES|QL query strings from a panel."""
    if isinstance(panel, dict):
        esql = panel.get("esql")
        if isinstance(esql, dict):
            q = esql.get("query")
            if q:
                queries.append(q)
        section = panel.get("section")
        if isinstance(section, dict):
            for p in section.get("panels", []):
                extract_queries_from_panel(p, queries)
        for p in panel.get("panels", []):
            extract_queries_from_panel(p, queries)


def extract_from_yaml(yaml_path: str) -> tuple[set[str], set[str], set[str]]:
    """Extract all metrics and labels from a single YAML dashboard file."""
    all_counters: set[str] = set()
    all_gauges: set[str] = set()
    all_labels: set[str] = set()

    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)
    if not data:
        return all_counters, all_gauges, all_labels

    dashboards = data.get("dashboards", [])
    if not dashboards:
        return all_counters, all_gauges, all_labels

    queries: list[str] = []
    for dashboard in dashboards:
        for panel in dashboard.get("panels", []):
            extract_queries_from_panel(panel, queries)

    for query in queries:
        c, g, l = extract_from_query(query)
        all_counters |= c
        all_gauges |= g
        all_labels |= l

    return all_counters, all_gauges, all_labels


def main():
    yaml_dir = sys.argv[1] if len(sys.argv) > 1 else "migration_output_serverless_scoped/yaml"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/dashboard_metrics.json"
    yaml_dir = Path(yaml_dir)

    if not yaml_dir.exists():
        print(f"Error: directory {yaml_dir} does not exist")
        sys.exit(1)

    all_counters: set[str] = set()
    all_gauges: set[str] = set()
    all_labels: set[str] = set()

    yaml_files = sorted(yaml_dir.glob("*.yaml"))
    print(f"Scanning {len(yaml_files)} dashboard YAML files in {yaml_dir}...")

    per_dashboard: dict[str, dict] = {}
    for yf in yaml_files:
        c, g, l = extract_from_yaml(str(yf))
        all_counters |= c
        all_gauges |= g
        all_labels |= l
        if c or g:
            per_dashboard[yf.stem] = {
                "counters": sorted(c),
                "gauges": sorted(g),
                "labels": sorted(l),
            }

    # If a metric appears in both, counter wins (RATE/IRATE is stronger signal)
    overlap = all_counters & all_gauges
    if overlap:
        print(f"\n  {len(overlap)} metrics used in both counter and gauge contexts:")
        for m in sorted(overlap):
            print(f"    {m} (classifying as counter)")
        all_gauges -= overlap

    for s in (all_counters, all_gauges):
        s -= NON_METRIC_FIELDS

    result = {
        "counters": sorted(all_counters),
        "gauges": sorted(all_gauges),
    }

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nExtracted metrics (from function arguments only):")
    print(f"  Counters: {len(all_counters)}")
    print(f"  Gauges:   {len(all_gauges)}")
    print(f"  Labels:   {len(all_labels)}")
    print(f"  Total:    {len(all_counters) + len(all_gauges)}")
    print(f"\nWrote {output_path}")

    # --- Gap analysis against the generator's EXTRA_* sets ---
    print(f"\n{'='*60}")
    print(f"Per-Dashboard Breakdown:")
    print(f"{'='*60}")
    for name, info in sorted(per_dashboard.items()):
        total = len(info["counters"]) + len(info["gauges"])
        print(f"  {name}: {len(info['counters'])}C + {len(info['gauges'])}G = {total}")

    # Compare against generator's declared sets
    print(f"\n{'='*60}")
    print(f"Gap Analysis vs setup_serverless_data.py:")
    print(f"{'='*60}")
    try:
        gen_path = Path(__file__).parent / "setup_serverless_data.py"
        gen_text = gen_path.read_text()
        # Extract EXTRA_COUNTER_METRICS
        m = re.search(r'EXTRA_COUNTER_METRICS\s*=\s*\{([^}]+)\}', gen_text, re.DOTALL)
        gen_extra_counters = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()
        # Extract EXTRA_GAUGE_METRICS
        m = re.search(r'EXTRA_GAUGE_METRICS\s*=\s*\{([^}]+)\}', gen_text, re.DOTALL)
        gen_extra_gauges = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()

        gen_all = gen_extra_counters | gen_extra_gauges
        dashboard_all = all_counters | all_gauges

        in_dashboard_not_gen = dashboard_all - gen_all
        in_gen_not_dashboard = gen_all - dashboard_all

        if in_dashboard_not_gen:
            print(f"\n  Metrics in dashboards but NOT in generator EXTRA_* sets ({len(in_dashboard_not_gen)}):")
            print(f"  (These may still be covered by the base dashboard_metrics.json or generic generation)")
            for m in sorted(in_dashboard_not_gen):
                print(f"    + {m}")
        else:
            print(f"\n  All dashboard metrics are covered by the generator!")

        if in_gen_not_dashboard:
            print(f"\n  Metrics in generator EXTRA_* but not in dashboards ({len(in_gen_not_dashboard)}):")
            for m in sorted(in_gen_not_dashboard):
                print(f"    - {m}")
    except Exception as e:
        print(f"  Could not parse generator: {e}")


if __name__ == "__main__":
    main()
