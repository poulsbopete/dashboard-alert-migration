"""Trusted Datadog monitor query translation for alert migration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from functools import lru_cache
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .field_map import FieldMapProfile
from .log_parser import log_ast_to_esql_where, log_ast_to_kql, parse_log_query
from .models import (
    FormulaBinOp,
    FormulaFuncCall,
    FormulaNumber,
    FormulaRef,
    FormulaUnary,
    FunctionCall,
    LogAttributeFilter,
    LogBoolOp,
    LogNot,
    LogRange,
    LogTerm,
    LogWildcard,
    ScopeBoolOp,
    TagFilter,
)
from .query_parser import ParseError, parse_formula, parse_metric_query
from .translate import (
    _esql_escape,
    _esql_identifier,
    _format_agg_expr,
    _metric_is_count_like,
    _metric_scope_to_esql,
    _needs_rate,
    _resolve_agg,
)

_METRIC_MONITOR_RE = re.compile(
    r"^(?P<time_agg>\w+)\(last_(?P<window>\d+\s*[smhdw])\):"
    r"(?P<metric_query>.+?)\s*"
    r"(?P<comparator>>=|<=|==|!=|>|<)\s*"
    r"(?P<threshold>-?(?:\d+(?:\.\d+)?|\.\d+))\s*$",
    re.IGNORECASE,
)
_FORMULA_METRIC_MONITOR_RE = re.compile(
    r"^(?P<time_agg>\w+)\(last_(?P<window>\d+\s*[smhdw])\):"
    r"(?P<formula>.+?)\s*"
    r"(?P<comparator>>=|<=|==|!=|>|<)\s*"
    r"(?P<threshold>-?(?:\d+(?:\.\d+)?|\.\d+))\s*$",
    re.IGNORECASE,
)
_CHANGE_METRIC_MONITOR_RE = re.compile(
    r"^(?P<change_agg>change|pct_change)\(\s*"
    r"(?P<time_agg>avg|sum|min|max)\(\s*(?P<window>last_\d+\s*[smhdw])\s*\)\s*,\s*"
    r"(?P<shift>(?:last_)?\d+\s*[smhdw](?:_ago)?)\s*\)\s*:\s*"
    r"(?P<metric_query>.+?)\s*"
    r"(?P<comparator>>=|<=|==|!=|>|<)\s*"
    r"(?P<threshold>-?(?:\d+(?:\.\d+)?|\.\d+))\s*$",
    re.IGNORECASE,
)
_LOG_MONITOR_RE = re.compile(
    r'^logs\("(?P<search>(?:[^"\\]|\\.)*)"\)'
    r'(?:\.index\("(?P<index>(?:[^"\\]|\\.)*)"\))?'
    r'\.rollup\("(?P<rollup>[^"]+)"(?:,\s*"(?P<measure>(?:[^"\\]|\\.)*)")?\)'
    r'\.last\("(?P<window>\d+\s*[smhdw])"\)\s*'
    r'(?P<comparator>>=|<=|==|!=|>|<)\s*'
    r'(?P<threshold>-?(?:\d+(?:\.\d+)?|\.\d+))\s*$',
    re.IGNORECASE,
)
_SUPPORTED_METRIC_TIME_AGGS = {"avg", "sum", "min", "max", "count", "last"}
_SUPPORTED_CHANGE_TIME_AGGS = {"avg", "sum", "min", "max"}
_SUPPORTED_MONITOR_METRIC_FUNCTIONS = {
    "rollup",
    "fill",
    "per_second",
    "per_minute",
    "per_hour",
    "derivative",
}
_SUPPORTED_OUTER_MONITOR_FUNCTIONS = {
    "default_zero",
    "exclude_null",
    "per_second",
    "per_minute",
    "per_hour",
}
_SUPPORTED_SHIFTED_FORMULA_FUNCTIONS = {
    "hour_before": 3600,
    "day_before": 86400,
    "week_before": 7 * 86400,
    "month_before": 28 * 86400,
}
_FORMULA_MONITOR_MANUAL_WARNING = (
    "Datadog formula monitor requires manual review; exact support currently covers "
    "arithmetic formulas over as_count() metrics with sum aggregation, plus "
    "single-query shifted formulas such as week_before(), calendar_shift() in UTC "
    "or stable-offset IANA time zones for day/week/month shifts, and timeshift()"
)


@dataclass
class DatadogMonitorTranslation:
    translated_query: str = ""
    translated_query_provenance: str = ""
    group_by: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _FormulaMonitorQueryRef:
    metric_query: Any
    shift_seconds: int = 0
    shift_esql_span: str = ""


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
    change_translation = _translate_change_metric_monitor(raw_query, field_map)
    if change_translation.translated_query or change_translation.warnings:
        return change_translation

    formula_translation = _translate_formula_metric_monitor(raw_query, field_map)
    if formula_translation.translated_query or formula_translation.warnings:
        return formula_translation

    match = _METRIC_MONITOR_RE.fullmatch(raw_query)
    if not match:
        return DatadogMonitorTranslation()

    time_agg = str(match.group("time_agg") or "").lower()
    metric_query_text = str(match.group("metric_query") or "").strip()
    comparator = str(match.group("comparator") or "").strip()
    threshold = float(match.group("threshold"))

    if time_agg not in _SUPPORTED_METRIC_TIME_AGGS:
        return DatadogMonitorTranslation()

    metric_query, outer_functions = _parse_metric_monitor_query(metric_query_text)
    if metric_query is None:
        return DatadogMonitorTranslation()
    if not _metric_query_is_supported(metric_query, outer_functions):
        return DatadogMonitorTranslation()
    metric_query = _merge_supported_outer_metric_functions(metric_query, outer_functions)
    if time_agg != metric_query.space_agg and time_agg != "last":
        return DatadogMonitorTranslation()

    metric_field = _resolve_metric_field(metric_query.metric, field_map)
    agg_expr = _metric_agg_expr(time_agg, metric_field, metric_query)
    if not agg_expr:
        return DatadogMonitorTranslation()
    agg_expr = _apply_outer_metric_functions(agg_expr, outer_functions)
    if not agg_expr:
        return DatadogMonitorTranslation()
    metric_capability_issues = _metric_query_field_issues(metric_query, metric_field, field_map)
    if _metric_caps_loaded(field_map) and metric_capability_issues:
        return DatadogMonitorTranslation(warnings=metric_capability_issues)

    where_clauses = []
    for scope_item in metric_query.scope:
        clause = _metric_scope_to_esql(scope_item, field_map, context="metric")
        if clause:
            where_clauses.append(clause)
    exclude_null_clauses = _exclude_null_group_where_clauses(metric_query, field_map, outer_functions)
    if exclude_null_clauses is None:
        return DatadogMonitorTranslation()
    where_clauses.extend(exclude_null_clauses)

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
        warnings=_metric_monitor_warnings(metric_query, outer_functions),
    )


def _translate_formula_metric_monitor(
    raw_query: str,
    field_map: FieldMapProfile,
) -> DatadogMonitorTranslation:
    match = _FORMULA_METRIC_MONITOR_RE.fullmatch(raw_query)
    if not match:
        return DatadogMonitorTranslation()

    formula_text = str(match.group("formula") or "").strip()
    if not _monitor_formula_has_top_level_arithmetic(formula_text):
        return DatadogMonitorTranslation()

    time_agg = str(match.group("time_agg") or "").lower().strip()
    comparator = str(match.group("comparator") or "").strip()
    threshold = float(match.group("threshold"))
    window = f"last_{str(match.group('window') or '').strip()}"

    parsed = _parse_formula_metric_monitor_expression(formula_text)
    if parsed is None:
        return DatadogMonitorTranslation(warnings=[_FORMULA_MONITOR_MANUAL_WARNING])

    formula_ast, query_refs = parsed
    support_mode = _formula_monitor_support_mode(formula_ast, query_refs, time_agg)
    if not support_mode:
        return DatadogMonitorTranslation(warnings=[_FORMULA_MONITOR_MANUAL_WARNING])

    first_metric_query = next(iter(query_refs.values())).metric_query
    group_by = [
        _esql_identifier(field_map.map_tag(tag, context="metric"))
        for tag in first_metric_query.group_by
    ]
    metric_capability_issues: list[str] = []
    stats_parts: list[str] = []
    window_seconds = _monitor_span_to_seconds(window)
    if window_seconds <= 0:
        return DatadogMonitorTranslation()
    max_total_seconds = max(window_seconds + ref.shift_seconds for ref in query_refs.values())
    max_total_span = _seconds_to_esql_span(max_total_seconds)
    window_span = _seconds_to_esql_span(window_seconds)
    if not max_total_span or not window_span:
        return DatadogMonitorTranslation()

    for ref_name, ref in query_refs.items():
        metric_query = ref.metric_query
        metric_field = _resolve_metric_field(metric_query.metric, field_map)
        metric_capability_issues.extend(_metric_query_field_issues(metric_query, metric_field, field_map))
        agg_expr = _metric_agg_expr(time_agg, metric_field, metric_query)
        if not agg_expr:
            return DatadogMonitorTranslation()
        where_clauses = []
        for scope_item in metric_query.scope:
            clause = _metric_scope_to_esql(scope_item, field_map, context="metric")
            if clause:
                where_clauses.append(clause)
        if ref.shift_seconds > 0:
            if ref.shift_esql_span:
                where_clauses.append(f"@timestamp >= NOW() - {ref.shift_esql_span} - {window_span}")
                where_clauses.append(f"@timestamp < NOW() - {ref.shift_esql_span}")
            else:
                shifted_total_span = _seconds_to_esql_span(window_seconds + ref.shift_seconds)
                shift_span = _seconds_to_esql_span(ref.shift_seconds)
                if not shifted_total_span or not shift_span:
                    return DatadogMonitorTranslation()
                where_clauses.append(f"@timestamp >= NOW() - {shifted_total_span}")
                where_clauses.append(f"@timestamp < NOW() - {shift_span}")
        else:
            where_clauses.append(f"@timestamp >= NOW() - {window_span}")
        stat_expr = f"{ref_name} = {agg_expr}"
        if where_clauses:
            stat_expr += f" WHERE {' AND '.join(where_clauses)}"
        stats_parts.append(stat_expr)

    if _metric_caps_loaded(field_map) and metric_capability_issues:
        deduped_issues = list(dict.fromkeys(metric_capability_issues))
        return DatadogMonitorTranslation(warnings=deduped_issues)

    value_expr = _monitor_formula_ast_to_esql(formula_ast)
    if not value_expr:
        return DatadogMonitorTranslation()

    lines = [
        f"FROM {field_map.metric_index}",
        f"| WHERE @timestamp >= NOW() - {max_total_span}",
    ]
    stats_line = "| STATS " + ", ".join(stats_parts)
    if group_by:
        stats_line += f" BY {', '.join(group_by)}"
    lines.append(stats_line)
    lines.append("| WHERE " + " AND ".join(f"{ref_name} IS NOT NULL" for ref_name in query_refs))
    lines.append(f"| EVAL value = {value_expr}")
    if _monitor_formula_ast_has_division(formula_ast):
        lines.append("| WHERE value IS NOT NULL")
    lines.append(f"| WHERE value {comparator} {threshold}")

    return DatadogMonitorTranslation(
        translated_query="\n".join(lines),
        translated_query_provenance="translated_esql",
        group_by=group_by,
    )


def _translate_change_metric_monitor(
    raw_query: str,
    field_map: FieldMapProfile,
) -> DatadogMonitorTranslation:
    match = _CHANGE_METRIC_MONITOR_RE.fullmatch(raw_query)
    if not match:
        return DatadogMonitorTranslation()

    change_agg = str(match.group("change_agg") or "").lower().strip()
    time_agg = str(match.group("time_agg") or "").lower().strip()
    window = str(match.group("window") or "").strip()
    shift = str(match.group("shift") or "").strip()
    metric_query_text = str(match.group("metric_query") or "").strip()
    comparator = str(match.group("comparator") or "").strip()
    threshold = float(match.group("threshold"))

    if change_agg not in {"change", "pct_change"}:
        return DatadogMonitorTranslation()
    if time_agg not in _SUPPORTED_CHANGE_TIME_AGGS:
        return DatadogMonitorTranslation()

    metric_query, outer_functions = _parse_metric_monitor_query(metric_query_text)
    if metric_query is None:
        return DatadogMonitorTranslation()
    if outer_functions or metric_query.functions or metric_query.as_rate or metric_query.as_count:
        return DatadogMonitorTranslation()
    if metric_query.space_agg not in _SUPPORTED_CHANGE_TIME_AGGS:
        return DatadogMonitorTranslation()
    if time_agg != metric_query.space_agg:
        return DatadogMonitorTranslation()

    metric_field = _resolve_metric_field(metric_query.metric, field_map)
    agg_expr = _metric_agg_expr(time_agg, metric_field, metric_query)
    if not agg_expr:
        return DatadogMonitorTranslation()
    metric_capability_issues = _metric_query_field_issues(metric_query, metric_field, field_map)
    if _metric_caps_loaded(field_map) and metric_capability_issues:
        return DatadogMonitorTranslation(warnings=metric_capability_issues)

    current_span = _monitor_span_to_esql(window)
    shift_span = _monitor_span_to_esql(shift)
    total_span = _monitor_total_span_to_esql(window, shift)
    if not current_span or not shift_span or not total_span:
        return DatadogMonitorTranslation()

    where_clauses = []
    for scope_item in metric_query.scope:
        clause = _metric_scope_to_esql(scope_item, field_map, context="metric")
        if clause:
            where_clauses.append(clause)
    where_clauses.append(f"@timestamp >= NOW() - {total_span}")

    group_by = [_esql_identifier(field_map.map_tag(tag, context="metric")) for tag in metric_query.group_by]
    previous_window_start = f"NOW() - {total_span}"
    previous_window_end = f"NOW() - {shift_span}"
    current_window_start = f"NOW() - {current_span}"

    lines = [f"FROM {field_map.metric_index}"]
    lines.append(f"| WHERE {' AND '.join(where_clauses)}")
    stats_parts = [
        (
            f"current_value = {agg_expr} "
            f"WHERE @timestamp >= {current_window_start}"
        ),
        (
            f"previous_value = {agg_expr} "
            f"WHERE @timestamp >= {previous_window_start} AND @timestamp < {previous_window_end}"
        ),
    ]
    stats_line = "| STATS " + ", ".join(stats_parts)
    if group_by:
        stats_line += f" BY {', '.join(group_by)}"
    lines.append(stats_line)
    lines.append("| WHERE current_value IS NOT NULL AND previous_value IS NOT NULL")
    if change_agg == "pct_change":
        lines.append(
            "| EVAL value = CASE(previous_value == 0, NULL, ((current_value - previous_value) / previous_value) * 100)"
        )
        lines.append("| WHERE value IS NOT NULL")
    else:
        lines.append("| EVAL value = current_value - previous_value")
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
    measure = _unescape_monitor_string(str(match.group("measure") or "")).strip()
    comparator = str(match.group("comparator") or "").strip()
    threshold = float(match.group("threshold"))

    agg_expr = _log_rollup_expr(rollup, measure, field_map)
    if not agg_expr:
        return DatadogMonitorTranslation()

    log_query = parse_log_query(search)
    tag_map = {key: field_map.map_tag(key, context="log") for key in field_map.tag_map}
    log_capability_issues = _log_query_field_issues(
        log_query.ast,
        field_map,
        measure_field=measure,
        rollup=rollup,
    )
    if _log_caps_loaded(field_map) and log_capability_issues:
        return DatadogMonitorTranslation(warnings=log_capability_issues)
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

    target_logs_index = field_map.logs_index
    warnings: list[str] = []
    if index_name and index_name != "*":
        mapped_index = field_map.map_log_index(index_name)
        if mapped_index:
            target_logs_index = mapped_index
        else:
            warnings.append("Datadog log index selection is approximated via the configured logs index")

    lines = [f"FROM {target_logs_index}"]
    if where_clause:
        lines.append(f"| WHERE {where_clause}")
    lines.append(f"| STATS value = {agg_expr}")
    lines.append(f"| WHERE value {comparator} {threshold}")

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
    return not _metric_query_field_issues(metric_query, metric_field, field_map)


def _metric_query_field_issues(metric_query: Any, metric_field: str, field_map: FieldMapProfile) -> list[str]:
    issues: list[str] = []

    metric_cap = field_map.field_capability(metric_field, context="metric")
    if not metric_cap:
        issues.append(f"Target metric field `{metric_field}` is missing from metric field capabilities")
    else:
        if not field_map.is_numeric_field(metric_field, context="metric"):
            issues.append(f"Target metric field `{metric_field}` is not numeric")
        if not field_map.is_aggregatable_field(metric_field, context="metric"):
            issues.append(f"Target metric field `{metric_field}` is not aggregatable")

    for tag in metric_query.group_by:
        mapped = field_map.map_tag(tag, context="metric")
        cap = field_map.field_capability(mapped, context="metric")
        if not cap:
            issues.append(f"Target group-by field `{mapped}` is missing from metric field capabilities")
        elif not field_map.is_aggregatable_field(mapped, context="metric"):
            issues.append(f"Target group-by field `{mapped}` is not aggregatable")

    for raw_field in _collect_metric_scope_fields(metric_query.scope):
        mapped = field_map.map_tag(raw_field, context="metric")
        cap = field_map.field_capability(mapped, context="metric")
        if not cap:
            issues.append(f"Target filter field `{mapped}` is missing from metric field capabilities")
        elif not field_map.is_searchable_field(mapped, context="metric"):
            issues.append(f"Target filter field `{mapped}` is not searchable")

    return issues


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


def _metric_agg_expr(time_agg: str, metric_field: str, metric_query: Any | None = None) -> str:
    if metric_query is not None and time_agg != "last":
        try:
            es_agg = _resolve_agg(time_agg, metric_field)
        except ValueError:
            return ""
        return _format_agg_expr(es_agg, metric_field, metric_query)

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


def _parse_metric_monitor_query(raw: str) -> tuple[Any | None, list[FunctionCall]]:
    inner = str(raw or "").strip()
    outer_functions: list[FunctionCall] = []

    while True:
        match = re.match(r"^(?P<name>\w+)\s*\(", inner)
        if not match:
            break

        remainder = inner[match.end():]
        close_idx = _find_matching_monitor_paren(remainder)
        if close_idx < 0 or close_idx != len(remainder) - 1:
            break

        arg_parts = _split_monitor_function_args(remainder[:close_idx])
        if not arg_parts:
            break

        outer_functions.append(
            FunctionCall(
                name=match.group("name"),
                args=[_coerce_monitor_function_arg(part.strip()) for part in arg_parts[1:]],
            )
        )
        inner = arg_parts[0].strip()

    try:
        return parse_metric_query(inner), outer_functions
    except ParseError:
        return None, outer_functions


def _find_matching_monitor_paren(text: str) -> int:
    depth = 1
    brace_depth = 0
    in_quote = False
    quote_char = ""
    for idx, ch in enumerate(text):
        if ch in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = ch
            continue
        if in_quote and ch == quote_char:
            in_quote = False
            continue
        if in_quote:
            continue
        if ch == "{":
            brace_depth += 1
            continue
        if ch == "}":
            brace_depth = max(brace_depth - 1, 0)
            continue
        if ch == "(":
            depth += 1
            continue
        if ch == ")" and brace_depth == 0:
            depth -= 1
            if depth == 0:
                return idx
    return -1


def _split_monitor_function_args(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    paren_depth = 0
    brace_depth = 0
    in_quote = False
    quote_char = ""

    for ch in text:
        if ch in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = ch
            current.append(ch)
            continue
        if in_quote and ch == quote_char:
            in_quote = False
            current.append(ch)
            continue
        if in_quote:
            current.append(ch)
            continue
        if ch == "(":
            paren_depth += 1
            current.append(ch)
            continue
        if ch == ")":
            paren_depth = max(paren_depth - 1, 0)
            current.append(ch)
            continue
        if ch == "{":
            brace_depth += 1
            current.append(ch)
            continue
        if ch == "}":
            brace_depth = max(brace_depth - 1, 0)
            current.append(ch)
            continue
        if ch == "," and paren_depth == 0 and brace_depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)

    if current:
        parts.append("".join(current))
    return parts


def _coerce_monitor_function_arg(value: str) -> Any:
    if value.startswith(("'", '"')) and len(value) >= 2 and value[-1] == value[0]:
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _metric_query_is_supported(metric_query: Any, outer_functions: list[FunctionCall]) -> bool:
    for fn in metric_query.functions or []:
        if str(fn.name or "").lower() not in _SUPPORTED_MONITOR_METRIC_FUNCTIONS:
            return False
    if metric_query.fill_value not in (None, "zero"):
        return False

    for fn in outer_functions or []:
        if str(fn.name or "").lower() not in _SUPPORTED_OUTER_MONITOR_FUNCTIONS:
            return False
    return True


def _merge_supported_outer_metric_functions(metric_query: Any, outer_functions: list[FunctionCall]) -> Any:
    for fn in outer_functions or []:
        if str(fn.name or "").lower() in {"per_second", "per_minute", "per_hour"}:
            metric_query.functions.append(fn)
    return metric_query


def _apply_outer_metric_functions(agg_expr: str, outer_functions: list[FunctionCall]) -> str:
    expr = agg_expr
    for fn in reversed(outer_functions or []):
        fn_name = str(fn.name or "").lower()
        if fn_name in {"per_second", "per_minute", "per_hour"}:
            continue
        if fn_name == "exclude_null":
            continue
        if fn_name == "default_zero":
            expr = f"COALESCE({expr}, 0)"
            continue
        return ""
    return expr


def _metric_monitor_warnings(metric_query: Any, outer_functions: list[FunctionCall]) -> list[str]:
    warnings: list[str] = []
    if metric_query.as_rate or _needs_rate(metric_query):
        warnings.append("rate semantics approximated with delta over observed bucket span")
    if metric_query.as_count and not _metric_is_count_like(metric_query.metric):
        warnings.append("as_count semantics are approximated for non-count metrics")
    if metric_query.rollup:
        warnings.append("rollup interval is approximated in ES|QL")
    if metric_query.fill_value == "zero":
        warnings.append(
            "fill(zero) only applies to null values in returned rows; empty buckets may still be omitted"
        )
    if any(str(fn.name or "").lower() == "default_zero" for fn in outer_functions or []):
        warnings.append("default_zero semantics are approximated in ES|QL")
    return warnings


def _monitor_formula_has_top_level_arithmetic(text: str) -> bool:
    depth = 0
    brace_depth = 0
    in_quote = False
    quote_char = ""
    for ch in str(text or ""):
        if ch in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = ch
            continue
        if in_quote and ch == quote_char:
            in_quote = False
            continue
        if in_quote:
            continue
        if ch == "{":
            brace_depth += 1
            continue
        if ch == "}":
            brace_depth = max(brace_depth - 1, 0)
            continue
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            depth = max(depth - 1, 0)
            continue
        if depth == 0 and brace_depth == 0 and ch in "+-*/":
            return True
    return False


def _parse_formula_metric_monitor_expression(raw_expr: str) -> tuple[Any, dict[str, _FormulaMonitorQueryRef]] | None:
    formula_parts: list[str] = []
    query_refs: dict[str, _FormulaMonitorQueryRef] = {}
    term_ref_map: dict[tuple[str, int, str], str] = {}
    idx = 0
    expect_value = True
    ref_idx = 1
    text = str(raw_expr or "")

    while idx < len(text):
        ch = text[idx]
        if ch.isspace():
            formula_parts.append(ch)
            idx += 1
            continue

        if expect_value:
            if ch == "(":
                formula_parts.append(ch)
                idx += 1
                continue
            if ch == "-":
                formula_parts.append(ch)
                idx += 1
                continue
            number_match = re.match(r"\d+(?:\.\d+)?", text[idx:])
            if number_match:
                formula_parts.append(number_match.group(0))
                idx += len(number_match.group(0))
                expect_value = False
                continue

            shifted = _consume_shifted_formula_metric_term(text, idx)
            if shifted is not None:
                term, shift_seconds, shift_esql_span, next_idx = shifted
                ref_name = term_ref_map.get((term, shift_seconds, shift_esql_span))
                if ref_name is None:
                    try:
                        metric_query = parse_metric_query(term)
                    except ParseError:
                        return None
                    ref_name = f"q{ref_idx}"
                    ref_idx += 1
                    query_refs[ref_name] = _FormulaMonitorQueryRef(
                        metric_query=metric_query,
                        shift_seconds=shift_seconds,
                        shift_esql_span=shift_esql_span,
                    )
                    term_ref_map[(term, shift_seconds, shift_esql_span)] = ref_name
                formula_parts.append(ref_name)
                idx = next_idx
                expect_value = False
                continue

            term, next_idx = _consume_formula_metric_term(text, idx)
            if not term:
                return None
            ref_name = term_ref_map.get((term, 0))
            if ref_name is None:
                try:
                    metric_query = parse_metric_query(term)
                except ParseError:
                    return None
                ref_name = f"q{ref_idx}"
                ref_idx += 1
                query_refs[ref_name] = _FormulaMonitorQueryRef(metric_query=metric_query)
                term_ref_map[(term, 0)] = ref_name
            formula_parts.append(ref_name)
            idx = next_idx
            expect_value = False
            continue

        if ch in "+-*/":
            formula_parts.append(ch)
            idx += 1
            expect_value = True
            continue
        if ch == ")":
            formula_parts.append(ch)
            idx += 1
            continue
        return None

    try:
        parsed = parse_formula("".join(formula_parts))
    except ParseError:
        return None
    if parsed.ast is None or not query_refs:
        return None
    return parsed.ast, query_refs


def _consume_formula_metric_term(text: str, start: int) -> tuple[str, int]:
    current: list[str] = []
    brace_depth = 0
    paren_depth = 0
    in_quote = False
    quote_char = ""
    idx = start
    while idx < len(text):
        ch = text[idx]
        if ch in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = ch
            current.append(ch)
            idx += 1
            continue
        if in_quote and ch == quote_char:
            in_quote = False
            current.append(ch)
            idx += 1
            continue
        if in_quote:
            current.append(ch)
            idx += 1
            continue
        if ch == "{":
            brace_depth += 1
            current.append(ch)
            idx += 1
            continue
        if ch == "}":
            brace_depth = max(brace_depth - 1, 0)
            current.append(ch)
            idx += 1
            continue
        if ch == "(":
            paren_depth += 1
            current.append(ch)
            idx += 1
            continue
        if ch == ")":
            if paren_depth == 0 and brace_depth == 0:
                break
            paren_depth = max(paren_depth - 1, 0)
            current.append(ch)
            idx += 1
            continue
        if brace_depth == 0 and paren_depth == 0 and ch in "+-*/":
            break
        current.append(ch)
        idx += 1
    return "".join(current).strip(), idx


def _consume_shifted_formula_metric_term(text: str, start: int) -> tuple[str, int, str, int] | None:
    match = re.match(r"(?P<name>[A-Za-z_]\w*)\s*\(", text[start:])
    if not match:
        return None
    fn_name = str(match.group("name") or "").lower()
    if fn_name not in _SUPPORTED_SHIFTED_FORMULA_FUNCTIONS and fn_name not in {"timeshift", "calendar_shift"}:
        return None

    remainder = text[start + match.end():]
    close_idx = _find_matching_monitor_paren(remainder)
    if close_idx < 0:
        return None

    arg_parts = _split_monitor_function_args(remainder[:close_idx])
    next_idx = start + match.end() + close_idx + 1
    if fn_name == "timeshift":
        if len(arg_parts) != 2:
            return None
        shift_seconds = _parse_timeshift_shift_seconds(arg_parts[1])
        if shift_seconds <= 0:
            return None
        return arg_parts[0].strip(), shift_seconds, "", next_idx

    if fn_name == "calendar_shift":
        if len(arg_parts) != 3:
            return None
        shift_seconds, shift_esql_span = _parse_calendar_shift_shift(arg_parts[1], arg_parts[2])
        if shift_seconds <= 0:
            return None
        return arg_parts[0].strip(), shift_seconds, shift_esql_span, next_idx

    if len(arg_parts) != 1:
        return None
    return arg_parts[0].strip(), _SUPPORTED_SHIFTED_FORMULA_FUNCTIONS[fn_name], "", next_idx


def _parse_timeshift_shift_seconds(raw: str) -> int:
    value = str(raw or "").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return 0
    try:
        seconds = int(abs(float(value)))
    except ValueError:
        return 0
    return seconds


def _parse_calendar_shift_shift(raw_shift: str, raw_timezone: str) -> tuple[int, str]:
    timezone_name = str(raw_timezone or "").strip().strip("'\"")
    if not _calendar_shift_timezone_is_exact(timezone_name):
        return 0, ""
    shift = str(raw_shift or "").strip().strip("'\"")
    match = re.fullmatch(r"-(?P<amount>\d+)(?P<unit>d|w|mo)", shift, re.IGNORECASE)
    if not match:
        return 0, ""
    amount = int(match.group("amount"))
    unit = str(match.group("unit") or "").lower()
    if unit == "d":
        return amount * 86400, ""
    if unit == "w":
        return amount * 7 * 86400, ""
    if unit == "mo":
        return amount * 32 * 86400, f"{amount} {'month' if amount == 1 else 'months'}"
    return 0, ""


@lru_cache(maxsize=None)
def _calendar_shift_timezone_is_exact(timezone_name: str) -> bool:
    normalized = str(timezone_name or "").strip()
    if not normalized:
        return False
    if normalized.upper() == "UTC":
        return True
    try:
        tzinfo = ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        return False

    current_year = datetime.now(dt_timezone.utc).year
    offsets = {
        datetime(year, month, 15, 12, 0, tzinfo=dt_timezone.utc).astimezone(tzinfo).utcoffset()
        for year in range(current_year - 1, current_year + 11)
        for month in range(1, 13)
    }
    return len(offsets) == 1


def _exclude_null_group_where_clauses(
    metric_query: Any,
    field_map: FieldMapProfile,
    outer_functions: list[FunctionCall],
) -> list[str] | None:
    if not any(str(fn.name or "").lower() == "exclude_null" for fn in outer_functions or []):
        return []
    if not metric_query.group_by:
        return None

    clauses: list[str] = []
    for tag in metric_query.group_by:
        field_name = _esql_identifier(field_map.map_tag(tag, context="metric"))
        clauses.append(f"{field_name} IS NOT NULL")
        clauses.append(f'{field_name} != "N/A"')
    return clauses


def _formula_monitor_support_mode(
    formula_ast: Any,
    query_refs: dict[str, _FormulaMonitorQueryRef],
    time_agg: str,
) -> str:
    if _formula_monitor_exact_shift_supported(formula_ast, query_refs, time_agg):
        return "shifted"
    if _formula_monitor_exact_as_count_supported(formula_ast, query_refs, time_agg):
        return "as_count"
    return ""


def _formula_monitor_exact_as_count_supported(
    formula_ast: Any,
    query_refs: dict[str, _FormulaMonitorQueryRef],
    time_agg: str,
) -> bool:
    if time_agg != "sum":
        return False
    if not _monitor_formula_ast_is_exact_as_count_safe(formula_ast):
        return False

    base_group_by: list[str] | None = None
    for ref in query_refs.values():
        if ref.shift_seconds != 0:
            return False
        metric_query = ref.metric_query
        if not metric_query.as_count:
            return False
        if metric_query.as_rate:
            return False
        if metric_query.functions:
            return False
        if metric_query.space_agg != "sum":
            return False
        if base_group_by is None:
            base_group_by = list(metric_query.group_by)
        elif list(metric_query.group_by) != base_group_by:
            return False
    return True


def _formula_monitor_exact_shift_supported(
    formula_ast: Any,
    query_refs: dict[str, _FormulaMonitorQueryRef],
    time_agg: str,
) -> bool:
    if time_agg not in {"avg", "sum", "min", "max"}:
        return False
    if not any(ref.shift_seconds > 0 for ref in query_refs.values()):
        return False
    if not _monitor_formula_ast_is_shift_safe(formula_ast):
        return False

    base_identity: tuple[Any, ...] | None = None
    for ref in query_refs.values():
        metric_query = ref.metric_query
        if metric_query.as_rate or metric_query.as_count:
            return False
        if metric_query.functions:
            return False
        if metric_query.space_agg != time_agg:
            return False
        identity = _metric_query_identity(metric_query)
        if base_identity is None:
            base_identity = identity
        elif identity != base_identity:
            return False
    return True


def _monitor_formula_ast_is_exact_as_count_safe(node: Any) -> bool:
    if isinstance(node, (FormulaRef, FormulaNumber)):
        return True
    if isinstance(node, FormulaUnary):
        return node.op == "-" and _monitor_formula_ast_is_exact_as_count_safe(node.operand)
    if isinstance(node, FormulaBinOp):
        return (
            node.op in {"+", "-", "*", "/"}
            and _monitor_formula_ast_is_exact_as_count_safe(node.left)
            and _monitor_formula_ast_is_exact_as_count_safe(node.right)
        )
    if isinstance(node, FormulaFuncCall):
        return False
    return False


def _monitor_formula_ast_is_shift_safe(node: Any) -> bool:
    return _monitor_formula_ast_is_exact_as_count_safe(node)


def _monitor_formula_ast_has_division(node: Any) -> bool:
    if isinstance(node, FormulaBinOp):
        if node.op == "/":
            return True
        return _monitor_formula_ast_has_division(node.left) or _monitor_formula_ast_has_division(node.right)
    if isinstance(node, FormulaUnary):
        return _monitor_formula_ast_has_division(node.operand)
    if isinstance(node, FormulaFuncCall):
        return any(_monitor_formula_ast_has_division(arg) for arg in node.args or [])
    return False


def _metric_query_identity(metric_query: Any) -> tuple[Any, ...]:
    return (
        metric_query.space_agg,
        metric_query.metric,
        tuple(repr(item) for item in metric_query.scope or []),
        tuple(metric_query.group_by or []),
    )


def _monitor_formula_ast_to_esql(node: Any) -> str:
    if isinstance(node, FormulaRef):
        return _esql_identifier(node.name)
    if isinstance(node, FormulaNumber):
        value = node.value if node.value is not None else 0
        if float(value).is_integer():
            return str(int(value))
        return str(value)
    if isinstance(node, FormulaUnary):
        operand = _monitor_formula_ast_to_esql(node.operand)
        if node.op == "-":
            return f"(-{operand})"
        return ""
    if isinstance(node, FormulaBinOp):
        left = _monitor_formula_ast_to_esql(node.left)
        right = _monitor_formula_ast_to_esql(node.right)
        if not left or not right:
            return ""
        if node.op == "/":
            return f"CASE({right} == 0, NULL, ({left} / {right}))"
        if node.op in {"+", "-", "*"}:
            return f"({left} {node.op} {right})"
        return ""
    return ""


def _ast_has_free_text(node: Any) -> bool:
    if isinstance(node, LogTerm):
        return True
    if isinstance(node, LogBoolOp):
        return any(_ast_has_free_text(child) for child in node.children)
    if isinstance(node, LogNot):
        return _ast_has_free_text(node.child)
    return False


def _log_query_fields_are_usable(
    node: Any,
    field_map: FieldMapProfile,
    *,
    measure_field: str = "",
    rollup: str = "",
) -> bool:
    return not _log_query_field_issues(
        node,
        field_map,
        measure_field=measure_field,
        rollup=rollup,
    )


def _log_query_field_issues(
    node: Any,
    field_map: FieldMapProfile,
    *,
    measure_field: str = "",
    rollup: str = "",
) -> list[str]:
    issues: list[str] = []
    for raw_field in _collect_log_fields(node):
        mapped = field_map.map_tag(raw_field, context="log")
        cap = field_map.field_capability(mapped, context="log")
        if not cap:
            issues.append(f"Target log filter field `{mapped}` is missing from log field capabilities")
        elif not field_map.is_searchable_field(mapped, context="log"):
            issues.append(f"Target log filter field `{mapped}` is not searchable")

    if measure_field:
        mapped_measure = field_map.map_tag(_normalize_log_measure_field(measure_field), context="log")
        cap = field_map.field_capability(mapped_measure, context="log")
        if not cap:
            issues.append(f"Target log measure field `{mapped_measure}` is missing from log field capabilities")
        if rollup == "cardinality":
            if cap and not field_map.is_aggregatable_field(mapped_measure, context="log"):
                issues.append(f"Target log measure field `{mapped_measure}` is not aggregatable")
            return issues
        if cap and not field_map.is_numeric_field(mapped_measure, context="log"):
            issues.append(f"Target log measure field `{mapped_measure}` is not numeric")
        if cap and not field_map.is_aggregatable_field(mapped_measure, context="log"):
            issues.append(f"Target log measure field `{mapped_measure}` is not aggregatable")
    return issues


def _log_rollup_expr(rollup: str, measure_field: str, field_map: FieldMapProfile) -> str:
    normalized_rollup = str(rollup or "").lower().strip()
    normalized_measure = _normalize_log_measure_field(measure_field)
    if normalized_rollup == "count" and not normalized_measure:
        return "COUNT(*)"
    if not normalized_measure:
        return ""

    field_ident = _esql_identifier(field_map.map_tag(normalized_measure, context="log"))
    if normalized_rollup == "avg":
        return f"AVG({field_ident})"
    if normalized_rollup == "sum":
        return f"SUM({field_ident})"
    if normalized_rollup == "min":
        return f"MIN({field_ident})"
    if normalized_rollup == "max":
        return f"MAX({field_ident})"
    if normalized_rollup == "median":
        return f"PERCENTILE({field_ident}, 50)"
    if normalized_rollup == "cardinality":
        return f"COUNT_DISTINCT({field_ident})"
    percentile_map = {
        "pc75": 75,
        "pc90": 90,
        "pc95": 95,
        "pc98": 98,
        "pc99": 99,
    }
    if normalized_rollup in percentile_map:
        return f"PERCENTILE({field_ident}, {percentile_map[normalized_rollup]})"
    return ""


def _normalize_log_measure_field(measure_field: str) -> str:
    normalized = str(measure_field or "").strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    return normalized


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


_MONITOR_SPAN_RE = re.compile(
    r"^(?:last_)?(?P<amount>\d+)\s*(?P<unit>[smhdw])(?:_ago)?$",
    re.IGNORECASE,
)
_SPAN_UNIT_LABELS = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
}
_SPAN_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}


def _monitor_span_to_seconds(raw: str) -> int:
    match = _MONITOR_SPAN_RE.fullmatch(str(raw or "").strip())
    if not match:
        return 0
    amount = int(match.group("amount"))
    unit = str(match.group("unit") or "").lower()
    return amount * _SPAN_UNIT_SECONDS.get(unit, 0)


def _seconds_to_esql_span(total_seconds: int) -> str:
    if total_seconds <= 0:
        return ""
    if total_seconds % _SPAN_UNIT_SECONDS["d"] == 0:
        return f"{total_seconds // _SPAN_UNIT_SECONDS['d']} days"
    if total_seconds % _SPAN_UNIT_SECONDS["w"] == 0:
        return f"{total_seconds // _SPAN_UNIT_SECONDS['w']} weeks"
    if total_seconds % _SPAN_UNIT_SECONDS["h"] == 0:
        return f"{total_seconds // _SPAN_UNIT_SECONDS['h']} hours"
    if total_seconds % _SPAN_UNIT_SECONDS["m"] == 0:
        return f"{total_seconds // _SPAN_UNIT_SECONDS['m']} minutes"
    return f"{total_seconds} seconds"


def _monitor_span_to_esql(raw: str) -> str:
    return _seconds_to_esql_span(_monitor_span_to_seconds(raw))


def _monitor_total_span_to_esql(window: str, shift: str) -> str:
    total_seconds = _monitor_span_to_seconds(window) + _monitor_span_to_seconds(shift)
    return _seconds_to_esql_span(total_seconds)


__all__ = ["DatadogMonitorTranslation", "translate_monitor_to_alert_query"]
