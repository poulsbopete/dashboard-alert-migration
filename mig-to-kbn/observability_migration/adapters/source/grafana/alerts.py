"""Extract Grafana legacy alert rules and model them as migration tasks.

Grafana alerting and Kibana alerting have fundamentally different models:

- **Grafana legacy alerts** are embedded in panels (``panel.alert``).
- **Kibana alerting** uses rule types (ES query, threshold, anomaly detection)
  tied to connectors and actions.

This module extracts legacy alert definitions from dashboard JSON and produces
structured migration task descriptors that tell the customer exactly what
needs to be recreated in Kibana.
"""

from __future__ import annotations

from typing import Any


def _extract_legacy_alert(panel: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a Grafana legacy alert from a panel's ``alert`` field."""
    alert = panel.get("alert")
    if not alert or not isinstance(alert, dict):
        return None

    name = str(alert.get("name", "") or panel.get("title", "") or "")
    message = str(alert.get("message", "") or "")
    frequency = str(alert.get("frequency", "") or "")
    pending_for = str(alert.get("for", "") or "")
    conditions = alert.get("conditions") or []
    notifications = alert.get("notifications") or []
    no_data_state = str(alert.get("noDataState", "") or "")
    exec_error_state = str(alert.get("executionErrorState", "") or "")

    parsed_conditions: list[dict[str, Any]] = []
    for cond in conditions:
        if not isinstance(cond, dict):
            continue
        evaluator = cond.get("evaluator") or {}
        operator_info = cond.get("operator") or {}
        query_info = cond.get("query") or {}
        reducer_info = cond.get("reducer") or {}
        parsed_conditions.append({
            "evaluator_type": evaluator.get("type", ""),
            "evaluator_params": evaluator.get("params", []),
            "operator": operator_info.get("type", ""),
            "query_ref": query_info.get("params", [""])[0] if query_info.get("params") else "",
            "query_from": query_info.get("params", ["", ""])[1] if len(query_info.get("params", [])) > 1 else "",
            "query_to": query_info.get("params", ["", "", ""])[2] if len(query_info.get("params", [])) > 2 else "",
            "reducer": reducer_info.get("type", ""),
        })

    notification_channels = [
        str(n.get("uid", "") or n.get("id", "") or "")
        for n in notifications if isinstance(n, dict)
    ]

    return {
        "alert_type": "legacy",
        "name": name,
        "message": message,
        "frequency": frequency,
        "pending_for": pending_for,
        "no_data_state": no_data_state,
        "exec_error_state": exec_error_state,
        "conditions": parsed_conditions,
        "notification_channels": notification_channels,
    }


def _iter_dashboard_panels(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    panels: list[dict[str, Any]] = []
    for panel in dashboard.get("panels", []) or []:
        panels.append(panel)
        panels.extend(panel.get("panels", []) or [])
    for row in dashboard.get("rows", []) or []:
        panels.extend(row.get("panels", []) or [])
    return panels


def extract_alerts_from_dashboard(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract legacy panel-embedded alert definitions from a dashboard."""
    alerts: list[dict[str, Any]] = []
    dashboard_title = str(dashboard.get("title", "") or "")
    dashboard_uid = str(dashboard.get("uid", "") or "")

    all_panels = _iter_dashboard_panels(dashboard)
    for panel in all_panels:
        legacy = _extract_legacy_alert(panel)
        if legacy:
            legacy["source_panel_title"] = str(panel.get("title", "") or "")
            legacy["source_panel_id"] = str(panel.get("id", "") or "")
            legacy["dashboard_title"] = dashboard_title
            legacy["dashboard_uid"] = dashboard_uid
            alerts.append(legacy)

    return alerts


def _suggest_kibana_rule_type(alert: dict[str, Any]) -> str:
    """Suggest the closest Kibana rule type for a Grafana alert."""
    conditions = alert.get("conditions") or []
    if not conditions:
        return "threshold"
    for cond in conditions:
        eval_type = str(cond.get("evaluator_type", "")).lower()
        if eval_type in ("gt", "lt", "within_range", "outside_range"):
            return "threshold"
    return "es_query"


def build_alert_migration_tasks(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert extracted alerts into structured migration task descriptors."""
    tasks: list[dict[str, Any]] = []
    for alert in alerts:
        suggested_type = _suggest_kibana_rule_type(alert)
        conditions_desc = []
        for cond in alert.get("conditions", []):
            reducer = cond.get("reducer", "")
            eval_type = cond.get("evaluator_type", "")
            params = cond.get("evaluator_params", [])
            param_str = ", ".join(str(p) for p in params)
            conditions_desc.append(
                f"{reducer}() {eval_type} [{param_str}] on ref {cond.get('query_ref', '?')}"
            )

        tasks.append({
            "task_type": "alert_migration",
            "dashboard": alert.get("dashboard_title", ""),
            "dashboard_uid": alert.get("dashboard_uid", ""),
            "panel": alert.get("source_panel_title", ""),
            "alert_name": alert.get("name", ""),
            "alert_type": alert.get("alert_type", "legacy"),
            "suggested_kibana_rule_type": suggested_type,
            "frequency": alert.get("frequency", ""),
            "pending_for": alert.get("pending_for", ""),
            "no_data_state": alert.get("no_data_state", ""),
            "exec_error_state": alert.get("exec_error_state", ""),
            "conditions": alert.get("conditions", []),
            "conditions_description": conditions_desc,
            "notification_channels": alert.get("notification_channels", []),
            "description": (
                f"Alert '{alert.get('name', '')}' on panel '{alert.get('source_panel_title', '')}' "
                f"→ Kibana {suggested_type} rule. "
                f"Conditions: {'; '.join(conditions_desc) or 'none extracted'}. "
                f"Notifications to: {', '.join(alert.get('notification_channels', [])) or 'none'}."
            ),
        })
    return tasks


def build_alert_summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize alert migration tasks."""
    if not tasks:
        return {"total": 0, "by_type": {}, "by_kibana_type": {}}

    by_type: dict[str, int] = {}
    by_kibana: dict[str, int] = {}
    for task in tasks:
        t = task.get("alert_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        k = task.get("suggested_kibana_rule_type", "unknown")
        by_kibana[k] = by_kibana.get(k, 0) + 1

    return {
        "total": len(tasks),
        "by_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
        "by_kibana_type": dict(sorted(by_kibana.items(), key=lambda x: -x[1])),
    }


__all__ = [
    "build_alert_migration_tasks",
    "build_alert_summary",
    "extract_alerts_from_dashboard",
]
