"""Rule-mapping engine for alert/monitor migration.

Takes AlertingIR instances and produces Kibana rule payloads for safely
mappable cases, or downgrades the automation tier and records semantic
losses for cases that cannot be automatically translated.
"""

from __future__ import annotations

import re
from typing import Any

from observability_migration.core.assets.alerting import AlertingIR
from observability_migration.core.assets.status import AssetStatus


# ---- Kibana rule type IDs ----
ES_QUERY_RULE_TYPE = ".es-query"
INDEX_THRESHOLD_RULE_TYPE = ".index-threshold"
CUSTOM_THRESHOLD_RULE_TYPE = "observability.rules.custom_threshold"

# ---- Fidelity classification ----

AUTOMATED_KINDS = {"grafana_legacy", "datadog_metric"}
DRAFT_REVIEW_KINDS = {"grafana_unified", "datadog_log"}
MANUAL_ONLY_KINDS = {
    "datadog_composite",
    "datadog_service_check",
    "datadog_event",
    "datadog_rum",
    "datadog_apm",
    "datadog_synthetics",
    "datadog_ci",
    "datadog_slo",
    "datadog_audit",
    "datadog_cost",
    "datadog_network",
    "datadog_watchdog",
    "datadog_forecast",
    "datadog_outlier",
    "datadog_anomaly_alert",
}


def classify_automation_tier(ir: AlertingIR) -> str:
    """Determine the automation tier for an alert IR.

    Returns one of: "automated", "draft_requires_review", "manual_required".
    """
    if ir.kind in MANUAL_ONLY_KINDS:
        return "manual_required"

    if ir.kind == "grafana_legacy":
        if _has_source_faithful_query(ir) and _has_simple_threshold_condition(ir):
            return "automated"
        return "manual_required"

    if ir.kind == "grafana_unified":
        if _has_source_faithful_query(ir):
            return "draft_requires_review"
        return "manual_required"

    if ir.kind == "datadog_metric":
        if not _has_source_faithful_query(ir):
            return "manual_required"
        if _has_simple_threshold_condition(ir):
            return "automated"
        return "draft_requires_review"

    if ir.kind == "datadog_log":
        if _has_source_faithful_query(ir):
            return "draft_requires_review"
        return "manual_required"

    if ir.kind in DRAFT_REVIEW_KINDS:
        return "draft_requires_review"

    return "manual_required"


def _has_simple_threshold_condition(ir: AlertingIR) -> bool:
    """Check if the alert has a simple threshold condition amenable to automation."""
    ext = ir.source_extension or {}

    if ir.kind == "grafana_legacy":
        conditions = ext.get("conditions") if isinstance(ext.get("conditions"), list) else []
        if not conditions:
            alert_type = ext.get("alert_type", "")
            return alert_type == "legacy"
        for cond in conditions:
            if not isinstance(cond, dict):
                return False
            eval_type = str(cond.get("evaluator_type", "")).lower()
            if eval_type not in ("gt", "lt", "within_range", "outside_range"):
                return False
        return True

    if ir.kind == "datadog_metric":
        query = ir.condition_summary or ""
        if "formula(" in query.lower() or "||" in query or "&&" in query:
            return False
        return True

    return False


def _primary_source_query(ir: AlertingIR) -> dict[str, str]:
    """Return the first non-expression source query for an alert, if present."""
    ext = ir.source_extension or {}
    queries = ext.get("source_queries")
    if isinstance(queries, list):
        for item in queries:
            if not isinstance(item, dict):
                continue
            expr = str(item.get("expr", "") or "")
            if not expr:
                continue
            return {
                "expr": expr,
                "datasource_uid": str(item.get("datasource_uid", "") or ""),
                "datasource_type": str(item.get("datasource_type", "") or ""),
                "datasource_name": str(item.get("datasource_name", "") or ""),
            }

    data_list = ext.get("data")
    if not isinstance(data_list, list):
        return {}

    raw_datasource_map = ext.get("datasource_map")
    datasource_map: dict[str, Any] = raw_datasource_map if isinstance(raw_datasource_map, dict) else {}
    for item in data_list:
        if not isinstance(item, dict):
            continue
        datasource_uid = str(item.get("datasourceUid", "") or "")
        if not datasource_uid or datasource_uid == "__expr__":
            continue
        raw_model = item.get("model")
        model = raw_model if isinstance(raw_model, dict) else {}
        expr = str(model.get("expr", "") or "")
        raw_ds_meta = datasource_map.get(datasource_uid)
        ds_meta = raw_ds_meta if isinstance(raw_ds_meta, dict) else {}
        if expr:
            return {
                "expr": expr,
                "datasource_uid": datasource_uid,
                "datasource_type": str(ds_meta.get("type", "") or ""),
                "datasource_name": str(ds_meta.get("name", "") or ""),
            }
    return {}


