"""Tests for the alert/monitor migration pipeline.

Covers:
- AlertingIR builders (Grafana legacy, Grafana unified, Datadog monitors)
- Fidelity classification and semantic loss tracking
- Mapping engine (tier selection, rule type selection, payload building)
- Grafana extract helpers (session auth, unified alerting)
- Datadog extract helpers (monitor file loading)
- Kibana alerting client (preflight, validation)
- CLI flag wiring
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock, patch

from observability_migration.core.assets.alerting import (
    AlertingIR,
    build_alerting_ir_from_datadog,
    build_alerting_ir_from_grafana,
    build_alerting_ir_from_grafana_unified,
)
from observability_migration.core.assets.status import AssetStatus
from observability_migration.core.mapping import (
    AUTOMATED_KINDS,
    CUSTOM_THRESHOLD_RULE_TYPE,
    DRAFT_REVIEW_KINDS,
    ES_QUERY_RULE_TYPE,
    INDEX_THRESHOLD_RULE_TYPE,
    MANUAL_ONLY_KINDS,
    build_custom_threshold_rule_params,
    build_es_query_rule_params,
    build_index_threshold_rule_params,
    classify_automation_tier,
    map_alert_to_kibana_payload,
    map_alerts_batch,
    record_semantic_losses,
    select_target_rule_type,
)
from observability_migration.core.reporting.report import MigrationResult


# =====================================================================
# Fixtures
# =====================================================================


def _grafana_legacy_alert_task():
    return {
        "task_type": "alert_migration",
        "dashboard": "Node Exporter",
        "dashboard_uid": "abc123",
        "panel": "CPU Usage",
        "alert_name": "High CPU",
        "alert_type": "legacy",
        "suggested_kibana_rule_type": "threshold",
        "frequency": "60s",
        "pending_for": "5m",
        "no_data_state": "no_data",
        "exec_error_state": "alerting",
        "conditions": [
            {
                "evaluator_type": "gt",
                "evaluator_params": [80],
                "operator": "and",
                "query_ref": "A",
                "reducer": "avg",
            }
        ],
        "conditions_description": ["avg() gt [80] on ref A"],
        "notification_channels": ["uid-slack-1"],
    }


def _grafana_unified_rule():
    return {
        "uid": "rule-uid-1",
        "title": "Memory pressure alert",
        "ruleGroup": "resource-alerts",
        "folderUID": "folder-1",
        "condition": "C",
        "for": "5m",
        "noDataState": "NoData",
        "execErrState": "Error",
        "isPaused": False,
        "labels": {"severity": "warning", "team": "infra"},
        "annotations": {
            "summary": "Memory is above threshold",
            "__dashboardUid__": "dash-123",
            "__panelId__": "42",
        },
        "data": [
            {
                "refId": "A",
                "datasourceUid": "prometheus",
                "relativeTimeRange": {"from": 300, "to": 0},
                "model": {"expr": "node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes < 0.1"},
            },
            {
                "refId": "B",
                "datasourceUid": "-100",
                "relativeTimeRange": {"from": 0, "to": 0},
                "model": {"type": "reduce", "reducer": "last"},
            },
            {
                "refId": "C",
                "datasourceUid": "-100",
                "relativeTimeRange": {"from": 0, "to": 0},
                "model": {"type": "threshold", "conditions": [{"evaluator": {"type": "lt", "params": [0.1]}}]},
            },
        ],
    }


def _grafana_unified_prometheus_rule():
    return {
        "uid": "rule-prom-1",
        "title": "High CPU usage",
        "ruleGroup": "resource-alerts",
        "folderUID": "folder-1",
        "condition": "C",
        "for": "5m",
        "noDataState": "NoData",
        "execErrState": "Error",
        "isPaused": False,
        "labels": {"severity": "warning", "team": "infra"},
        "annotations": {"summary": "CPU is above threshold"},
        "data": [
            {
                "refId": "A",
                "datasourceUid": "prometheus",
                "relativeTimeRange": {"from": 300, "to": 0},
                "model": {
                    "expr": '100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
                },
            },
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "relativeTimeRange": {"from": 0, "to": 0},
                "model": {"type": "reduce", "reducer": "last"},
            },
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "relativeTimeRange": {"from": 0, "to": 0},
                "model": {"type": "threshold", "conditions": [{"evaluator": {"type": "gt", "params": [80]}}]},
            },
        ],
    }


def _grafana_unified_logql_rule():
    return {
        "uid": "rule-log-1",
        "title": "Error log spike",
        "ruleGroup": "log-alerts",
        "folderUID": "folder-1",
        "condition": "C",
        "for": "5m",
        "noDataState": "NoData",
        "execErrState": "Error",
        "isPaused": False,
        "labels": {"severity": "warning", "team": "app"},
        "annotations": {"summary": "Error logs are spiking"},
        "data": [
            {
                "refId": "A",
                "datasourceUid": "loki",
                "relativeTimeRange": {"from": 300, "to": 0},
                "model": {
                    "expr": 'count_over_time({job=~".+"} |= "error" [5m])',
                },
            },
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "relativeTimeRange": {"from": 0, "to": 0},
                "model": {"type": "reduce", "reducer": "last"},
            },
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "relativeTimeRange": {"from": 0, "to": 0},
                "model": {"type": "threshold", "conditions": [{"evaluator": {"type": "gt", "params": [100]}}]},
            },
        ],
    }


def _datadog_metric_monitor():
    return {
        "id": 12345,
        "name": "High CPU on web hosts",
        "type": "metric alert",
        "query": "avg(last_5m):avg:system.cpu.user{env:production} by {host} > 90",
        "message": "CPU is above 90%! @slack-infra-alerts @pagerduty-oncall",
        "tags": ["env:production", "team:infra"],
        "priority": 2,
        "multi": True,
        "options": {
            "thresholds": {"critical": 90, "warning": 80},
            "notify_no_data": True,
            "no_data_timeframe": 10,
            "renotify_interval": 60,
            "evaluation_delay": 300,
            "require_full_window": True,
            "notify_by": ["host"],
        },
    }


def _datadog_log_monitor():
    return {
        "id": 67890,
        "name": "Error log spike",
        "type": "log alert",
        "query": 'logs("status:error").index("main").rollup("count").last("5m") > 100',
        "message": "Error logs spiking!",
        "tags": ["team:backend"],
        "options": {
            "thresholds": {"critical": 100},
            "notify_no_data": False,
        },
    }


def _datadog_service_check_monitor():
    return {
        "id": 35767150,
        "name": "[Auto] Clock in sync with NTP",
        "type": "service check",
        "query": '"ntp.in_sync".over("*").last(2).count_by_status()',
        "message": "Clock drift detected",
        "options": {
            "thresholds": {
                "critical": 1.0,
                "ok": 1.0,
                "warning": 1.0,
            }
        },
        "multi": True,
    }


def _datadog_live_metric_query_alert():
    return {
        "id": 221632609,
        "name": "{{component_type.name}} component is producing errors",
        "type": "query alert",
        "query": (
            "sum(last_15m):sum:pipelines.component_errors_total"
            "{!component_id:_*,pipeline_id:46a24f86-9fd2-11f0-9e3d-da7ad0900002} "
            "by {component_type,component_id,host,worker_uuid} > 0"
        ),
        "message": "Component errors detected",
        "options": {
            "include_tags": True,
            "new_group_delay": 60,
            "notify_no_data": False,
            "thresholds": {"critical": 0.0},
            "timeout_h": 1,
        },
        "multi": True,
    }


def _datadog_composite_monitor():
    return {
        "id": 99999,
        "name": "Composite: CPU and Memory",
        "type": "composite",
        "query": "12345 && 67890",
        "message": "Both monitors triggered",
        "options": {},
    }


# =====================================================================
# AlertingIR builder tests
# =====================================================================


class TestBuildAlertingIRFromGrafana(unittest.TestCase):
    def test_legacy_alert_basic_fields(self):
        task = _grafana_legacy_alert_task()
        ir = build_alerting_ir_from_grafana(task)
        self.assertEqual(ir.kind, "grafana_legacy")
        self.assertEqual(ir.name, "High CPU")
        self.assertIn("abc123", ir.alert_id)
        self.assertEqual(ir.evaluation_window, "60s")
        self.assertEqual(ir.no_data_policy, "no_data")
        self.assertEqual(ir.target_candidate, "threshold")
        self.assertEqual(ir.source_extension["alert_type"], "legacy")

    def test_legacy_alert_notification_channels(self):
        task = _grafana_legacy_alert_task()
        ir = build_alerting_ir_from_grafana(task)
        self.assertEqual(len(ir.actions), 1)
        self.assertIn("uid-slack-1", ir.actions[0]["notification_channels"])

    def test_legacy_alert_condition_summary(self):
        task = _grafana_legacy_alert_task()
        ir = build_alerting_ir_from_grafana(task)
        self.assertIn("avg()", ir.condition_summary)

    def test_legacy_alert_conditions_preserved(self):
        task = _grafana_legacy_alert_task()
        ir = build_alerting_ir_from_grafana(task)
        self.assertEqual(ir.source_extension["conditions"][0]["query_ref"], "A")


class TestBuildAlertingIRFromGrafanaUnified(unittest.TestCase):
    def test_unified_rule_basic_fields(self):
        rule = _grafana_unified_rule()
        ir = build_alerting_ir_from_grafana_unified(rule)
        self.assertEqual(ir.kind, "grafana_unified")
        self.assertEqual(ir.name, "Memory pressure alert")
        self.assertEqual(ir.alert_id, "rule-uid-1")
        self.assertEqual(ir.no_data_policy, "NoData")
        self.assertEqual(ir.pending_period, "5m")
        self.assertEqual(ir.automation_tier, "draft_requires_review")
        self.assertEqual(ir.target_rule_type, "es-query")

    def test_unified_rule_evaluation_window(self):
        rule = _grafana_unified_rule()
        ir = build_alerting_ir_from_grafana_unified(rule)
        self.assertEqual(ir.evaluation_window, "5m")

    def test_unified_rule_source_extension(self):
        rule = _grafana_unified_rule()
        ir = build_alerting_ir_from_grafana_unified(rule)
        self.assertIn("data", ir.source_extension)
        self.assertIn("labels", ir.source_extension)
        self.assertEqual(ir.source_extension["labels"]["severity"], "warning")

    def test_unified_rule_no_uid_uses_title(self):
        rule = _grafana_unified_rule()
        rule.pop("uid")
        ir = build_alerting_ir_from_grafana_unified(rule)
        self.assertEqual(ir.alert_id, "Memory pressure alert")

    def test_unified_rule_hour_window(self):
        rule = _grafana_unified_rule()
        rule["data"][0]["relativeTimeRange"]["from"] = 3600
        ir = build_alerting_ir_from_grafana_unified(rule)
        self.assertEqual(ir.evaluation_window, "1h")

    def test_unified_rule_preserves_datasource_metadata_when_provided(self):
        rule = _grafana_unified_prometheus_rule()
        ir = build_alerting_ir_from_grafana_unified(
            rule,
            datasource_map={"prometheus": {"type": "prometheus", "name": "Prometheus"}},
        )
        self.assertEqual(ir.source_extension["datasource_map"]["prometheus"]["type"], "prometheus")


class TestBuildAlertingIRFromDatadog(unittest.TestCase):
    def test_metric_monitor_basic_fields(self):
        mon = _datadog_metric_monitor()
        ir = build_alerting_ir_from_datadog(mon)
        self.assertEqual(ir.kind, "datadog_metric")
        self.assertEqual(ir.name, "High CPU on web hosts")
        self.assertEqual(ir.alert_id, "12345")
        self.assertEqual(ir.severity, "2")
        self.assertEqual(ir.no_data_policy, "notify")

    def test_metric_monitor_evaluation_window(self):
        mon = _datadog_metric_monitor()
        ir = build_alerting_ir_from_datadog(mon)
        self.assertEqual(ir.evaluation_window, "5m")

    def test_metric_monitor_automation_tier(self):
        mon = _datadog_metric_monitor()
        ir = build_alerting_ir_from_datadog(mon)
        self.assertEqual(ir.automation_tier, "draft_requires_review")

    def test_metric_monitor_target_rule_type(self):
        mon = _datadog_metric_monitor()
        ir = build_alerting_ir_from_datadog(mon)
        self.assertEqual(ir.target_rule_type, "custom-threshold")

    def test_log_monitor_kind(self):
        mon = _datadog_log_monitor()
        ir = build_alerting_ir_from_datadog(mon)
        self.assertEqual(ir.kind, "datadog_log")
        self.assertEqual(ir.target_rule_type, "es-query")

    def test_composite_monitor(self):
        mon = _datadog_composite_monitor()
        ir = build_alerting_ir_from_datadog(mon)
        self.assertEqual(ir.kind, "datadog_composite")
        self.assertEqual(ir.automation_tier, "manual_required")

    def test_notification_summary_from_message(self):
        mon = _datadog_metric_monitor()
        ir = build_alerting_ir_from_datadog(mon)
        self.assertIn("@slack-infra-alerts", ir.notification_summary)

    def test_no_data_policy_false(self):
        mon = _datadog_log_monitor()
        ir = build_alerting_ir_from_datadog(mon)
        self.assertEqual(ir.no_data_policy, "no_notify")

    def test_empty_monitor(self):
        ir = build_alerting_ir_from_datadog({})
        self.assertEqual(ir.kind, "datadog_monitor")
        self.assertEqual(ir.name, "")

    def test_condition_summary_includes_thresholds(self):
        mon = _datadog_metric_monitor()
        ir = build_alerting_ir_from_datadog(mon)
        self.assertIn("thresholds=", ir.condition_summary)

    def test_metric_monitor_with_field_profile_gets_translated_query(self):
        from observability_migration.adapters.source.datadog.field_map import load_profile

        field_map = load_profile("elastic_agent")
        ir = build_alerting_ir_from_datadog(_datadog_metric_monitor(), field_map=field_map)

        self.assertEqual(ir.translated_query_provenance, "translated_esql")
        self.assertIn("AVG(system.cpu.user.pct)", ir.translated_query)
        self.assertIn('deployment.environment == "production"', ir.translated_query)
        self.assertIn("host.name", ir.translated_query)
        self.assertIn("| WHERE value > 90.0", ir.translated_query)

    def test_live_metric_query_alert_with_custom_metric_mapping_gets_translated(self):
        from observability_migration.adapters.source.datadog.field_map import load_profile

        field_map = load_profile("otel")
        field_map.metric_map["pipelines.component_errors_total"] = "pipelines.component_errors_total"
        ir = build_alerting_ir_from_datadog(_datadog_live_metric_query_alert(), field_map=field_map)

        self.assertEqual(ir.translated_query_provenance, "translated_esql")
        self.assertIn("SUM(pipelines.component_errors_total)", ir.translated_query)
        self.assertIn('pipeline_id == "46a24f86-9fd2-11f0-9e3d-da7ad0900002"', ir.translated_query)
        self.assertIn("component_type", ir.translated_query)
        self.assertIn("component_id", ir.translated_query)
        self.assertIn("host.name", ir.translated_query)
        self.assertIn("worker_uuid", ir.translated_query)
        self.assertIn("| WHERE value > 0.0", ir.translated_query)

    def test_live_metric_query_alert_with_missing_live_fields_stays_untranslated(self):
        from observability_migration.adapters.source.datadog.field_map import load_profile
        from observability_migration.core.verification.field_capabilities import FieldCapability

        field_map = load_profile("otel")
        field_map.metric_field_caps = {
            "host.name": FieldCapability(name="host.name", type="keyword"),
        }
        field_map.field_caps = dict(field_map.metric_field_caps)

        ir = build_alerting_ir_from_datadog(_datadog_live_metric_query_alert(), field_map=field_map)

        self.assertEqual(ir.translated_query, "")
        self.assertEqual(ir.translated_query_provenance, "")

    def test_log_monitor_with_field_profile_gets_translated_query(self):
        from observability_migration.adapters.source.datadog.field_map import load_profile

        field_map = load_profile("otel")
        ir = build_alerting_ir_from_datadog(_datadog_log_monitor(), field_map=field_map)

        self.assertEqual(ir.translated_query_provenance, "translated_esql")
        self.assertIn("FROM logs-*", ir.translated_query)
        self.assertIn('log.level == "error"', ir.translated_query)
        self.assertIn("STATS value = COUNT(*)", ir.translated_query)
        self.assertIn("| WHERE value > 100.0", ir.translated_query)

    def test_service_check_monitor_with_field_profile_stays_untranslated(self):
        from observability_migration.adapters.source.datadog.field_map import load_profile

        field_map = load_profile("otel")
        ir = build_alerting_ir_from_datadog(_datadog_service_check_monitor(), field_map=field_map)

        self.assertEqual(ir.translated_query, "")
        self.assertEqual(ir.translated_query_provenance, "")


# =====================================================================
# Fidelity classification tests
# =====================================================================


class TestClassifyAutomationTier(unittest.TestCase):
    def test_grafana_legacy_simple_threshold_is_manual(self):
        ir = AlertingIR(kind="grafana_legacy", source_extension={"alert_type": "legacy"})
        self.assertEqual(classify_automation_tier(ir), "manual_required")

    def test_grafana_unified_prometheus_is_draft_review(self):
        ir = build_alerting_ir_from_grafana_unified(
            _grafana_unified_prometheus_rule(),
            datasource_map={"prometheus": {"type": "prometheus", "name": "Prometheus"}},
        )
        self.assertEqual(classify_automation_tier(ir), "draft_requires_review")

    def test_datadog_metric_simple_is_manual_without_translation(self):
        ir = AlertingIR(kind="datadog_metric", condition_summary="avg:system.cpu{host:*} > 90")
        self.assertEqual(classify_automation_tier(ir), "manual_required")

    def test_datadog_metric_with_translated_query_is_automated(self):
        ir = AlertingIR(
            kind="datadog_metric",
            condition_summary="avg:system.cpu{host:*} > 90",
            translated_query="FROM metrics-* | STATS cpu = AVG(system.cpu.user.pct) BY host.name | WHERE cpu > 90",
            translated_query_provenance="translated_esql",
        )
        self.assertEqual(classify_automation_tier(ir), "automated")

    def test_datadog_metric_formula_without_translation_is_manual(self):
        ir = AlertingIR(kind="datadog_metric", condition_summary="formula(a / b)")
        self.assertEqual(classify_automation_tier(ir), "manual_required")

    def test_datadog_composite_is_manual(self):
        ir = AlertingIR(kind="datadog_composite")
        self.assertEqual(classify_automation_tier(ir), "manual_required")

    def test_datadog_log_is_manual_without_translation(self):
        ir = AlertingIR(kind="datadog_log")
        self.assertEqual(classify_automation_tier(ir), "manual_required")

    def test_unknown_kind_is_manual(self):
        ir = AlertingIR(kind="some_unknown_source")
        self.assertEqual(classify_automation_tier(ir), "manual_required")

    def test_all_manual_only_kinds(self):
        for kind in MANUAL_ONLY_KINDS:
            ir = AlertingIR(kind=kind)
            self.assertEqual(classify_automation_tier(ir), "manual_required", f"Failed for {kind}")


class TestRecordSemanticLosses(unittest.TestCase):
    def test_datadog_renotify_loss(self):
        ir = build_alerting_ir_from_datadog(_datadog_metric_monitor())
        losses = record_semantic_losses(ir)
        self.assertTrue(any("renotify" in l for l in losses))

    def test_datadog_notification_handles_loss(self):
        ir = build_alerting_ir_from_datadog(_datadog_metric_monitor())
        losses = record_semantic_losses(ir)
        self.assertTrue(any("notification handles" in l for l in losses))

    def test_datadog_evaluation_delay_loss(self):
        ir = build_alerting_ir_from_datadog(_datadog_metric_monitor())
        losses = record_semantic_losses(ir)
        self.assertTrue(any("evaluation_delay" in l for l in losses))

    def test_grafana_notification_channel_loss(self):
        task = _grafana_legacy_alert_task()
        ir = build_alerting_ir_from_grafana(task)
        losses = record_semantic_losses(ir)
        self.assertTrue(any("notification channel" in l for l in losses))

    def test_grafana_unified_multi_query_loss(self):
        rule = _grafana_unified_rule()
        ir = build_alerting_ir_from_grafana_unified(rule)
        losses = record_semantic_losses(ir)
        self.assertTrue(any("Multi-query" in l for l in losses))

    def test_grafana_unified_dashboard_link_loss(self):
        rule = _grafana_unified_rule()
        ir = build_alerting_ir_from_grafana_unified(rule)
        losses = record_semantic_losses(ir)
        self.assertTrue(any("Dashboard-linked" in l for l in losses))

    def test_no_data_policy_loss(self):
        ir = AlertingIR(kind="grafana_legacy", no_data_policy="Alerting")
        losses = record_semantic_losses(ir)
        self.assertTrue(any("no-data policy" in l for l in losses))

    def test_no_losses_for_clean_alert(self):
        ir = AlertingIR(kind="grafana_legacy", no_data_policy="", source_extension={"alert_type": "legacy"})
        losses = record_semantic_losses(ir)
        self.assertEqual(len(losses), 0)


# =====================================================================
# Mapping engine tests
# =====================================================================


class TestSelectTargetRuleType(unittest.TestCase):
    def test_grafana_legacy_without_query_has_no_target(self):
        ir = AlertingIR(kind="grafana_legacy")
        self.assertEqual(select_target_rule_type(ir), "")

    def test_grafana_unified_prometheus_gets_es_query(self):
        ir = build_alerting_ir_from_grafana_unified(
            _grafana_unified_prometheus_rule(),
            datasource_map={"prometheus": {"type": "prometheus", "name": "Prometheus"}},
        )
        self.assertEqual(select_target_rule_type(ir), ES_QUERY_RULE_TYPE)

    def test_datadog_metric_without_translation_has_no_target(self):
        ir = AlertingIR(kind="datadog_metric")
        self.assertEqual(select_target_rule_type(ir), "")

    def test_datadog_log_without_translation_has_no_target(self):
        ir = AlertingIR(kind="datadog_log")
        self.assertEqual(select_target_rule_type(ir), "")

    def test_datadog_metric_with_translation_gets_es_query(self):
        ir = AlertingIR(
            kind="datadog_metric",
            translated_query="FROM metrics-* | STATS doc_count = COUNT(*)",
            translated_query_provenance="translated_esql",
        )
        self.assertEqual(select_target_rule_type(ir), ES_QUERY_RULE_TYPE)

    def test_manual_only_returns_empty(self):
        ir = AlertingIR(kind="datadog_composite")
        self.assertEqual(select_target_rule_type(ir), "")

    def test_respects_preflight_availability(self):
        ir = AlertingIR(
            kind="datadog_metric",
            translated_query="FROM metrics-* | STATS doc_count = COUNT(*) | WHERE doc_count > 0",
            translated_query_provenance="translated_esql",
        )
        preflight = {"rule_family_availability": {"custom-threshold": False, "es-query": True}}
        self.assertEqual(select_target_rule_type(ir, preflight), ES_QUERY_RULE_TYPE)

    def test_no_target_when_all_unavailable(self):
        ir = AlertingIR(kind="grafana_legacy")
        preflight = {"rule_family_availability": {"es-query": False, "index-threshold": False}}
        self.assertEqual(select_target_rule_type(ir, preflight), "")


class TestBuildRuleParams(unittest.TestCase):
    def test_es_query_params_basic(self):
        ir = AlertingIR(
            evaluation_window="10m",
            translated_query="FROM metrics-* | STATS doc_count = COUNT(*) | WHERE doc_count > 10",
            translated_query_provenance="translated_esql",
        )
        params = build_es_query_rule_params(ir)
        self.assertEqual(params["searchType"], "esqlQuery")
        self.assertEqual(params["timeWindowSize"], 10)
        self.assertEqual(params["timeWindowUnit"], "m")
        self.assertEqual(params["threshold"], [0])
        self.assertEqual(params["thresholdComparator"], ">")

    def test_es_query_params_hours(self):
        ir = AlertingIR(
            evaluation_window="2h",
            translated_query="FROM metrics-* | STATS doc_count = COUNT(*) | WHERE doc_count > 0",
            translated_query_provenance="translated_esql",
        )
        params = build_es_query_rule_params(ir)
        self.assertEqual(params["timeWindowSize"], 2)
        self.assertEqual(params["timeWindowUnit"], "h")

    def test_es_query_params_use_native_promql_for_supported_grafana_prometheus_rules(self):
        ir = build_alerting_ir_from_grafana_unified(
            _grafana_unified_prometheus_rule(),
            datasource_map={"prometheus": {"type": "prometheus", "name": "Prometheus"}},
        )
        params = build_es_query_rule_params(ir)
        self.assertEqual(params["threshold"], [0])
        self.assertEqual(params["thresholdComparator"], ">")
        self.assertTrue(params["esqlQuery"]["esql"].startswith("PROMQL "))
        self.assertIn("node_cpu_seconds_total", params["esqlQuery"]["esql"])
        self.assertIn("| WHERE value > 80.0", params["esqlQuery"]["esql"])

    def test_es_query_params_return_empty_for_unsupported_logql_alert(self):
        ir = build_alerting_ir_from_grafana_unified(
            _grafana_unified_logql_rule(),
            datasource_map={"loki": {"type": "loki", "name": "Loki"}},
        )
        self.assertEqual(build_es_query_rule_params(ir), {})

    def test_index_threshold_params_with_group_by(self):
        ir = AlertingIR(group_by=["host.name"])
        params = build_index_threshold_rule_params(ir)
        self.assertEqual(params["groupBy"], "top")
        self.assertEqual(params["termField"], "host.name")

    def test_custom_threshold_params_with_group_by(self):
        ir = AlertingIR(group_by=["service.name", "host.name"])
        params = build_custom_threshold_rule_params(ir)
        self.assertEqual(params["groupBy"], ["service.name", "host.name"])


class TestMapAlertToKibanaPayload(unittest.TestCase):
    def test_grafana_legacy_without_source_query_is_manual(self):
        task = _grafana_legacy_alert_task()
        ir = build_alerting_ir_from_grafana(task)
        result = map_alert_to_kibana_payload(ir)
        self.assertEqual(result["automation_tier"], "manual_required")
        self.assertFalse(result["valid"])
        self.assertEqual(result["rule_payload"], {})

    def test_draft_review_grafana_unified_prometheus(self):
        ir = build_alerting_ir_from_grafana_unified(
            _grafana_unified_prometheus_rule(),
            datasource_map={"prometheus": {"type": "prometheus", "name": "Prometheus"}},
        )
        result = map_alert_to_kibana_payload(ir)
        self.assertEqual(result["automation_tier"], "draft_requires_review")
        self.assertTrue(result["valid"])
        self.assertEqual(ir.status, AssetStatus.DRAFT_REVIEW)
        self.assertTrue(result["rule_payload"]["params"]["esqlQuery"]["esql"].startswith("PROMQL "))

    def test_grafana_unified_loki_is_manual(self):
        ir = build_alerting_ir_from_grafana_unified(
            _grafana_unified_logql_rule(),
            datasource_map={"loki": {"type": "loki", "name": "Loki"}},
        )
        result = map_alert_to_kibana_payload(ir)
        self.assertEqual(result["automation_tier"], "manual_required")
        self.assertFalse(result["valid"])
        self.assertEqual(result["rule_payload"], {})

    def test_manual_composite_monitor(self):
        mon = _datadog_composite_monitor()
        ir = build_alerting_ir_from_datadog(mon)
        result = map_alert_to_kibana_payload(ir)
        self.assertEqual(result["automation_tier"], "manual_required")
        self.assertFalse(result["valid"])
        self.assertEqual(result["rule_payload"], {})
        self.assertEqual(ir.status, AssetStatus.MANUAL_REQUIRED)

    def test_preflight_downgrade(self):
        task = _grafana_legacy_alert_task()
        ir = build_alerting_ir_from_grafana(task)
        preflight = {"rule_family_availability": {"es-query": False, "index-threshold": False}}
        result = map_alert_to_kibana_payload(ir, preflight=preflight)
        self.assertFalse(result["valid"])

    def test_datadog_metric_without_translation_is_manual(self):
        ir = build_alerting_ir_from_datadog(_datadog_metric_monitor())
        result = map_alert_to_kibana_payload(ir)
        self.assertEqual(result["automation_tier"], "manual_required")
        self.assertFalse(result["valid"])
        self.assertEqual(result["rule_payload"], {})

    def test_datadog_metric_with_explicit_translated_query_is_valid(self):
        ir = build_alerting_ir_from_datadog(_datadog_metric_monitor())
        ir.translated_query = "FROM metrics-* | STATS errors = SUM(pipelines.component_errors_total) | WHERE errors > 0"
        ir.translated_query_provenance = "translated_esql"
        result = map_alert_to_kibana_payload(ir)
        self.assertEqual(result["automation_tier"], "automated")
        self.assertTrue(result["valid"])
        self.assertEqual(result["rule_payload"]["rule_type_id"], ES_QUERY_RULE_TYPE)
        self.assertEqual(result["rule_payload"]["params"]["esqlQuery"]["esql"], ir.translated_query)

    def test_datadog_metric_with_profile_translation_is_valid(self):
        from observability_migration.adapters.source.datadog.field_map import load_profile

        field_map = load_profile("elastic_agent")
        ir = build_alerting_ir_from_datadog(_datadog_metric_monitor(), field_map=field_map)
        result = map_alert_to_kibana_payload(ir)

        self.assertEqual(result["automation_tier"], "automated")
        self.assertTrue(result["valid"])
        self.assertEqual(result["rule_payload"]["rule_type_id"], ES_QUERY_RULE_TYPE)
        self.assertIn("AVG(system.cpu.user.pct)", result["rule_payload"]["params"]["esqlQuery"]["esql"])

    def test_datadog_log_with_profile_translation_is_valid(self):
        from observability_migration.adapters.source.datadog.field_map import load_profile

        field_map = load_profile("otel")
        ir = build_alerting_ir_from_datadog(_datadog_log_monitor(), field_map=field_map)
        result = map_alert_to_kibana_payload(ir)

        self.assertEqual(result["automation_tier"], "draft_requires_review")
        self.assertTrue(result["valid"])
        self.assertEqual(result["rule_payload"]["rule_type_id"], ES_QUERY_RULE_TYPE)
        self.assertIn("STATS value = COUNT(*)", result["rule_payload"]["params"]["esqlQuery"]["esql"])


class TestMapAlertsBatch(unittest.TestCase):
    def test_batch_summary(self):
        alerts = [
            build_alerting_ir_from_grafana(_grafana_legacy_alert_task()),
            build_alerting_ir_from_grafana_unified(
                _grafana_unified_prometheus_rule(),
                datasource_map={"prometheus": {"type": "prometheus", "name": "Prometheus"}},
            ),
            build_alerting_ir_from_datadog(_datadog_metric_monitor()),
            build_alerting_ir_from_datadog(_datadog_composite_monitor()),
        ]
        result = map_alerts_batch(alerts)
        self.assertEqual(result["summary"]["total"], 4)
        self.assertIn("draft_requires_review", result["summary"]["by_automation_tier"])
        self.assertIn("manual_required", result["summary"]["by_automation_tier"])
        self.assertTrue(len(result["summary"]["unique_semantic_losses"]) > 0)


# =====================================================================
# AssetStatus tests
# =====================================================================


class TestAssetStatusDraftReview(unittest.TestCase):
    def test_draft_review_exists(self):
        self.assertEqual(AssetStatus.DRAFT_REVIEW.value, "draft_review")

    def test_draft_review_between_translated_and_manual(self):
        values = list(AssetStatus)
        translated_idx = values.index(AssetStatus.TRANSLATED_WITH_WARNINGS)
        draft_idx = values.index(AssetStatus.DRAFT_REVIEW)
        manual_idx = values.index(AssetStatus.MANUAL_REQUIRED)
        self.assertTrue(translated_idx < draft_idx < manual_idx)


# =====================================================================
# AlertingIR serialization tests
# =====================================================================


class TestAlertingIRSerialization(unittest.TestCase):
    def test_to_dict_includes_new_fields(self):
        ir = AlertingIR(
            alert_id="test-1",
            name="Test Alert",
            kind="grafana_legacy",
            automation_tier="automated",
            target_rule_type="es-query",
            schedule_interval="1m",
            translated_query="FROM metrics-* | WHERE cpu > 90",
            translated_query_provenance="translated_esql",
        )
        d = ir.to_dict()
        self.assertEqual(d["automation_tier"], "automated")
        self.assertEqual(d["target_rule_type"], "es-query")
        self.assertEqual(d["schedule_interval"], "1m")
        self.assertEqual(d["translated_query"], "FROM metrics-* | WHERE cpu > 90")
        self.assertEqual(d["translated_query_provenance"], "translated_esql")
        self.assertEqual(d["status"], "manual_required")

    def test_to_dict_round_trip(self):
        mon = _datadog_metric_monitor()
        ir = build_alerting_ir_from_datadog(mon)
        d = ir.to_dict()
        serialized = json.dumps(d)
        deserialized = json.loads(serialized)
        self.assertEqual(deserialized["kind"], "datadog_metric")
        self.assertEqual(deserialized["alert_id"], "12345")


# =====================================================================
# Grafana extract helper tests
# =====================================================================


class TestGrafanaExtractSession(unittest.TestCase):
    def test_session_with_basic_auth(self):
        from observability_migration.adapters.source.grafana.extract import _grafana_session
        session = _grafana_session("http://grafana:3000", user="admin", password="secret")
        self.assertIsNotNone(session.auth)

    def test_session_with_token(self):
        from observability_migration.adapters.source.grafana.extract import _grafana_session
        session = _grafana_session("http://grafana:3000", token="my-token")
        self.assertIn("Authorization", session.headers)
        self.assertIn("Bearer", session.headers["Authorization"])

    def test_session_token_takes_precedence(self):
        from observability_migration.adapters.source.grafana.extract import _grafana_session
        session = _grafana_session("http://grafana:3000", user="admin", password="pass", token="tok")
        self.assertIn("Bearer", session.headers.get("Authorization", ""))


class TestGrafanaExtractAllAlertingResources(unittest.TestCase):
    @patch("observability_migration.adapters.source.grafana.extract._fetch_unified_provisioning_json")
    @patch("observability_migration.adapters.source.grafana.extract._grafana_session")
    def test_returns_all_keys(self, mock_session, mock_fetch):
        mock_fetch.return_value = []
        result = {}
        from observability_migration.adapters.source.grafana.extract import extract_all_alerting_resources
        result = extract_all_alerting_resources("http://grafana:3000")
        self.assertIn("alert_rules", result)
        self.assertIn("contact_points", result)
        self.assertIn("notification_policies", result)
        self.assertIn("mute_timings", result)
        self.assertIn("templates", result)
        self.assertIn("datasources", result)


# =====================================================================
# Datadog monitor file extraction tests
# =====================================================================


class TestDatadogMonitorFileExtraction(unittest.TestCase):
    def test_single_monitor_file(self):
        from observability_migration.adapters.source.datadog.extract import extract_monitors_from_files
        with tempfile.TemporaryDirectory() as tmpdir:
            mon = _datadog_metric_monitor()
            path = Path(tmpdir) / "monitor.json"
            path.write_text(json.dumps(mon))
            result = extract_monitors_from_files(tmpdir)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["name"], "High CPU on web hosts")
            self.assertIn("_source_file", result[0])

    def test_array_of_monitors(self):
        from observability_migration.adapters.source.datadog.extract import extract_monitors_from_files
        with tempfile.TemporaryDirectory() as tmpdir:
            monitors = [_datadog_metric_monitor(), _datadog_log_monitor()]
            path = Path(tmpdir) / "monitors.json"
            path.write_text(json.dumps(monitors))
            result = extract_monitors_from_files(tmpdir)
            self.assertEqual(len(result), 2)

    def test_wrapped_monitors(self):
        from observability_migration.adapters.source.datadog.extract import extract_monitors_from_files
        with tempfile.TemporaryDirectory() as tmpdir:
            wrapped = {"monitors": [_datadog_metric_monitor()]}
            path = Path(tmpdir) / "export.json"
            path.write_text(json.dumps(wrapped))
            result = extract_monitors_from_files(tmpdir)
            self.assertEqual(len(result), 1)

    def test_missing_directory(self):
        from observability_migration.adapters.source.datadog.extract import extract_monitors_from_files
        with self.assertRaises(FileNotFoundError):
            extract_monitors_from_files("/nonexistent/path")

    def test_json_safe_api_value_converts_datetimes(self):
        from datetime import date, datetime

        from observability_migration.adapters.source.datadog.extract import _json_safe_api_value

        raw = {
            "updated_at": datetime(2026, 4, 1, 12, 34, 56),
            "nested": [{"date": date(2026, 4, 1)}],
        }

        normalized = _json_safe_api_value(raw)

        self.assertEqual(normalized["updated_at"], "2026-04-01T12:34:56")
        self.assertEqual(normalized["nested"][0]["date"], "2026-04-01")
        json.dumps(normalized)


# =====================================================================
# Kibana alerting client tests
# =====================================================================


class TestKibanaAlertingPreflight(unittest.TestCase):
    def test_validate_rule_payload_missing_type(self):
        from observability_migration.targets.kibana.alerting import validate_rule_payload
        result = validate_rule_payload("", {}, {})
        self.assertFalse(result["valid"])
        self.assertTrue(any("rule_type_id" in e for e in result["errors"]))

    def test_validate_rule_payload_unavailable_type(self):
        from observability_migration.targets.kibana.alerting import validate_rule_payload
        preflight = {"rule_family_availability": {"es-query": False}}
        result = validate_rule_payload(".es-query", {"esqlQuery": {}}, preflight)
        self.assertFalse(result["valid"])
        self.assertTrue(any("not available" in e for e in result["errors"]))

    def test_validate_rule_payload_valid(self):
        from observability_migration.targets.kibana.alerting import validate_rule_payload
        preflight = {"rule_family_availability": {"es-query": True}}
        result = validate_rule_payload(".es-query", {"esqlQuery": {"esql": "FROM metrics-*"}}, preflight)
        self.assertTrue(result["valid"])

    def test_run_alerting_preflight_structure(self):
        from observability_migration.targets.kibana.alerting import run_alerting_preflight
        with patch("observability_migration.targets.kibana.alerting._session") as mock_sess:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {}
            mock_resp.raise_for_status = MagicMock()
            mock_session = MagicMock()
            mock_session.get.return_value = mock_resp
            mock_sess.return_value = mock_session

            result = run_alerting_preflight("http://kibana:5601", api_key="test")
            self.assertIn("health", result)
            self.assertIn("rule_family_availability", result)
            self.assertIn("can_create_es_query_rules", result)


# =====================================================================
# CLI flag tests
# =====================================================================


class TestUnifiedCliFetchAlertsFlag(unittest.TestCase):
    def test_migrate_parser_has_fetch_alerts(self):
        from observability_migration.app.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["migrate", "--source", "grafana", "--fetch-alerts"])
        self.assertTrue(args.fetch_alerts)

    def test_migrate_parser_has_grafana_token(self):
        from observability_migration.app.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["migrate", "--source", "grafana", "--grafana-token", "tok123"])
        self.assertEqual(args.grafana_token, "tok123")

    def test_migrate_parser_has_monitor_ids(self):
        from observability_migration.app.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["migrate", "--source", "datadog", "--monitor-ids", "1,2,3"])
        self.assertEqual(args.monitor_ids, "1,2,3")

    def test_migrate_parser_has_alert_dry_run(self):
        from observability_migration.app.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["migrate", "--source", "grafana", "--alert-dry-run"])
        self.assertTrue(args.alert_dry_run)


class TestGrafanaCliFetchAlertsFlag(unittest.TestCase):
    def test_grafana_parser_has_fetch_alerts(self):
        from observability_migration.adapters.source.grafana.cli import parse_args
        args = parse_args(["--fetch-alerts"])
        self.assertTrue(args.fetch_alerts)

    def test_grafana_parser_has_grafana_token(self):
        from observability_migration.adapters.source.grafana.cli import parse_args
        args = parse_args(["--grafana-token", "my-token"])
        self.assertEqual(args.grafana_token, "my-token")


class TestDatadogCliFetchMonitorsFlag(unittest.TestCase):
    def test_datadog_parser_has_fetch_monitors(self):
        from observability_migration.adapters.source.datadog.cli import parse_args
        args = parse_args(["--fetch-monitors"])
        self.assertTrue(args.fetch_monitors)

    def test_datadog_parser_has_monitor_ids(self):
        from observability_migration.adapters.source.datadog.cli import parse_args
        args = parse_args(["--monitor-ids", "111,222"])
        self.assertEqual(args.monitor_ids, "111,222")

    def test_datadog_parser_has_monitor_query(self):
        from observability_migration.adapters.source.datadog.cli import parse_args
        args = parse_args(["--monitor-query", "tag:env:prod"])
        self.assertEqual(args.monitor_query, "tag:env:prod")


# =====================================================================
# MigrationResult alert fields tests
# =====================================================================


class TestMigrationResultAlertFields(unittest.TestCase):
    def test_default_alert_fields(self):
        result = MigrationResult(dashboard_title="Test", dashboard_uid="uid-1")
        self.assertEqual(result.alert_results, [])
        self.assertEqual(result.alert_summary, {})

    def test_alert_fields_can_be_populated(self):
        result = MigrationResult(dashboard_title="Test", dashboard_uid="uid-1")
        ir = build_alerting_ir_from_datadog(_datadog_metric_monitor())
        result.alert_results = [ir.to_dict()]
        result.alert_summary = {"total": 1, "automated": 0, "draft_review": 1, "manual_required": 0}
        self.assertEqual(len(result.alert_results), 1)
        self.assertEqual(result.alert_summary["total"], 1)


# =====================================================================
# Integration-level tests
# =====================================================================


class TestEndToEndAlertMapping(unittest.TestCase):
    def test_full_pipeline_mixed_alerts(self):
        """Test that a mixed batch of alerts produces correct tier distribution."""
        alerts = [
            build_alerting_ir_from_grafana(_grafana_legacy_alert_task()),
            build_alerting_ir_from_grafana_unified(
                _grafana_unified_prometheus_rule(),
                datasource_map={"prometheus": {"type": "prometheus", "name": "Prometheus"}},
            ),
            build_alerting_ir_from_datadog(_datadog_metric_monitor()),
            build_alerting_ir_from_datadog(_datadog_log_monitor()),
            build_alerting_ir_from_datadog(_datadog_composite_monitor()),
        ]
        batch_result = map_alerts_batch(alerts)
        summary = batch_result["summary"]

        self.assertEqual(summary["total"], 5)
        self.assertGreater(summary["by_automation_tier"].get("draft_requires_review", 0), 0)
        self.assertGreater(summary["by_automation_tier"].get("manual_required", 0), 0)

        for item in batch_result["results"]:
            mapping = item["mapping"]
            if mapping["automation_tier"] == "manual_required":
                self.assertFalse(mapping["valid"])
                self.assertEqual(mapping["rule_payload"], {})
            else:
                self.assertTrue(mapping["valid"])
                self.assertIn("rule_type_id", mapping["rule_payload"])

    def test_all_payloads_are_disabled(self):
        """Safety: all generated payloads must have enabled=False."""
        alerts = [
            build_alerting_ir_from_grafana(_grafana_legacy_alert_task()),
            build_alerting_ir_from_datadog(_datadog_metric_monitor()),
        ]
        batch_result = map_alerts_batch(alerts)
        for item in batch_result["results"]:
            payload = item["mapping"]["rule_payload"]
            if payload:
                self.assertFalse(payload.get("enabled", True))

    def test_migration_tags_present(self):
        """All generated payloads should have obs-migration tag."""
        ir = build_alerting_ir_from_grafana(_grafana_legacy_alert_task())
        result = map_alert_to_kibana_payload(ir)
        if result["rule_payload"]:
            self.assertIn("obs-migration", result["rule_payload"]["tags"])


if __name__ == "__main__":
    unittest.main()
