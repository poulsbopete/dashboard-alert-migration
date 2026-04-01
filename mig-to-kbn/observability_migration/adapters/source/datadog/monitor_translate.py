"""Trusted Datadog monitor query translation for alert migration."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .field_map import FieldMapProfile
from .log_parser import log_ast_to_esql_where, log_ast_to_kql, parse_log_query
from .models import (
    LogAttributeFilter,
    LogBoolOp,
    LogNot,
    LogRange,
    LogTerm,
    LogWildcard,
    ScopeBoolOp,
    TagFilter,
    WidgetQuery,
)
from .query_parser import ParseError, parse_metric_query
from .translate import _esql_escape, _esql_identifier, _metric_scope_to_esql

_METRIC_MONITOR_RE = re.compile(
    r"^(?P<time_agg>\w+)\(last_(?P<window>\d+\s*[smhdw])\):"
    r"(?P<metric_query>.+?)\s*"
    r"(?P<comparator>>=|<=|==|!=|>|<)\s*"
    r"(?P<threshold>-?(?:\d+(?:\.\d+)?|\.\d+))\s*$",
    re.IGNORECASE,
)
_LOG_MONITOR_RE = re.compile(
    r'^logs\("(?P<search>(?:[^"\\]|\\.)*)"\)'
    r'(?:\.index\("(?P<index>(?:[^"\\]|\\.)*)"\))?'
    r'\.rollup\("(?P<rollup>[^"]+)"\)'
    r'\.last\("(?P<window>\d+\s*[smhdw])"\)\s*'
    r'(?P<comparator>>=|<=|==|!=|>|<)\s*'
    r'(?P<threshold>-?(?:\d+(?:\.\d+)?|\.\d+))\s*$',
    re.IGNORECASE,
)
_SUPPORTED_METRIC_TIME_AGGS = {"avg", "sum", "min", "max", "count", "last"}


@dataclass
class DatadogMonitorTranslation:
    translated_query: str = ""
    translated_query_provenance: str = ""
    group_by: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def translate_monitor_to_alert_query(
    monitor: dict[str, Any],
    field_map: FieldMapProfile,
) -> DatadogMonitorTranslation:
    """Translate supported Datadog monitor queries into trusted Kibana ES|QL."""
    monitor_type = str(monitor.get("type", "") or "").strip().lower()
    query = str(monitor.get("query", "") or "").strip()

    if monitor_type in {"metric alert", "query alert"}:
        return _translate_metric_monitor(query, field_map)
    if monitor_type == "log alert":
        return _translate_log_monitor(query, field_map)
    return DatadogMonitorTranslation()


def _translate_metric_monitor(
    raw_query: str,
    field_map: FieldMapProfile,
) -> DatadogMonitorTranslation:
    match = _METRIC_MONITOR_RE.fullmatch(raw_query)
    if not match:
        return DatadogMonitorTranslation()

    time_agg = str(match.group("time_agg") or "").lower()
    metric_query_text = str(match.group("metric_query") or "").strip()
    comparator = str(match.group("comparator") or "").strip()
    threshold = float(match.group("threshold"))

    if time_agg not in _SUPPORTED_METRIC_TIME_AGGS:
        return DatadogMonitorTranslation()

    try:
        metric_query = parse_metric_query(metric_query_text)
    except ParseError:
        return DatadogMonitorTranslation()

    if metric_query.functions or metric_query.as_rate or metric_query.as_count:
        return DatadogMonitorTranslation()
    if time_agg != metric_query.space_agg and time_agg != "last":
        return DatadogMonitorTranslation()

    metric_field = _resolve_metric_field(metric_query.metric, field_map)
    agg_expr = _metric_agg_expr(time_agg, metric_field)
    if not agg_expr:
        return DatadogMonitorTranslation()
    if _metric_caps_loaded(field_map) and not _metric_query_fields_are_usable(metric_query, metric_field, field_map):
        return DatadogMonitorTranslation()

    where_clauses = []
    for scope_item in metric_query.scope:
        clause = _metric_scope_to_esql(scope_item, field_map, context="metric")
        if clause:
            where_clauses.append(clause)

    lines = [f"FROM {field_map.metric_index}"]
    if where_clauses:
        lines.append(f"| WHERE {' AND '.join(where_clauses)}")

    group_by = [_esql_identifier(field_map.map_tag(tag, context="metric")) for tag in metric_query.group_by]
    if group_by:
        lines.append(f"| STATS value = {agg_expr} BY {', '.join(group_by)}")
    else:
        lines.append(f"| STATS value = {agg_expr}")
    lines.append(f"| WHERE value {comparator} {threshold}")

    return DatadogMonitorTranslation(
        translated_query="\n".join(lines),
        translated_query_provenance="translated_esql",
        group_by=group_by,
    )


def _translate_log_monitor(
    raw_query: str,
    field_map: FieldMapProfile,
) -> DatadogMonitorTranslation:
    match = _LOG_MONITOR_RE.fullmatch(raw_query)
    if not match:
        return DatadogMonitorTranslation()

    search = _unescape_monitor_string(str(match.group("search") or ""))
    index_name = _unescape_monitor_string(str(match.group("index") or ""))
    rollup = str(match.group("rollup") or "").lower().strip()
    comparator = str(match.group("comparator") or "").strip()
    threshold = float(match.group("threshold"))

    if rollup != "count":
        return DatadogMonitorTranslation()

    log_query = parse_log_query(search)
    tag_map = {key: field_map.map_tag(key, context="log") for key in field_map.tag_map}
    if _log_caps_loaded(field_map) and not _log_query_fields_are_usable(log_query.ast, field_map):
        return DatadogMonitorTranslation()
    where_clause = ""
    if _ast_has_free_text(log_query.ast):
        kql = log_ast_to_kql(log_query.ast, field_map=tag_map)
        if not kql or kql == "*":
            return DatadogMonitorTranslation()
        where_clause = f'KQL("{_esql_escape(kql)}")'
    else:
        where_clause = log_ast_to_esql_where(log_query.ast, tag_map)
        if not where_clause and search:
            return DatadogMonitorTranslation()

    lines = [f"FROM {field_map.logs_index}"]
    if where_clause:
        lines.append(f"| WHERE {where_clause}")
    lines.append("| STATS value = COUNT(*)")
    lines.append(f"| WHERE value {comparator} {threshold}")

    warnings: list[str] = []
    if index_name and index_name != "*":
        warnings.append("Datadog log index selection is approximated via the configured logs index")

    return DatadogMonitorTranslation(
        translated_query="\n".join(lines),
        translated_query_provenance="translated_esql",
        warnings=warnings,
    )


def _resolve_metric_field(dd_metric: str, field_map: FieldMapProfile) -> str:
    mapped_metric = field_map.map_metric(dd_metric)
    candidates = []
    if mapped_metric:
        candidates.append(mapped_metric)
    if dd_metric and dd_metric not in candidates:
        candidates.append(dd_metric)

    for candidate in candidates:
        if field_map.field_capability(candidate, context="metric"):
            return candidate
    return candidates[0] if candidates else dd_metric


def _metric_caps_loaded(field_map: FieldMapProfile) -> bool:
    return bool(field_map.metric_field_caps or field_map.field_caps)


def _log_caps_loaded(field_map: FieldMapProfile) -> bool:
    return bool(field_map.log_field_caps or field_map.field_caps)


def _metric_query_fields_are_usable(metric_query: Any, metric_field: str, field_map: FieldMapProfile) -> bool:
    metric_cap = field_map.field_capability(metric_field, context="metric")
    if not metric_cap or not field_map.is_numeric_field(metric_field, context="metric"):
        return False
    if not field_map.is_aggregatable_field(metric_field, context="metric"):
        return False

    for tag in metric_query.group_by:
        mapped = field_map.map_tag(tag, context="metric")
        cap = field_map.field_capability(mapped, context="metric")
        if not cap or not field_map.is_aggregatable_field(mapped, context="metric"):
            return False

    for raw_field in _collect_metric_scope_fields(metric_query.scope):
        mapped = field_map.map_tag(raw_field, context="metric")
        cap = field_map.field_capability(mapped, context="metric")
        if not cap or not field_map.is_searchable_field(mapped, context="metric"):
            return False

    return True


def _collect_metric_scope_fields(scope_items: list[Any]) -> list[str]:
    fields: list[str] = []
    for item in scope_items or []:
        if isinstance(item, TagFilter):
            if item.key not in fields:
                fields.append(item.key)
        elif isinstance(item, ScopeBoolOp):
            for child in _collect_metric_scope_fields(item.children):
                if child not in fields:
                    fields.append(child)
    return fields


def _metric_agg_expr(time_agg: str, metric_field: str) -> str:
    field_ident = _esql_identifier(metric_field)
    if time_agg == "avg":
        return f"AVG({field_ident})"
    if time_agg == "sum":
        return f"SUM({field_ident})"
    if time_agg == "min":
        return f"MIN({field_ident})"
    if time_agg == "max":
        return f"MAX({field_ident})"
    if time_agg == "count":
        return f"COUNT({field_ident})"
    if time_agg == "last":
        return f"LAST({field_ident}, @timestamp)"
    return ""


def _ast_has_free_text(node: Any) -> bool:
    if isinstance(node, LogTerm):
        return True
    if isinstance(node, LogBoolOp):
        return any(_ast_has_free_text(child) for child in node.children)
    if isinstance(node, LogNot):
        return _ast_has_free_text(node.child)
    return False


def _log_query_fields_are_usable(node: Any, field_map: FieldMapProfile) -> bool:
    for raw_field in _collect_log_fields(node):
        mapped = field_map.map_tag(raw_field, context="log")
        cap = field_map.field_capability(mapped, context="log")
        if not cap or not field_map.is_searchable_field(mapped, context="log"):
            return False
    return True


def _collect_log_fields(node: Any) -> list[str]:
    fields: list[str] = []
    if isinstance(node, LogAttributeFilter):
        fields.append(node.attribute)
    elif isinstance(node, LogRange):
        fields.append(node.attribute)
    elif isinstance(node, LogWildcard):
        if node.attribute:
            fields.append(node.attribute)
    elif isinstance(node, LogBoolOp):
        for child in node.children:
            for field in _collect_log_fields(child):
                if field not in fields:
                    fields.append(field)
    elif isinstance(node, LogNot):
        for field in _collect_log_fields(node.child):
            if field not in fields:
                fields.append(field)
    return fields


def _unescape_monitor_string(value: str) -> str:
    return value.replace(r"\"", '"').replace(r"\\", "\\")


__all__ = ["DatadogMonitorTranslation", "translate_monitor_to_alert_query"]