def _source_query_language(source_query: dict[str, str]) -> str:
    expr = str(source_query.get("expr", "") or "")
    datasource_type = str(source_query.get("datasource_type", "") or "").lower()
    if not expr:
        return "unknown"
    if "loki" in datasource_type:
        return "logql"
    if "prom" in datasource_type or "mimir" in datasource_type:
        return "promql"
    if "|=" in expr or "|~" in expr:
        return "logql"
    return "promql"


def _has_explicit_threshold(ir: AlertingIR) -> bool:
    ext = ir.source_extension or {}

    if ir.kind == "grafana_unified":
        data_list = ext.get("data")
        if not isinstance(data_list, list):
            return False
        for item in data_list:
            if not isinstance(item, dict):
                continue
            raw_model = item.get("model")
            model = raw_model if isinstance(raw_model, dict) else {}
            if model.get("type") == "threshold":
                return True
        return False

    if ir.kind.startswith("datadog_"):
        query = str(ext.get("query", "") or "")
        if re.search(r"(>=|<=|==|!=|>|<)\s*-?\d+(?:\.\d+)?\s*$", query):
            return True
        raw_opts = ext.get("options")
        opts = raw_opts if isinstance(raw_opts, dict) else {}
        raw_thresholds = opts.get("thresholds")
        thresholds = raw_thresholds if isinstance(raw_thresholds, dict) else {}
        return bool(thresholds)

    return False


def _promql_expr_has_comparison(expr: str) -> bool:
    stripped = re.sub(r'"(?:\\.|[^"])*"', '""', str(expr or ""))
    stripped = re.sub(r"\{[^{}]*\}", "{}", stripped)
    return bool(re.search(r"(==|!=|>=|<=|(?<![=!~<>])>(?![=])|(?<![=!~<>])<(?![=]))", stripped))


def _default_promql_index(data_view: str) -> str:
    index = str(data_view or "").strip()
    if not index or index == "metrics-*":
        return "metrics-prometheus-*"
    return index


def _has_source_faithful_query(ir: AlertingIR) -> bool:
    translated = str(ir.translated_query or "").strip()
    translated_provenance = str(
        ir.translated_query_provenance or ir.metadata.get("translated_query_provenance", "")
    ).strip().lower()
    if translated and translated_provenance in {"translated_esql", "native_promql", "manual_verified"}:
        return True

    if ir.kind != "grafana_unified":
        return False

    source_query = _primary_source_query(ir)
    expr = str(source_query.get("expr", "") or "")
    if not expr or _source_query_language(source_query) != "promql":
        return False

    ds_identity = " ".join(
        [
            str(source_query.get("datasource_type", "") or ""),
            str(source_query.get("datasource_uid", "") or ""),
            str(source_query.get("datasource_name", "") or ""),
        ]
    ).lower()
    if "prom" not in ds_identity and "mimir" not in ds_identity:
        return False

    try:
        from observability_migration.adapters.source.grafana.panels import can_use_native_promql
    except ImportError:
        return False

    return bool(can_use_native_promql(expr))


