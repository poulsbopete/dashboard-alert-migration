"""Canonical alerting IR — shared envelope for alerts and monitors.

Wraps both Grafana legacy alerts and Datadog monitors under one
operational envelope without faking a universal condition AST.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .status import AssetStatus

_REL_LAST_RE = re.compile(
    r"(?:\blast_\s*(\d+\s*[smhdw])\b|\blast\s*\(\s*(\d+\s*[smhdw])\s*\))",
    re.IGNORECASE,
)


@dataclass
class AlertingIR:
    """Source-agnostic alerting / monitor asset.

    ``kind`` distinguishes the alert family (e.g. ``grafana_legacy``,
    ``datadog_monitor``). Source-specific condition detail lives in
    ``source_extension`` rather than a fake unified condition AST.
    """

    version: int = 1
    alert_id: str = ""
    name: str = ""
    kind: str = ""
    source_ref: str = ""
    condition_summary: str = ""
    evaluation_window: str = ""
    severity: str = ""
    no_data_policy: str = ""

    actions: list[dict[str, Any]] = field(default_factory=list)
    linked_assets: list[str] = field(default_factory=list)

    status: AssetStatus = AssetStatus.MANUAL_REQUIRED
    manual_required: bool = True
    target_candidate: str = ""
    losses: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_extension: dict[str, Any] = field(default_factory=dict)

    automation_tier: str = ""  # "automated", "draft_requires_review", "manual_required"
    target_rule_type: str = ""  # e.g. "es-query", "index-threshold", "custom-threshold"
    target_rule_payload: dict[str, Any] = field(default_factory=dict)
    target_connector_refs: list[str] = field(default_factory=list)
    schedule_interval: str = ""  # e.g. "1m", "5m"
    pending_period: str = ""  # Grafana "for" / evaluation stability window
    group_by: list[str] = field(default_factory=list)
    translated_query: str = ""  # ES|QL or KQL query for the target rule
    translated_query_provenance: str = ""  # e.g. translated_esql, native_promql, manual_verified
    notification_summary: str = ""  # human-readable notification routing summary

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


def build_alerting_ir_from_grafana(alert_task: dict[str, Any]) -> AlertingIR:
    """Build an AlertingIR from a Grafana alert migration task dict."""
    return AlertingIR(
        alert_id=str(alert_task.get("dashboard_uid", "") or "") + "/" + str(alert_task.get("panel", "") or ""),
        name=str(alert_task.get("alert_name", "") or ""),
        kind="grafana_legacy",
        source_ref=str(alert_task.get("panel", "") or ""),
        condition_summary="; ".join(alert_task.get("conditions_description", [])),
        evaluation_window=str(alert_task.get("frequency", "") or ""),
        severity="",
        no_data_policy=str(alert_task.get("no_data_state", "") or ""),
        actions=[{"notification_channels": alert_task.get("notification_channels", [])}],
        linked_assets=[str(alert_task.get("panel", ""))],
        target_candidate=str(alert_task.get("suggested_kibana_rule_type", "") or ""),
        source_extension={
            "alert_type": alert_task.get("alert_type", "legacy"),
            "exec_error_state": alert_task.get("exec_error_state", ""),
            "pending_for": alert_task.get("pending_for", ""),
            "conditions": alert_task.get("conditions", []),
        },
    )


def _parse_datadog_query_time_window(query: str) -> str:
    if not query:
        return ""
    m = _REL_LAST_RE.search(query)
    if not m:
        return ""
    return (m.group(1) or m.group(2) or "").replace(" ", "")


def _datadog_kind(monitor_type: str) -> str:
    t = (monitor_type or "").lower().strip()
    if t in ("metric alert", "query alert"):
        return "datadog_metric"
    if t == "log alert":
        return "datadog_log"
    if t == "composite":
        return "datadog_composite"
    if t == "service check":
        return "datadog_service_check"
    if not t:
        return "datadog_monitor"
    safe = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return f"datadog_{safe}"


def _datadog_automation_tier(monitor_type: str) -> str:
    t = (monitor_type or "").lower().strip()
    if t in ("metric alert", "query alert", "log alert"):
        return "draft_requires_review"
    if t == "composite":
        return "manual_required"
    return "manual_required"


def _datadog_target_rule_type(monitor_type: str) -> str:
    t = (monitor_type or "").lower().strip()
    if t in ("metric alert", "query alert"):
        return "custom-threshold"
    return "es-query"


def _datadog_no_data_policy(options: dict[str, Any]) -> str:
    if not isinstance(options, dict):
        return ""
    raw = options.get("notify_no_data")
    if raw is True:
        return "notify"
    if raw is False:
        return "no_notify"
    if raw is None:
        return ""
    return str(raw)


def _summarize_datadog_condition(monitor: dict[str, Any]) -> str:
    parts: list[str] = []
    q = monitor.get("query")
    if q:
        parts.append(str(q))
    opts = monitor.get("options")
    if isinstance(opts, dict):
        th = opts.get("thresholds")
        if th:
            parts.append(f"thresholds={th}")
    return "; ".join(parts) if parts else ""


def build_alerting_ir_from_datadog(
    monitor: dict[str, Any],
    field_map: Any | None = None,
) -> AlertingIR:
    """Build an AlertingIR from a raw Datadog monitor API-style dict."""
    mtype = str(monitor.get("type", "") or "")
    kind = _datadog_kind(mtype)
    opts = monitor.get("options") if isinstance(monitor.get("options"), dict) else {}
    query = str(monitor.get("query", "") or "")
    name = str(monitor.get("name", "") or "")
    alert_id = str(monitor.get("id", "") or monitor.get("monitor_id", "") or "")

    automation_tier = _datadog_automation_tier(mtype)
    target_rule_type = _datadog_target_rule_type(mtype)
    eval_win = _parse_datadog_query_time_window(query)
    no_data = _datadog_no_data_policy(opts)
    condition_summary = _summarize_datadog_condition(monitor)
    message = str(monitor.get("message", "") or "")
    priority = monitor.get("priority")
    severity = str(priority) if priority is not None else ""

    metadata: dict[str, Any] = {
        "datadog_type": mtype,
        "tags": monitor.get("tags") or [],
    }
    if monitor.get("multi") is not None:
        metadata["multi"] = monitor.get("multi")

    ir = AlertingIR(
        alert_id=alert_id,
        name=name,
        kind=kind,
        source_ref=str(monitor.get("id", "") or ""),
        condition_summary=condition_summary,
        evaluation_window=eval_win,
        severity=severity,
        no_data_policy=no_data,
        metadata=metadata,
        source_extension=dict(monitor),
        automation_tier=automation_tier,
        target_rule_type=target_rule_type,
        notification_summary=message[:2000] if message else "",
    )

    if field_map is not None:
        try:
            from observability_migration.adapters.source.datadog.monitor_translate import (
                translate_monitor_to_alert_query,
            )
        except ImportError:
            return ir

        translation = translate_monitor_to_alert_query(monitor, field_map)
        if translation.translated_query:
            ir.translated_query = translation.translated_query
            ir.translated_query_provenance = translation.translated_query_provenance
            ir.group_by = list(translation.group_by)
        if translation.warnings:
            ir.warnings.extend(w for w in translation.warnings if w not in ir.warnings)

    return ir


def _grafana_unified_evaluation_window(rule: dict[str, Any]) -> str:
    data = rule.get("data")
    if not isinstance(data, list) or not data:
        return ""
    first = data[0]
    if not isinstance(first, dict):
        return ""
    rtr = first.get("relativeTimeRange")
    if not isinstance(rtr, dict):
        return ""
    from_sec = rtr.get("from")
    if from_sec is None:
        return ""
    try:
        s = int(from_sec)
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    if s % 3600 == 0:
        return f"{s // 3600}h"
    if s % 60 == 0:
        return f"{s // 60}m"
    return f"{s}s"


def _grafana_source_queries(
    data: list[dict[str, Any]],
    datasource_map: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    queries: list[dict[str, Any]] = []
    used_datasources: dict[str, dict[str, Any]] = {}
    ds_map = datasource_map if isinstance(datasource_map, dict) else {}

    for item in data:
        if not isinstance(item, dict):
            continue
        datasource_uid = str(item.get("datasourceUid", "") or "")
        if not datasource_uid or datasource_uid == "__expr__":
            continue
        model = item.get("model") if isinstance(item.get("model"), dict) else {}
        expr = str(model.get("expr", "") or "")
        ds_meta = ds_map.get(datasource_uid, {}) if isinstance(ds_map.get(datasource_uid), dict) else {}
        queries.append(
            {
                "ref_id": str(item.get("refId", "") or ""),
                "datasource_uid": datasource_uid,
                "datasource_type": str(ds_meta.get("type", "") or ""),
                "datasource_name": str(ds_meta.get("name", "") or ""),
                "expr": expr,
            }
        )
        if ds_meta:
            used_datasources[datasource_uid] = {
                "uid": datasource_uid,
                "type": str(ds_meta.get("type", "") or ""),
                "name": str(ds_meta.get("name", "") or ""),
            }

    return queries, used_datasources


def build_alerting_ir_from_grafana_unified(
    rule: dict[str, Any],
    datasource_map: dict[str, dict[str, Any]] | None = None,
) -> AlertingIR:
    """Build an AlertingIR from a Grafana Unified Alerting provisioned rule dict."""
    title = str(rule.get("title", "") or "")
    uid = str(rule.get("uid", "") or "")
    alert_id = uid if uid else title
    condition = str(rule.get("condition", "") or "")
    data = rule.get("data") if isinstance(rule.get("data"), list) else []
    labels = rule.get("labels") if isinstance(rule.get("labels"), dict) else {}

    annotations = rule.get("annotations")
    if not isinstance(annotations, dict):
        annotations = {}

    cond_bits = [title, f"condition={condition}"] if condition else [title]
    condition_summary = "; ".join(cond_bits)

    pending = str(rule.get("for", "") or "")
    source_queries, used_datasources = _grafana_source_queries(data, datasource_map)

    source_extension: dict[str, Any] = {
        "data": data,
        "labels": dict(labels),
        "annotations": dict(annotations),
        "source_queries": source_queries,
        "datasource_map": used_datasources,
    }

    ann_summary = " ".join(f"{k}={v}" for k, v in annotations.items() if v)[:2000]

    return AlertingIR(
        alert_id=alert_id,
        name=title,
        kind="grafana_unified",
        source_ref=uid,
        condition_summary=condition_summary,
        evaluation_window=_grafana_unified_evaluation_window(rule),
        severity="",
        no_data_policy=str(rule.get("noDataState", "") or ""),
        metadata={
            "exec_err_state": str(rule.get("execErrState", "") or ""),
            "grafana_condition": condition,
            "datasource_types": sorted(
                {q["datasource_type"] for q in source_queries if q.get("datasource_type")}
            ),
        },
        source_extension=source_extension,
        automation_tier="draft_requires_review",
        target_rule_type="es-query",
        pending_period=pending,
        notification_summary=ann_summary,
    )


__all__ = [
    "AlertingIR",
    "build_alerting_ir_from_datadog",
    "build_alerting_ir_from_grafana",
    "build_alerting_ir_from_grafana_unified",
]
