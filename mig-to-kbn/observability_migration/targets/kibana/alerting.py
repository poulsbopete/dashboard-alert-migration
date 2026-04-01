"""Kibana Serverless alerting and connector API client.

Provides rule-type discovery, connector management, rule lifecycle,
and capability preflight for the alert migration pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from observability_migration.targets.kibana.compile import kibana_url_for_space

logger = logging.getLogger(__name__)


def _api_base(kibana_url: str, space_id: str = "") -> str:
    base = kibana_url_for_space(kibana_url, space_id).rstrip("/")
    if space_id and not base.endswith(f"/s/{space_id}"):
        base = f"{base}/s/{space_id}"
    return base


def _session(api_key: str = "") -> requests.Session:
    session = requests.Session()
    session.headers.update({"kbn-xsrf": "true"})
    if api_key:
        session.headers["Authorization"] = f"ApiKey {api_key}"
    return session


# ---------------------------------------------------------------------------
# Discovery / preflight
# ---------------------------------------------------------------------------

def get_alerting_health(
    kibana_url: str, *, api_key: str = "", space_id: str = "", timeout: int = 15,
) -> dict[str, Any]:
    """GET /api/alerting/_health — alerting subsystem health."""
    session = _session(api_key)
    base = _api_base(kibana_url, space_id)
    try:
        resp = session.get(f"{base}/api/alerting/_health", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("alerting health check failed: %s", exc)
        return {"error": str(exc)}


def list_rule_types(
    kibana_url: str, *, api_key: str = "", space_id: str = "", timeout: int = 15,
) -> list[dict[str, Any]]:
    """GET /api/alerting/rule_types — discover available rule families."""
    session = _session(api_key)
    base = _api_base(kibana_url, space_id)
    try:
        resp = session.get(f"{base}/api/alerting/rule_types", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("failed to list rule types: %s", exc)
        return []


def list_connector_types(
    kibana_url: str, *, api_key: str = "", space_id: str = "", timeout: int = 15,
) -> list[dict[str, Any]]:
    """GET /api/actions/connector_types — discover available connector families."""
    session = _session(api_key)
    base = _api_base(kibana_url, space_id)
    try:
        resp = session.get(f"{base}/api/actions/connector_types", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("failed to list connector types: %s", exc)
        return []


def list_connectors(
    kibana_url: str, *, api_key: str = "", space_id: str = "", timeout: int = 15,
) -> list[dict[str, Any]]:
    """GET /api/actions/connectors — list all existing connectors."""
    session = _session(api_key)
    base = _api_base(kibana_url, space_id)
    try:
        resp = session.get(f"{base}/api/actions/connectors", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("failed to list connectors: %s", exc)
        return []


def run_alerting_preflight(
    kibana_url: str, *, api_key: str = "", space_id: str = "", timeout: int = 15,
) -> dict[str, Any]:
    """Run a full alerting capability preflight against the target Kibana.

    Returns a structured report including:
    - health status
    - available rule type IDs
    - available connector type IDs
    - existing connector count
    - whether key rule families are present
    """
    health = get_alerting_health(kibana_url, api_key=api_key, space_id=space_id, timeout=timeout)
    rule_types = list_rule_types(kibana_url, api_key=api_key, space_id=space_id, timeout=timeout)
    connector_types = list_connector_types(kibana_url, api_key=api_key, space_id=space_id, timeout=timeout)
    connectors = list_connectors(kibana_url, api_key=api_key, space_id=space_id, timeout=timeout)

    rule_type_ids = {rt.get("id", "") for rt in rule_types}
    connector_type_ids = {ct.get("id", "") for ct in connector_types}
    enabled_connector_types = {
        ct.get("id", "") for ct in connector_types
        if ct.get("enabled") and ct.get("enabled_in_config")
    }

    KEY_RULE_FAMILIES = {
        "es-query": ".es-query",
        "index-threshold": ".index-threshold",
        "custom-threshold": "observability.rules.custom_threshold",
        "metric-threshold": "metrics.alert.threshold",
        "log-threshold": "logs.alert.document.count",
    }

    rule_family_availability = {}
    for family_name, rule_type_id in KEY_RULE_FAMILIES.items():
        rule_family_availability[family_name] = rule_type_id in rule_type_ids

    return {
        "health": health,
        "rule_types_count": len(rule_types),
        "rule_type_ids": sorted(rule_type_ids),
        "connector_types_count": len(connector_types),
        "enabled_connector_type_ids": sorted(enabled_connector_types),
        "existing_connectors": len(connectors),
        "existing_connector_ids": [c.get("id", "") for c in connectors],
        "rule_family_availability": rule_family_availability,
        "can_create_es_query_rules": rule_family_availability.get("es-query", False),
        "can_create_index_threshold_rules": rule_family_availability.get("index-threshold", False),
        "can_create_custom_threshold_rules": rule_family_availability.get("custom-threshold", False),
    }


# ---------------------------------------------------------------------------
# Connector lifecycle
# ---------------------------------------------------------------------------

def create_connector(
    kibana_url: str,
    *,
    connector_type_id: str,
    name: str,
    config: dict[str, Any] | None = None,
    secrets: dict[str, Any] | None = None,
    api_key: str = "",
    space_id: str = "",
    timeout: int = 15,
) -> dict[str, Any]:
    """POST /api/actions/connector — create a new connector."""
    session = _session(api_key)
    base = _api_base(kibana_url, space_id)
    body: dict[str, Any] = {
        "connector_type_id": connector_type_id,
        "name": name,
    }
    if config:
        body["config"] = config
    if secrets:
        body["secrets"] = secrets
    try:
        resp = session.post(f"{base}/api/actions/connector", json=body, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("failed to create connector '%s': %s", name, exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Rule lifecycle
# ---------------------------------------------------------------------------

def create_rule(
    kibana_url: str,
    *,
    rule_type_id: str,
    name: str,
    consumer: str = "alerts",
    schedule_interval: str = "1m",
    params: dict[str, Any] | None = None,
    actions: list[dict[str, Any]] | None = None,
    enabled: bool = False,
    tags: list[str] | None = None,
    api_key: str = "",
    space_id: str = "",
    timeout: int = 15,
) -> dict[str, Any]:
    """POST /api/alerting/rule — create a new alerting rule.

    Rules are created disabled by default for safety.
    """
    session = _session(api_key)
    base = _api_base(kibana_url, space_id)
    body: dict[str, Any] = {
        "rule_type_id": rule_type_id,
        "name": name,
        "consumer": consumer,
        "schedule": {"interval": schedule_interval},
        "params": params or {},
        "actions": actions or [],
        "enabled": enabled,
        "tags": tags or ["obs-migration"],
    }
    try:
        resp = session.post(f"{base}/api/alerting/rule", json=body, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("failed to create rule '%s': %s", name, exc)
        return {"error": str(exc)}


def list_rules(
    kibana_url: str, *, api_key: str = "", space_id: str = "", timeout: int = 15,
    per_page: int = 100, page: int = 1,
) -> dict[str, Any]:
    """GET /api/alerting/rules/_find — list existing rules."""
    session = _session(api_key)
    base = _api_base(kibana_url, space_id)
    try:
        resp = session.get(
            f"{base}/api/alerting/rules/_find",
            params={"per_page": per_page, "page": page},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("failed to list rules: %s", exc)
        return {"error": str(exc), "data": [], "total": 0}


def delete_rule(
    kibana_url: str,
    rule_id: str,
    *,
    api_key: str = "",
    space_id: str = "",
    timeout: int = 15,
) -> bool:
    """DELETE /api/alerting/rule/{id}."""
    session = _session(api_key)
    base = _api_base(kibana_url, space_id)
    try:
        resp = session.delete(f"{base}/api/alerting/rule/{rule_id}", timeout=timeout)
        return resp.status_code == 204
    except Exception as exc:
        logger.warning("failed to delete rule %s: %s", rule_id, exc)
        return False


def enable_rule(
    kibana_url: str,
    rule_id: str,
    *,
    api_key: str = "",
    space_id: str = "",
    timeout: int = 15,
) -> bool:
    """POST /api/alerting/rule/{id}/_enable."""
    session = _session(api_key)
    base = _api_base(kibana_url, space_id)
    try:
        resp = session.post(f"{base}/api/alerting/rule/{rule_id}/_enable", timeout=timeout)
        return resp.status_code in {200, 204}
    except Exception as exc:
        logger.warning("failed to enable rule %s: %s", rule_id, exc)
        return False


def disable_rule(
    kibana_url: str,
    rule_id: str,
    *,
    api_key: str = "",
    space_id: str = "",
    timeout: int = 15,
) -> bool:
    """POST /api/alerting/rule/{id}/_disable."""
    session = _session(api_key)
    base = _api_base(kibana_url, space_id)
    try:
        resp = session.post(f"{base}/api/alerting/rule/{rule_id}/_disable", timeout=timeout)
        return resp.status_code in {200, 204}
    except Exception as exc:
        logger.warning("failed to disable rule %s: %s", rule_id, exc)
        return False


# ---------------------------------------------------------------------------
# Dry-run validation
# ---------------------------------------------------------------------------

def validate_rule_payload(
    rule_type_id: str,
    params: dict[str, Any],
    preflight: dict[str, Any],
) -> dict[str, Any]:
    """Validate a rule payload against the preflight capability report.

    Returns {"valid": bool, "errors": [...], "warnings": [...]}.
    Does NOT make any API calls — purely local structural validation.
    """
    errors: list[str] = []
    warnings: list[str] = []

    available = preflight.get("rule_family_availability", {})

    RULE_TYPE_MAP = {
        ".es-query": "es-query",
        ".index-threshold": "index-threshold",
        "observability.rules.custom_threshold": "custom-threshold",
    }
    family_key = RULE_TYPE_MAP.get(rule_type_id, "")
    if family_key and not available.get(family_key, False):
        errors.append(f"Rule type '{rule_type_id}' is not available in the target Kibana")

    if not rule_type_id:
        errors.append("rule_type_id is required")
    if not params:
        errors.append("params must not be empty")

    if rule_type_id == ".es-query":
        if "esqlQuery" not in params and "searchType" not in params and "esQuery" not in params:
            warnings.append("ES query rule params should contain esqlQuery, esQuery, or searchType")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


__all__ = [
    "create_connector",
    "create_rule",
    "delete_rule",
    "disable_rule",
    "enable_rule",
    "get_alerting_health",
    "list_connector_types",
    "list_connectors",
    "list_rule_types",
    "list_rules",
    "run_alerting_preflight",
    "validate_rule_payload",
]