def record_semantic_losses(ir: AlertingIR) -> list[str]:
    """Identify and record semantic losses for an alert IR."""
    losses: list[str] = []

    if ir.no_data_policy and ir.no_data_policy not in ("", "no_notify"):
        losses.append(f"no-data policy '{ir.no_data_policy}' may not have exact Kibana equivalent")

    ext = ir.source_extension or {}

    if ir.kind.startswith("datadog_"):
        opts = ext.get("options", {}) if isinstance(ext.get("options"), dict) else {}
        if opts.get("renotify_interval"):
            losses.append("Datadog renotify_interval has no direct Kibana equivalent")
        if opts.get("threshold_windows"):
            losses.append("Datadog recovery/trigger threshold windows not directly portable")
        if opts.get("notify_by"):
            losses.append("Datadog notify_by grouping may differ from Kibana group-by behavior")
        if opts.get("evaluation_delay"):
            losses.append("Datadog evaluation_delay not natively supported in Kibana rules")
        if opts.get("require_full_window") is True:
            losses.append("Datadog require_full_window semantics differ from Kibana evaluation")
        msg = str(ext.get("message", "") or "")
        if any(handle in msg for handle in ("@slack-", "@pagerduty-", "@webhook-", "@opsgenie-")):
            losses.append("Datadog notification handles in message require manual connector setup")

    if ir.kind == "grafana_legacy":
        if ext.get("exec_error_state") and ext.get("exec_error_state") != "alerting":
            losses.append(f"Grafana exec_error_state '{ext.get('exec_error_state')}' may differ in Kibana")
        channels = []
        for action in ir.actions or []:
            channels.extend(action.get("notification_channels", []))
        if channels:
            losses.append("Grafana notification channel UIDs require manual connector resolution")

    if ir.kind == "grafana_unified":
        data = ext.get("data", [])
        if isinstance(data, list) and len(data) > 2:
            losses.append("Multi-query unified alerting rule may lose expression graph semantics")
        labels = ext.get("labels", {})
        if labels:
            losses.append("Grafana alert labels not directly portable to Kibana rule tags")
        annotations = ext.get("annotations", {})
        if annotations.get("__dashboardUid__"):
            losses.append("Dashboard-linked alert annotation requires manual Kibana linkage")

    ir.losses = losses
    return losses


def select_target_rule_type(ir: AlertingIR, preflight: dict[str, Any] | None = None) -> str:
    """Select the best Kibana rule type for an alert IR.

    Only returns a rule type when a source-faithful target query is available.
    The current correctness-first path emits `.es-query` rules only.

    Returns the rule_type_id string or empty string if no suitable target.
    """
    availability: dict[str, Any] = {}
    if preflight:
        availability = preflight.get("rule_family_availability", {})

    if ir.kind in MANUAL_ONLY_KINDS or not _has_source_faithful_query(ir):
        return ""

    if availability.get("es-query", True):
        return ES_QUERY_RULE_TYPE
    return ""


def _extract_source_expression(ir: AlertingIR) -> str:
    """Extract the primary source query expression from AlertingIR source_extension."""
    return str(_primary_source_query(ir).get("expr", "") or "")


def _extract_threshold_from_source(ir: AlertingIR) -> tuple[str, float]:
    """Extract (comparator, value) from the Grafana unified alert threshold step."""
    ext = ir.source_extension or {}

    if ir.kind.startswith("datadog_"):
        query = str(ext.get("query", "") or "")
        match = re.search(r"(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$", query)
        if match:
            return match.group(1), float(match.group(2))
        raw_opts = ext.get("options")
        opts = raw_opts if isinstance(raw_opts, dict) else {}
        raw_thresholds = opts.get("thresholds")
        thresholds = raw_thresholds if isinstance(raw_thresholds, dict) else {}
        for key in ("critical", "warning"):
            if key in thresholds:
                try:
                    return ">", float(thresholds[key])
                except (TypeError, ValueError):
                    continue
        return ">", 0.0

    data_list = ext.get("data", [])
    for d in data_list:
        if not isinstance(d, dict):
            continue
        raw_model = d.get("model")
        model = raw_model if isinstance(raw_model, dict) else {}
        if model.get("type") == "threshold":
            for cond in model.get("conditions", []):
                ev = cond.get("evaluator", {})
                ev_type = ev.get("type", "gt")
                params = ev.get("params", [0])
                val = params[0] if params else 0
                comp_map = {"gt": ">", "lt": "<", "gte": ">=", "lte": "<="}
                return comp_map.get(ev_type, ">"), float(val)
    return ">", 0.0


def _generate_esql_for_alert(ir: AlertingIR, data_view: str) -> str:
    """Generate a source-faithful query for an alert rule when possible."""
    if ir.kind != "grafana_unified" or not _has_source_faithful_query(ir):
        return ""

    source_query = _primary_source_query(ir)
    expr = str(source_query.get("expr", "") or "")
    if not expr:
        return ""

    try:
        from observability_migration.adapters.source.grafana.panels import build_native_promql_query
    except ImportError:
        return ""

    query = build_native_promql_query(
        expr,
        index=_default_promql_index(data_view),
        kibana_type="metric",
    )

    if _promql_expr_has_comparison(expr):
        return query
    if not _has_explicit_threshold(ir):
        return ""

    comparator, threshold_val = _extract_threshold_from_source(ir)
    return f"{query} | WHERE value {comparator} {threshold_val}"


def build_es_query_rule_params(ir: AlertingIR, data_view: str = "metrics-*") -> dict[str, Any]:
    """Build Kibana ES query rule params from an AlertingIR."""
    query = str(ir.translated_query or "").strip()
    if not query:
        query = _generate_esql_for_alert(ir, data_view)
    if not query:
        return {}

    params: dict[str, Any] = {
        "searchType": "esqlQuery",
        "esqlQuery": {"esql": query},
        "timeField": "@timestamp",
        "timeWindowSize": 5,
        "timeWindowUnit": "m",
        "threshold": [0],
        "thresholdComparator": ">",
        "size": 100,
    }

    window = ir.evaluation_window
    if window:
        try:
            if window.endswith("m"):
                params["timeWindowSize"] = int(window[:-1])
                params["timeWindowUnit"] = "m"
            elif window.endswith("h"):
                params["timeWindowSize"] = int(window[:-1])
                params["timeWindowUnit"] = "h"
            elif window.endswith("s"):
                params["timeWindowSize"] = int(window[:-1])
                params["timeWindowUnit"] = "s"
        except (ValueError, TypeError):
            pass

    return params


def build_index_threshold_rule_params(ir: AlertingIR, index: str = "metrics-*") -> dict[str, Any]:
    """Build Kibana index threshold rule params from an AlertingIR."""
    params: dict[str, Any] = {
        "index": [index],
        "timeField": "@timestamp",
        "aggType": "count",
        "groupBy": "all",
        "termSize": 5,
        "timeWindowSize": 5,
        "timeWindowUnit": "m",
        "threshold": [0],
        "thresholdComparator": ">",
    }

    if ir.group_by:
        params["groupBy"] = "top"
        params["termField"] = ir.group_by[0] if ir.group_by else ""

    return params


def build_custom_threshold_rule_params(ir: AlertingIR, data_view_id: str = "metrics-*") -> dict[str, Any]:
    """Build Kibana custom threshold rule params from an AlertingIR."""
    params: dict[str, Any] = {
        "criteria": [
            {
                "comparator": ">",
                "threshold": [0],
                "metrics": [
                    {"name": "A", "aggType": "count"},
                ],
                "timeSize": 5,
                "timeUnit": "m",
            }
        ],
        "searchConfiguration": {
            "index": data_view_id,
            "query": {"query": "", "language": "kuery"},
        },
    }

    if ir.group_by:
        params["groupBy"] = ir.group_by

    return params


def map_alert_to_kibana_payload(
    ir: AlertingIR,
    *,
    preflight: dict[str, Any] | None = None,
    data_view: str = "metrics-*",
) -> dict[str, Any]:
    """Map an AlertingIR to a complete Kibana rule creation payload.

    Returns a dict with:
    - "rule_payload": the Kibana API request body (or empty dict if not mappable)
    - "automation_tier": final tier after analysis
    - "target_rule_type": selected rule type ID
    - "losses": semantic losses
    - "valid": whether the payload is valid for creation
    - "validation_errors": list of validation issues
    """
    losses = record_semantic_losses(ir)
    tier = classify_automation_tier(ir)
    rule_type = select_target_rule_type(ir, preflight)

    ir.automation_tier = tier
    ir.target_rule_type = rule_type.replace(".", "").replace("_", "-") if rule_type else ""
    ir.losses = losses

    if tier == "manual_required" or not rule_type:
        ir.status = AssetStatus.MANUAL_REQUIRED
        ir.manual_required = True
        return {
            "rule_payload": {},
            "automation_tier": tier,
            "target_rule_type": rule_type,
            "losses": losses,
            "valid": False,
            "validation_errors": ["No suitable target rule type or alert requires manual migration"],
        }

    if rule_type == ES_QUERY_RULE_TYPE:
        params = build_es_query_rule_params(ir, data_view=data_view)
    elif rule_type == INDEX_THRESHOLD_RULE_TYPE:
        params = build_index_threshold_rule_params(ir, index=data_view)
    elif rule_type == CUSTOM_THRESHOLD_RULE_TYPE:
        params = build_custom_threshold_rule_params(ir, data_view_id=data_view)
    else:
        params = {}

    if not params:
        ir.status = AssetStatus.MANUAL_REQUIRED
        ir.manual_required = True
        return {
            "rule_payload": {},
            "automation_tier": "manual_required",
            "target_rule_type": "",
            "losses": losses,
            "valid": False,
            "validation_errors": ["No source-faithful target query could be produced"],
        }

    schedule = ir.schedule_interval or "1m"

    CONSUMER_MAP = {
        ES_QUERY_RULE_TYPE: "stackAlerts",
        INDEX_THRESHOLD_RULE_TYPE: "stackAlerts",
        CUSTOM_THRESHOLD_RULE_TYPE: "observability",
    }
    consumer = CONSUMER_MAP.get(rule_type, "stackAlerts")

    payload = {
        "rule_type_id": rule_type,
        "name": f"[migrated] {ir.name}" if ir.name else "[migrated] unnamed",
        "consumer": consumer,
        "schedule": {"interval": schedule},
        "params": params,
        "actions": [],
        "enabled": False,
        "tags": ["obs-migration", f"source:{ir.kind}"],
    }

    ir.target_rule_payload = payload

    if tier == "automated":
        ir.status = AssetStatus.TRANSLATED
        ir.manual_required = False
    else:
        ir.status = AssetStatus.DRAFT_REVIEW
        ir.manual_required = False

    validation_errors = []
    if not params:
        validation_errors.append("Empty params generated")

    return {
        "rule_payload": payload,
        "automation_tier": tier,
        "target_rule_type": rule_type,
        "losses": losses,
        "valid": len(validation_errors) == 0,
        "validation_errors": validation_errors,
    }


def map_alerts_batch(
    alerts: list[AlertingIR],
    *,
    preflight: dict[str, Any] | None = None,
    data_view: str = "metrics-*",
) -> dict[str, Any]:
    """Map a batch of AlertingIR instances and return a summary.

    Returns:
    - "results": list of per-alert mapping dicts
    - "summary": aggregate counts by tier and rule type
    """
    results = []
    by_tier: dict[str, int] = {}
    by_rule_type: dict[str, int] = {}
    total_losses: list[str] = []

    for ir in alerts:
        mapping = map_alert_to_kibana_payload(ir, preflight=preflight, data_view=data_view)
        results.append({
            "alert_id": ir.alert_id,
            "name": ir.name,
            "kind": ir.kind,
            "mapping": mapping,
        })
        tier = mapping["automation_tier"]
        by_tier[tier] = by_tier.get(tier, 0) + 1
        rt = mapping["target_rule_type"]
        if rt:
            by_rule_type[rt] = by_rule_type.get(rt, 0) + 1
        total_losses.extend(mapping["losses"])

    unique_losses: dict[str, int] = {}
    for loss in total_losses:
        unique_losses[loss] = unique_losses.get(loss, 0) + 1

    return {
        "results": results,
        "summary": {
            "total": len(alerts),
            "by_automation_tier": by_tier,
            "by_target_rule_type": by_rule_type,
            "unique_semantic_losses": dict(sorted(unique_losses.items(), key=lambda x: -x[1])),
        },
    }


__all__ = [
    "AUTOMATED_KINDS",
    "CUSTOM_THRESHOLD_RULE_TYPE",
    "DRAFT_REVIEW_KINDS",
    "ES_QUERY_RULE_TYPE",
    "INDEX_THRESHOLD_RULE_TYPE",
    "MANUAL_ONLY_KINDS",
    "build_custom_threshold_rule_params",
    "build_es_query_rule_params",
    "build_index_threshold_rule_params",
    "classify_automation_tier",
    "map_alert_to_kibana_payload",
    "map_alerts_batch",
    "record_semantic_losses",
    "select_target_rule_type",
]
