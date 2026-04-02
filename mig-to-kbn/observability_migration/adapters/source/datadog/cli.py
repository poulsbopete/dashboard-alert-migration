"""CLI entry point for the Datadog → Kibana migration tool.

Usage:
    python -m observability_migration.adapters.source.datadog.cli \\
        --source files \\
        --input-dir infra/datadog/dashboards \\
        --output-dir datadog_migration_output \\
        --field-profile otel \\
        --data-view "metrics-*"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import requests

import observability_migration.targets.kibana.adapter  # noqa: F401
from observability_migration.adapters.source.grafana.esql_validate import (
    _query_source_and_index,
    summarize_validation_records,
    validate_query_with_fixes,
)
from observability_migration.adapters.source.grafana.rules import _append_unique
from observability_migration.core.interfaces.registries import target_registry
from observability_migration.targets.kibana.alerting import (
    run_alerting_preflight,
    validate_rule_payload,
)
from observability_migration.targets.kibana.smoke_integration import merge_smoke_into_results

from .extract import (
    extract_dashboards_from_api,
    extract_dashboards_from_files,
    load_credentials_from_env,
)
from .field_map import load_profile
from .generate import generate_dashboard_yaml
from .manifest import save_migration_manifest
from .models import DashboardResult, NormalizedWidget, TranslationResult
from .normalize import normalize_dashboard
from .planner import plan_widget
from .preflight import PreflightResult, run_preflight
from .report import (
    build_monitor_comparison_results,
    build_monitor_migration_results,
    print_report,
    save_detailed_report,
)
from .rollout import build_rollout_plan, generate_review_queue, save_rollout_plan
from .translate import translate_widget
from .verification import (
    annotate_results_with_verification,
    build_monitor_verification_lookup,
    save_verification_packets,
    validate_monitor_queries,
)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    auto_enabled_upload = False
    auto_enabled_validate = False
    target_adapter = target_registry.get("kibana")()
    dd_creds = load_credentials_from_env(args.env_file)

    if args.list_dashboards:
        _handle_list_dashboards(args, target_adapter)
        return
    if args.delete_dashboards:
        _handle_delete_dashboards(args, target_adapter)
        return

    if (args.browser_audit or args.capture_screenshots) and not args.smoke:
        print("  ERROR: --browser-audit and --capture-screenshots require --smoke")
        sys.exit(2)
    if args.smoke and not args.upload:
        args.upload = True
        auto_enabled_upload = True
    compile_requested = args.compile or args.upload

    if args.upload and not args.kibana_url:
        print("  ERROR: --kibana-url is required when --upload is set")
        sys.exit(2)
    if args.smoke and not args.es_url:
        print("  ERROR: --es-url is required when --smoke is set")
        sys.exit(2)
    if args.upload and args.es_url and not args.validate:
        args.validate = True
        auto_enabled_validate = True

    print("\n  Datadog → Kibana Migration Tool v0.1.0")
    print(f"  Source: {args.source}")
    print(f"  Field profile: {args.field_profile}")
    print(f"  Output: {args.output_dir}\n")
    if auto_enabled_upload:
        print("  Smoke requested: auto-enabling upload step\n")
    if args.upload and not args.compile:
        print("  Upload requested: auto-enabling compile step\n")
    if auto_enabled_validate:
        print("  Upload requested with --es-url: auto-enabling validate step\n")

    try:
        field_map = load_profile(args.field_profile)
    except ValueError as exc:
        print(f"  ERROR: {exc}")
        sys.exit(1)
    if args.data_view:
        field_map.metric_index = args.data_view
    if args.logs_index:
        field_map.logs_index = args.logs_index
    if args.dataset_filter:
        field_map.metrics_dataset_filter = args.dataset_filter
    if args.logs_dataset_filter:
        field_map.logs_dataset_filter = args.logs_dataset_filter
    if not field_map.metrics_dataset_filter:
        from .field_map import derive_dataset_from_index
        field_map.metrics_dataset_filter = derive_dataset_from_index(field_map.metric_index)
    if not field_map.logs_dataset_filter:
        from .field_map import derive_dataset_from_index
        field_map.logs_dataset_filter = derive_dataset_from_index(field_map.logs_index)
    _load_live_field_capabilities(field_map, args)

    raw_dashboards = _extract(args)
    if not raw_dashboards:
        print("  ERROR: no dashboards found")
        sys.exit(1)

    print(f"  Found {len(raw_dashboards)} dashboard(s)\n")

    output_dir = Path(args.output_dir)
    yaml_dir = output_dir / "yaml"
    yaml_dir.mkdir(parents=True, exist_ok=True)

    all_results: list[DashboardResult] = []
    dashboard_outputs: list[tuple[DashboardResult, Any]] = []

    for raw in raw_dashboards:
        dashboard = normalize_dashboard(raw)
        print(f"  Processing: {dashboard.title} ({len(dashboard.widgets)} widgets)")

        total_count = len(dashboard.widgets)
        for w in dashboard.widgets:
            total_count += len(w.children)

        dr = DashboardResult(
            dashboard_id=dashboard.id,
            dashboard_title=dashboard.title,
            source_file=dashboard.source_file,
            total_widgets=total_count,
        )
        preflight_result = _run_dashboard_preflight(dashboard, field_map, args)
        if preflight_result is not None:
            dr.preflight_passed = preflight_result.passed
            dr.preflight_issues = [_preflight_issue_to_dict(issue) for issue in preflight_result.issues]
            _print_preflight_summary(preflight_result)

        panel_results: list[TranslationResult] = []

        for widget in dashboard.widgets:
            result = _translate_widget(widget, field_map, args)
            panel_results.append(result)

            if widget.children:
                for child in widget.children:
                    child_result = _translate_widget(child, field_map, args)
                    panel_results.append(child_result)

        dr.panel_results = panel_results

        dashboard_yaml = generate_dashboard_yaml(
            dashboard, panel_results, data_view=field_map.metric_index,
            metrics_dataset_filter=field_map.metrics_dataset_filter,
            logs_dataset_filter=field_map.logs_dataset_filter,
            logs_index=field_map.logs_index,
            field_map=field_map,
        )

        stem = _safe_filename(dashboard.title)
        yaml_path = yaml_dir / f"{stem}.yaml"
        yaml_path.write_text(dashboard_yaml, encoding="utf-8")
        dr.yaml_path = str(yaml_path)

        print(f"    YAML written: {yaml_path}")

        dr.recompute_counts()
        all_results.append(dr)
        dashboard_outputs.append((dr, dashboard))

    validation_records: list[dict[str, Any]] = []
    validation_summary: dict[str, Any] = {}
    if args.validate and args.es_url:
        validation_records, validation_summary = _validate_all_dashboards(
            dashboard_outputs,
            field_map,
            args,
        )
    elif args.validate:
        print("  Validation: skipped (pass --es-url to enable)")

    if compile_requested:
        _compile_all_dashboards(all_results, output_dir, target_adapter)
    if args.upload and args.ensure_data_views:
        _ensure_data_views(args, target_adapter, field_map)
    if args.upload:
        _upload_all_dashboards(all_results, output_dir, args, target_adapter)

    smoke_payload: dict[str, Any] = {}
    if args.smoke:
        smoke_payload = _smoke_uploaded_dashboards(all_results, output_dir, args, target_adapter)

    verification_payload = annotate_results_with_verification(
        all_results,
        validation_records,
        datadog_api_key=dd_creds.get("api_key", ""),
        datadog_app_key=dd_creds.get("app_key", ""),
        datadog_site=dd_creds.get("site", "datadoghq.com"),
    )
    for result in all_results:
        result.verification_summary = {
            "green": sum(1 for pr in result.panel_results if (pr.verification_packet or {}).get("semantic_gate") == "Green"),
            "yellow": sum(1 for pr in result.panel_results if (pr.verification_packet or {}).get("semantic_gate") == "Yellow"),
            "red": sum(1 for pr in result.panel_results if (pr.verification_packet or {}).get("semantic_gate") == "Red"),
        }

    if getattr(args, "fetch_monitors", False):
        print("\n  Extracting Datadog monitors...")
        from observability_migration.adapters.source.datadog.extract import (
            extract_monitors_from_api,
            extract_monitors_from_files,
        )
        from observability_migration.core.assets.alerting import build_alerting_ir_from_datadog
        from observability_migration.core.mapping import map_alerts_batch
        import json as _mon_json

        raw_monitors: list[dict[str, Any]] = []
        if args.source == "api":
            if not dd_creds.get("api_key") or not dd_creds.get("app_key"):
                print("    WARNING: DD_API_KEY and DD_APP_KEY required for monitor extraction")
            else:
                mon_ids = [m.strip() for m in args.monitor_ids.split(",") if m.strip()] if args.monitor_ids else None
                mon_query = getattr(args, "monitor_query", "") or ""
                raw_monitors = extract_monitors_from_api(
                    api_key=dd_creds["api_key"],
                    app_key=dd_creds["app_key"],
                    site=dd_creds.get("site", "datadoghq.com"),
                    monitor_ids=mon_ids,
                    monitor_query=mon_query,
                )
        else:
            monitor_dir = Path(args.input_dir) / "monitors"
            if monitor_dir.is_dir():
                raw_monitors = extract_monitors_from_files(str(monitor_dir))
            else:
                print(f"    No monitors directory at {monitor_dir}")

        if raw_monitors:
            raw_dir = output_dir / "raw_monitors"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / "datadog_monitors.json"
            with raw_path.open("w") as fh:
                _mon_json.dump(raw_monitors, fh, indent=2)
            print(f"    Raw monitors saved: {raw_path} ({len(raw_monitors)} monitors)")

            monitor_irs = []
            for mon in raw_monitors:
                ir = build_alerting_ir_from_datadog(mon, field_map=field_map)
                monitor_irs.append(ir)

            mapping_batch = map_alerts_batch(
                monitor_irs,
                data_view=getattr(args, "data_view", "metrics-*"),
            )
            monitor_validation_records = validate_monitor_queries(
                monitor_irs,
                es_url=args.es_url if getattr(args, "validate", False) else "",
                es_api_key=getattr(args, "es_api_key", "") or "",
            )
            monitor_verification_lookup = build_monitor_verification_lookup(
                monitor_irs,
                monitor_validation_records,
            )
            payload_validation_by_alert_id: dict[str, Any] = {}
            if getattr(args, "kibana_url", ""):
                payload_preflight = run_alerting_preflight(
                    args.kibana_url,
                    api_key=getattr(args, "kibana_api_key", "") or "",
                    space_id=getattr(args, "space_id", "") or "",
                )
                for item in mapping_batch.get("results", []):
                    payload = item.get("mapping", {}).get("rule_payload", {})
                    if not payload:
                        continue
                    payload_validation_by_alert_id[str(item.get("alert_id", "") or "")] = validate_rule_payload(
                        payload.get("rule_type_id", ""),
                        payload.get("params", {}),
                        payload_preflight,
                    )
            monitor_comparison = build_monitor_comparison_results(
                raw_monitors,
                monitor_irs,
                mapping_batch,
                payload_validation_by_alert_id=payload_validation_by_alert_id,
                verification_by_alert_id=monitor_verification_lookup,
            )

            by_tier = mapping_batch["summary"]["by_automation_tier"]
            by_kind: dict[str, int] = {}
            for ir in monitor_irs:
                by_kind[ir.kind] = by_kind.get(ir.kind, 0) + 1

            monitor_results_path = output_dir / "monitor_migration_results.json"
            with monitor_results_path.open("w") as fh:
                _mon_json.dump(build_monitor_migration_results(monitor_irs), fh, indent=2)
            print(f"    Monitor migration results: {monitor_results_path}")

            monitor_comparison_path = output_dir / "monitor_comparison_results.json"
            with monitor_comparison_path.open("w") as fh:
                _mon_json.dump(monitor_comparison, fh, indent=2)
            print(f"    Monitor comparison results: {monitor_comparison_path}")

            monitor_verification_path = output_dir / "monitor_verification_results.json"
            monitor_validation_summary: dict[str, int] = {}
            for record in monitor_validation_records:
                status = str(record.get("status", "not_run") or "not_run")
                monitor_validation_summary[status] = monitor_validation_summary.get(status, 0) + 1
            with monitor_verification_path.open("w") as fh:
                _mon_json.dump(
                    {
                        "total": len(monitor_validation_records),
                        "by_status": monitor_validation_summary,
                        "records": monitor_validation_records,
                        "by_alert_id": monitor_verification_lookup,
                    },
                    fh,
                    indent=2,
                )
            print(f"    Monitor verification results: {monitor_verification_path}")
            print(f"    Total: {len(monitor_irs)}")
            print(f"    By tier: {by_tier}")
            print(f"    By kind: {by_kind}")

            for result in all_results:
                result.alert_results = [ir.to_dict() for ir in monitor_irs]
                result.alert_summary = {
                    "total": len(monitor_irs),
                    "automated": by_tier.get("automated", 0),
                    "draft_review": by_tier.get("draft_requires_review", 0),
                    "manual_required": by_tier.get("manual_required", 0),
                    "by_kind": dict(by_kind),
                }
        else:
            print("    No monitors found")

    print_report(all_results)

    report_path = output_dir / "migration_report.json"
    manifest_path = output_dir / "migration_manifest.json"
    verification_path = output_dir / "verification_packets.json"
    rollout_path = output_dir / "rollout_plan.json"
    save_detailed_report(
        all_results,
        str(report_path),
        validation_summary=validation_summary,
        validation_records=validation_records,
        smoke_payload=smoke_payload,
        verification_payload=verification_payload,
    )
    save_migration_manifest(all_results, manifest_path)
    save_verification_packets(verification_payload, verification_path)
    rollout_plan = build_rollout_plan(
        all_results,
        target_space=args.space_id or "",
        output_dir=str(output_dir),
        smoke_report_path=(args.smoke_output or str(output_dir / "uploaded_dashboard_smoke_report.json")) if args.smoke else "",
    )
    save_rollout_plan(rollout_plan, rollout_path)
    print(f"  Verification packets saved: {verification_path}")
    print(f"  Migration manifest saved: {manifest_path}")
    print(f"  Rollout plan saved: {rollout_path}")
    review_queue = generate_review_queue(rollout_plan)
    if review_queue:
        top_risk = review_queue[:3]
        print("  Review queue (top risk):")
        for item in top_risk:
            gates = item["gates"]
            print(
                f"    {item['dashboard']}: risk={item['risk_score']} "
                f"(G:{gates['green']} Y:{gates['yellow']} R:{gates['red']})"
            )


def _translate_widget(
    widget: NormalizedWidget,
    field_map: Any,
    args: argparse.Namespace,
) -> TranslationResult:
    """Plan and translate a single widget."""
    plan = plan_widget(widget)
    return translate_widget(widget, plan, field_map)


def _extract(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Extract dashboards based on source type."""
    if args.source == "files":
        return extract_dashboards_from_files(args.input_dir)

    if args.source == "api":
        creds = load_credentials_from_env(args.env_file)
        if not creds["api_key"] or not creds["app_key"]:
            print("  ERROR: DD_API_KEY and DD_APP_KEY must be set")
            sys.exit(1)
        dashboard_ids = args.dashboard_ids.split(",") if args.dashboard_ids else None
        return extract_dashboards_from_api(
            api_key=creds["api_key"],
            app_key=creds["app_key"],
            site=creds["site"],
            dashboard_ids=dashboard_ids,
        )

    print(f"  ERROR: unknown source: {args.source}")
    sys.exit(1)


def _load_live_field_capabilities(field_map: Any, args: argparse.Namespace) -> None:
    """Populate live target field capabilities when Elasticsearch access is configured."""
    if not args.es_url:
        print("  Target field capabilities: offline mode (pass --es-url to enable)")
        return
    try:
        counts = field_map.load_live_field_capabilities(args.es_url, es_api_key=args.es_api_key)
    except Exception as exc:
        print(f"  WARNING: target field capability discovery failed: {exc}")
        return
    metric_fields = counts.get("metric_fields", 0)
    log_fields = counts.get("log_fields", 0)
    parts = [f"metrics={metric_fields}"]
    if field_map.logs_index:
        parts.append(f"logs={log_fields}")
    print(f"  Target field capabilities: loaded {' '.join(parts)}")


def _run_dashboard_preflight(
    dashboard: Any,
    field_map: Any,
    args: argparse.Namespace,
) -> PreflightResult | None:
    """Run Datadog preflight when capability data is available or explicitly requested."""
    has_capabilities = bool(
        getattr(field_map, "field_caps", {})
        or getattr(field_map, "metric_field_caps", {})
        or getattr(field_map, "log_field_caps", {})
    )
    if not (args.preflight or has_capabilities):
        return None
    result = run_preflight(dashboard, field_map=field_map)
    if args.preflight and not has_capabilities and not result.issues:
        print("    Preflight: no target field capability data available")
        return None
    return result


def _print_preflight_summary(preflight: PreflightResult) -> None:
    block_count = len(preflight.blocking_issues)
    warn_count = len(preflight.warnings)
    info_count = len([issue for issue in preflight.issues if issue.level == "info"])
    status = "pass" if preflight.passed and not preflight.issues else "issues" if preflight.issues else "pass"
    print(f"    Preflight: {status}  Block: {block_count}  Warn: {warn_count}  Info: {info_count}")
    for issue in preflight.issues[:5]:
        prefix = issue.widget_id + ": " if issue.widget_id else ""
        print(f"      - [{issue.level}] {prefix}{issue.message}")
    if len(preflight.issues) > 5:
        print(f"      ... and {len(preflight.issues) - 5} more")


def _preflight_issue_to_dict(issue: Any) -> dict[str, str]:
    return {
        "level": issue.level,
        "category": issue.category,
        "message": issue.message,
        "widget_id": issue.widget_id,
        "field_name": issue.field_name,
    }


def _compile_all_dashboards(
    results: list[DashboardResult],
    output_dir: Path,
    target_adapter: Any,
) -> None:
    """Compile YAML to NDJSON using the shared Kibana target runtime."""
    compiled_dir = output_dir / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)

    for dr in results:
        if not dr.yaml_path:
            continue
        stem = Path(dr.yaml_path).stem
        out_dir = compiled_dir / stem
        out_dir.mkdir(parents=True, exist_ok=True)

        success, output = target_adapter.compile_dashboard(dr.yaml_path, out_dir)
        if success:
            dr.compiled = True
            dr.compiled_path = str(out_dir)
            print(f"    Compiled: {stem}")
        else:
            dr.compile_error = output[:500]
            print(f"    COMPILE FAILED: {stem}: {output[:200]}")


class _DatadogValidationResolver:
    """Minimal resolver adapter for generic ES|QL validation fixes."""

    def __init__(
        self,
        field_map: Any,
        index_pattern: str,
        *,
        es_url: str = "",
        es_api_key: str = "",
    ) -> None:
        self._field_map = field_map
        self._index_pattern = index_pattern or field_map.metric_index
        self._es_url = es_url
        self._es_api_key = es_api_key
        self._concrete_index_cache: list[str] | None = None

    def _context(self) -> str:
        if self._index_pattern == self._field_map.logs_index or self._index_pattern.startswith("logs-"):
            return "log"
        if self._index_pattern == self._field_map.metric_index or self._index_pattern.startswith("metrics-"):
            return "metric"
        return ""

    def _caps(self) -> dict[str, Any]:
        context = self._context()
        if context == "log":
            return self._field_map.log_field_caps or self._field_map.field_caps
        if context == "metric":
            return self._field_map.metric_field_caps or self._field_map.field_caps
        return self._field_map.field_caps

    def _candidate_fields(self, label: str) -> list[str]:
        candidates: list[str] = []
        context = self._context()
        mapped_tag = self._field_map.map_tag(label, context=context)
        if mapped_tag and mapped_tag != label:
            candidates.append(mapped_tag)
        mapped_log = self._field_map.map_log_field(label)
        if mapped_log and mapped_log not in candidates and mapped_log != label:
            candidates.append(mapped_log)
        mapped_metric = self._field_map.metric_map.get(label, "")
        if mapped_metric and mapped_metric not in candidates and mapped_metric != label:
            candidates.append(mapped_metric)
        return candidates

    def resolve_label(self, label: str) -> str:
        for candidate in self._candidate_fields(label):
            exists = self.field_exists(candidate)
            if exists is True or exists is None:
                return candidate
        return label

    def field_exists(self, field_name: str) -> bool | None:
        caps = self._caps()
        if not caps:
            return None
        return field_name in caps

    def _es_headers(self) -> dict[str, str]:
        headers = {}
        if self._es_api_key:
            headers["Authorization"] = f"ApiKey {self._es_api_key}"
        return headers

    def concrete_index_candidates(self) -> list[str]:
        if self._concrete_index_cache is not None:
            return list(self._concrete_index_cache)
        self._concrete_index_cache = []
        if not self._es_url:
            return []
        if not any(token in self._index_pattern for token in ("*", "?", ",")):
            self._concrete_index_cache = [self._index_pattern]
            return list(self._concrete_index_cache)
        try:
            resp = requests.get(
                f"{self._es_url}/_resolve/index/{self._index_pattern}",
                headers=self._es_headers(),
                timeout=10,
            )
            if resp.status_code != 200:
                return []
            body = resp.json()
            discovered: list[str] = []
            for bucket in ("data_streams", "indices"):
                for entry in body.get(bucket, []) or []:
                    name = entry.get("name")
                    if name and name not in discovered:
                        discovered.append(name)
            self._concrete_index_cache = discovered
        except Exception:
            pass
        return list(self._concrete_index_cache)


def _mark_widget_requires_manual_after_validation(
    result: TranslationResult,
    validation_result: dict[str, Any],
) -> None:
    result.status = "requires_manual"
    result.post_validation_action = "placeholder_empty_result"
    _append_unique(
        result.reasons,
        "Validation only succeeded on an empty fallback data stream",
    )
    _append_unique(
        result.warnings,
        "Validation only succeeded on an empty fallback data stream",
    )
    narrowed_to = (validation_result.get("analysis") or {}).get("narrowed_to_index", "")
    if narrowed_to:
        _append_unique(
            result.warnings,
            f"Fallback validation target `{narrowed_to}` returned zero rows; manual review required.",
        )
        result.post_validation_message = (
            f"Validation only succeeded on empty fallback stream `{narrowed_to}`; manual review required."
        )
    elif not result.post_validation_message:
        result.post_validation_message = "Validation only succeeded on an empty fallback stream; manual review required."
    if "empty fallback data stream during validation" not in result.semantic_losses:
        result.semantic_losses.append("empty fallback data stream during validation")


def _mark_widget_requires_manual_after_failed_validation(
    result: TranslationResult,
    validation_result: dict[str, Any],
) -> None:
    result.status = "requires_manual"
    result.post_validation_action = "placeholder_validation_failed"
    _append_unique(
        result.reasons,
        "Live ES|QL validation failed; uploaded placeholder instead of a broken runtime panel",
    )
    _append_unique(
        result.warnings,
        "Live ES|QL validation failed; uploaded placeholder instead of a broken runtime panel",
    )
    error = ((validation_result or {}).get("error") or "").splitlines()[0].strip()
    if error:
        _append_unique(result.warnings, f"Validation error: {error}")
        result.post_validation_message = f"Validation failed: {error}"
    elif not result.post_validation_message:
        result.post_validation_message = "Live ES|QL validation failed; manual review required."
    if "validation failure placeholder" not in result.semantic_losses:
        result.semantic_losses.append("validation failure placeholder")


def _rewrite_dashboard_yaml(
    dashboard: Any,
    result: DashboardResult,
    field_map: Any,
) -> None:
    if not result.yaml_path:
        return
    yaml_str = generate_dashboard_yaml(
        dashboard,
        result.panel_results,
        data_view=field_map.metric_index,
        metrics_dataset_filter=field_map.metrics_dataset_filter,
        logs_dataset_filter=field_map.logs_dataset_filter,
        logs_index=field_map.logs_index,
        field_map=field_map,
    )
    Path(result.yaml_path).write_text(yaml_str, encoding="utf-8")


def _validate_all_dashboards(
    dashboard_outputs: list[tuple[DashboardResult, Any]],
    field_map: Any,
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate emitted Datadog ES|QL queries against Elasticsearch."""
    print("\n  Validating ES|QL queries against Elasticsearch...")
    validation_records: list[dict[str, Any]] = []
    total_queries = 0
    passed = 0
    fixed = 0
    fixed_empty = 0
    failed = 0
    skipped = 0

    for result, dashboard in dashboard_outputs:
        per_dashboard_counts: dict[str, int] = {}
        dashboard_changed = False
        for panel_result in result.panel_results:
            if not panel_result.esql_query:
                continue
            total_queries += 1
            _source_cmd, index_pattern = _query_source_and_index(panel_result.esql_query)
            resolver = _DatadogValidationResolver(
                field_map,
                index_pattern or field_map.metric_index,
                es_url=args.es_url,
                es_api_key=args.es_api_key or "",
            )
            validation_result = validate_query_with_fixes(
                panel_result.esql_query,
                args.es_url,
                resolver,
                es_api_key=args.es_api_key or None,
            )
            status = validation_result["status"]
            per_dashboard_counts[status] = per_dashboard_counts.get(status, 0) + 1
            if status == "pass":
                passed += 1
            elif status == "fixed":
                fixed += 1
                panel_result.esql_query = validation_result["query"]
                dashboard_changed = True
            elif status == "fixed_empty":
                fixed_empty += 1
                panel_result.esql_query = validation_result["query"]
                _mark_widget_requires_manual_after_validation(panel_result, validation_result)
                dashboard_changed = True
            elif status == "fail":
                failed += 1
                _mark_widget_requires_manual_after_failed_validation(panel_result, validation_result)
                dashboard_changed = True
            elif status == "skip":
                skipped += 1

            validation_records.append(
                {
                    "dashboard": result.dashboard_title,
                    "dashboard_id": result.dashboard_id,
                    "widget": panel_result.title,
                    "widget_id": panel_result.widget_id,
                    "status": status,
                    "query": validation_result["query"],
                    "error": validation_result["error"],
                    "fix_attempts": validation_result["fix_attempts"],
                    "analysis": validation_result["analysis"],
                }
            )
        result.validation_summary = per_dashboard_counts
        result.recompute_counts()
        if dashboard_changed:
            _rewrite_dashboard_yaml(dashboard, result, field_map)

    validation_summary = summarize_validation_records(validation_records)
    print(
        f"  Validated {total_queries} queries: "
        f"{passed} passed, {fixed} auto-fixed, {fixed_empty} manualized after empty fallback, "
        f"{failed} failed, {skipped} skipped"
    )
    if validation_summary.get("missing_labels"):
        top_labels = list(validation_summary["missing_labels"].items())[:5]
        print("  Top missing labels: " + ", ".join(f"{name} ({count})" for name, count in top_labels))
    if validation_summary.get("missing_metrics"):
        top_metrics = list(validation_summary["missing_metrics"].items())[:5]
        print("  Top missing metrics: " + ", ".join(f"{name} ({count})" for name, count in top_metrics))
    if validation_summary.get("counter_type_mismatches"):
        top_counters = list(validation_summary["counter_type_mismatches"].items())[:5]
        print("  Residual counter type mismatches: " + ", ".join(f"{name} ({count})" for name, count in top_counters))
    if validation_summary.get("empty_fallback_indexes"):
        top_fallbacks = list(validation_summary["empty_fallback_indexes"].items())[:5]
        print("  Empty fallback streams: " + ", ".join(f"{name} ({count})" for name, count in top_fallbacks))
    return validation_records, validation_summary


def _handle_list_dashboards(args: argparse.Namespace, target_adapter: Any) -> None:
    if not args.kibana_url:
        print("  ERROR: --kibana-url is required for --list-dashboards")
        sys.exit(2)
    dashboards = target_adapter.list_dashboards(
        args.kibana_url,
        api_key=args.kibana_api_key,
        space_id=args.space_id,
    )
    print(f"\n  Found {len(dashboards)} dashboard(s) in Kibana:\n")
    for d in dashboards:
        title = d.get("attributes", {}).get("title", "(untitled)")
        print(f"    {d.get('id', '???'):40s}  {title}")


def _handle_delete_dashboards(args: argparse.Namespace, target_adapter: Any) -> None:
    if not args.kibana_url:
        print("  ERROR: --kibana-url is required for --delete-dashboards")
        sys.exit(2)
    ids = [i.strip() for i in args.delete_dashboards.split(",") if i.strip()]
    if not ids:
        print("  ERROR: provide comma-separated dashboard IDs")
        sys.exit(2)
    result = target_adapter.delete_dashboards(
        args.kibana_url,
        ids,
        api_key=args.kibana_api_key,
        space_id=args.space_id,
    )
    print(f"\n  Cleared {len(result['cleared'])} dashboard(s)")
    if result["failed"]:
        for f in result["failed"]:
            print(f"    FAILED: {f['id']}: {f['error'][:200]}")
    print(f"\n  Note: {result['note']}")


def _ensure_data_views(args: argparse.Namespace, target_adapter: Any, field_map: Any) -> None:
    patterns: list[str] = []
    if field_map.metric_index:
        patterns.append(field_map.metric_index)
    if field_map.logs_index:
        patterns.append(field_map.logs_index)
    if not patterns:
        patterns = ["metrics-*"]
    print(f"\n  Ensuring data views: {', '.join(patterns)}")
    try:
        created = target_adapter.ensure_data_views(
            args.kibana_url,
            data_view_patterns=patterns,
            api_key=args.kibana_api_key,
            space_id=args.space_id,
        )
        for dv in created:
            print(f"    OK: {dv.get('title', '???')} (id={dv.get('id', '???')})")
    except Exception as exc:
        print(f"    WARNING: data view creation failed: {exc}")


def _upload_all_dashboards(
    results: list[DashboardResult],
    output_dir: Path,
    args: argparse.Namespace,
    target_adapter: Any,
) -> None:
    """Upload compiled dashboards to Kibana via the shared target runtime."""
    from observability_migration.targets.kibana.compile import (
        detect_space_id_from_kibana_url,
        kibana_url_for_space,
    )

    compiled_dir = output_dir / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)
    target_space = detect_space_id_from_kibana_url(args.kibana_url) or "default"
    upload_space = args.space_id or ""
    upload_kibana_url = kibana_url_for_space(args.kibana_url, upload_space)

    print(f"\n  Uploading dashboards to {upload_kibana_url}")
    for dr in results:
        dr.upload_attempted = True
        stem = Path(dr.yaml_path).stem if dr.yaml_path else (dr.dashboard_title or dr.dashboard_id or "untitled")

        if not dr.yaml_path:
            dr.uploaded = False
            dr.upload_error = "Upload skipped because no YAML artifact was generated."
            print(f"    UPLOAD SKIPPED: {stem}: {dr.upload_error}")
            continue
        if not dr.compiled:
            dr.uploaded = False
            dr.upload_error = (
                "Upload skipped because compile failed."
                if dr.compile_error
                else "Upload skipped because compile did not run."
            )
            print(f"    UPLOAD SKIPPED: {stem}: {dr.upload_error}")
            continue

        out_dir = compiled_dir / Path(dr.yaml_path).stem
        out_dir.mkdir(parents=True, exist_ok=True)
        upload_result = target_adapter.upload_dashboard(
            dr.yaml_path,
            out_dir,
            kibana_url=args.kibana_url,
            space_id=upload_space,
            kibana_api_key=args.kibana_api_key,
        )
        dr.uploaded = upload_result["success"]
        dr.upload_error = "" if upload_result["success"] else upload_result["output"][:500]
        dr.uploaded_space = upload_space or target_space
        dr.uploaded_kibana_url = upload_result["kibana_url"]
        if upload_result["success"]:
            print(f"    Uploaded: {stem}")
        else:
            print(f"    UPLOAD FAILED: {stem}: {dr.upload_error[:200]}")


def _build_smoke_dashboard_indexes(
    smoke_payload: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_title: dict[str, dict[str, Any]] = {}
    for dashboard in smoke_payload.get("dashboards", []):
        dashboard_id = str(dashboard.get("id", "") or "")
        dashboard_title = str(dashboard.get("title", "") or "")
        if dashboard_id and dashboard_id not in by_id:
            by_id[dashboard_id] = dashboard
        if dashboard_title and dashboard_title not in by_title:
            by_title[dashboard_title] = dashboard
    return by_id, by_title


def _apply_smoke_dashboard_state(
    result: DashboardResult,
    smoke_dashboard: dict[str, Any] | None,
    *,
    output_path: Path,
    browser_requested: bool,
) -> None:
    result.smoke_attempted = True
    result.smoke_report_path = str(output_path)
    result.browser_audit_attempted = browser_requested
    if not smoke_dashboard:
        result.smoke_status = "not_run"
        result.smoke_error = "Uploaded dashboard was not found in the smoke report."
        if browser_requested:
            result.browser_audit_status = "not_run"
            result.browser_audit_error = ""
        return

    result.kibana_saved_object_id = str(smoke_dashboard.get("id", "") or "")
    layout = smoke_dashboard.get("layout", {}) or {}
    overlaps = layout.get("overlaps", []) or []
    invalid_sizes = layout.get("invalid_sizes", []) or []
    out_of_bounds = layout.get("out_of_bounds", []) or []
    result.layout_checked = True
    if overlaps or invalid_sizes or out_of_bounds:
        result.layout_error = (
            f"{len(overlaps)} overlap(s), {len(invalid_sizes)} invalid size(s), "
            f"{len(out_of_bounds)} out-of-bounds panel(s)"
        )
    else:
        result.layout_error = ""

    status = str(smoke_dashboard.get("status", "") or "")
    if status == "clean":
        result.smoke_status = "pass"
        result.smoke_error = ""
    elif status in {"has_runtime_errors", "has_layout_issues"}:
        result.smoke_status = "fail"
        if status == "has_runtime_errors":
            result.smoke_error = f"{len(smoke_dashboard.get('failing_panels', []) or [])} panel runtime error(s)"
        else:
            result.smoke_error = result.layout_error or "Uploaded dashboard has layout issues."
    elif status == "has_empty_panels":
        result.smoke_status = "empty_result"
        result.smoke_error = f"{len(smoke_dashboard.get('empty_panels', []) or [])} empty panel(s)"
    elif status == "has_runtime_gaps":
        result.smoke_status = "not_runtime_checked"
        result.smoke_error = (
            f"{len(smoke_dashboard.get('not_runtime_checked_panels', []) or [])} panel(s) not runtime-checked"
        )
    else:
        result.smoke_status = "not_run"
        result.smoke_error = ""

    browser_info = smoke_dashboard.get("browser_audit", {}) or {}
    browser_status = str(browser_info.get("status", "") or "not_requested")
    if browser_requested:
        if browser_status == "clean":
            result.browser_audit_status = "pass"
            result.browser_audit_error = ""
        elif browser_status in {"error", "failed"}:
            result.browser_audit_status = "fail"
            result.browser_audit_error = "; ".join(browser_info.get("issues", []) or []) or str(browser_info.get("error", "") or "")
        else:
            result.browser_audit_status = "not_run"
            result.browser_audit_error = str(browser_info.get("error", "") or "")


def _smoke_uploaded_dashboards(
    results: list[DashboardResult],
    output_dir: Path,
    args: argparse.Namespace,
    target_adapter: Any,
) -> dict[str, Any]:
    uploaded_results = [result for result in results if result.uploaded]
    if not uploaded_results:
        print("\n  Smoke validation skipped: no dashboards uploaded successfully")
        return {}

    smoke_output = Path(args.smoke_output) if args.smoke_output else output_dir / "uploaded_dashboard_smoke_report.json"
    dashboard_titles = [result.dashboard_title for result in uploaded_results if result.dashboard_title]

    print(f"\n  Smoke validating uploaded dashboards ({len(uploaded_results)})...")
    try:
        smoke_payload = target_adapter.smoke(
            kibana_url=args.kibana_url,
            es_url=args.es_url,
            kibana_api_key=args.kibana_api_key,
            es_api_key=args.es_api_key,
            space_id=args.space_id,
            output_path=smoke_output,
            screenshot_dir=str(output_dir / "dashboard_qa"),
            browser_audit_dir=str(output_dir / "browser_qa"),
            dashboard_titles=dashboard_titles,
            timeout=args.smoke_timeout,
            browser_audit=args.browser_audit,
            capture_screenshots=args.capture_screenshots,
            chrome_binary=args.chrome_binary,
        )
    except Exception as exc:
        message = str(exc)
        print(f"    SMOKE FAILED: {message}")
        for result in uploaded_results:
            result.smoke_attempted = True
            result.smoke_status = "fail"
            result.smoke_error = message
            result.smoke_report_path = str(smoke_output)
            result.browser_audit_attempted = args.browser_audit
            for panel_result in result.panel_results:
                _append_unique(panel_result.runtime_rollups, "smoke_failed")
            if args.browser_audit:
                result.browser_audit_status = "fail"
                result.browser_audit_error = message
                for panel_result in result.panel_results:
                    _append_unique(panel_result.runtime_rollups, "browser_failed")
        return {}

    merge_summary = merge_smoke_into_results(uploaded_results, smoke_payload)
    smoke_by_id, smoke_by_title = _build_smoke_dashboard_indexes(smoke_payload)
    for result in uploaded_results:
        smoke_dashboard = None
        if result.kibana_saved_object_id:
            smoke_dashboard = smoke_by_id.get(result.kibana_saved_object_id)
        if smoke_dashboard is None:
            smoke_dashboard = smoke_by_title.get(result.dashboard_title)
        if smoke_dashboard is None:
            for panel_result in result.panel_results:
                _append_unique(panel_result.runtime_rollups, "not_runtime_checked")
        _apply_smoke_dashboard_state(
            result,
            smoke_dashboard,
            output_path=smoke_output,
            browser_requested=args.browser_audit,
        )

    summary = smoke_payload.get("summary", {}) or {}
    print(
        "    Smoke summary: "
        f"{summary.get('runtime_error_panels', 0)} runtime error panel(s), "
        f"{summary.get('empty_panels', 0)} empty panel(s), "
        f"{summary.get('not_runtime_checked_panels', 0)} not runtime-checked panel(s), "
        f"{summary.get('dashboards_with_layout_issues', 0)} dashboard(s) with layout issues"
    )
    if args.browser_audit:
        print(
            "    Browser audit: "
            f"{summary.get('dashboards_with_browser_errors', 0)} dashboard(s) with visible errors"
        )
    if merge_summary.get("merged"):
        print(
            "    Smoke merge: "
            f"{merge_summary.get('smoke_failed', 0)} smoke_failed, "
            f"{merge_summary.get('browser_failed', 0)} browser_failed, "
            f"{merge_summary.get('empty_result', 0)} empty_result, "
            f"{merge_summary.get('not_runtime_checked', 0)} not_runtime_checked"
        )
    return smoke_payload


def _safe_filename(title: str) -> str:
    """Convert a dashboard title to a safe filename."""
    import re
    name = re.sub(r"[^\w\s-]", "", title).strip().lower()
    name = re.sub(r"[\s]+", "_", name)
    return name[:80] or "untitled"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate Datadog dashboards to Kibana",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--source", choices=["files", "api"], default="files",
        help="Dashboard source: 'files' (JSON exports) or 'api' (Datadog API)",
    )
    parser.add_argument(
        "--input-dir", default="infra/datadog/dashboards",
        help="Directory with exported Datadog dashboard JSON files",
    )
    parser.add_argument(
        "--output-dir", default="datadog_migration_output",
        help="Output directory for generated YAML and reports",
    )
    parser.add_argument(
        "--field-profile", default="otel",
        help="Field mapping profile: otel, elastic_agent, prometheus, passthrough, or path to YAML",
    )
    parser.add_argument(
        "--data-view", default="metrics-*",
        help="Elasticsearch index pattern for metrics data",
    )
    parser.add_argument(
        "--logs-index", default="",
        help="Elasticsearch index pattern for logs (defaults from profile)",
    )
    parser.add_argument(
        "--es-url",
        default=os.getenv("ELASTICSEARCH_ENDPOINT", os.getenv("ES_URL", "")),
        help="Elasticsearch URL for live target field discovery",
    )
    parser.add_argument(
        "--es-api-key",
        default=os.getenv("ES_API_KEY", os.getenv("KEY", "")),
        help="API key for Elasticsearch (defaults to ES_API_KEY or KEY env var)",
    )
    parser.add_argument(
        "--env-file", default="datadog_creds.env",
        help="Path to Datadog credentials .env file",
    )
    parser.add_argument(
        "--dashboard-ids", default="",
        help="Comma-separated Datadog dashboard IDs to fetch (API mode)",
    )
    parser.add_argument(
        "--compile", action="store_true",
        help="Compile YAML to NDJSON using kb-dashboard-cli",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Validate emitted ES|QL against Elasticsearch before compile/upload",
    )
    parser.add_argument(
        "--upload", action="store_true",
        help="Upload dashboards to Kibana after a successful compile pass",
    )
    parser.add_argument(
        "--smoke", action="store_true",
        help="Run post-upload smoke validation against the uploaded Kibana dashboards",
    )
    parser.add_argument(
        "--preflight", action="store_true",
        help="Run Datadog preflight checks before translation",
    )
    parser.add_argument(
        "--dataset-filter", default="",
        help="Explicit data_stream.dataset value for metrics dashboard filter "
             "(auto-derived from --data-view when possible)",
    )
    parser.add_argument(
        "--logs-dataset-filter", default="",
        help="Explicit data_stream.dataset value for logs dashboard filter "
             "(auto-derived from --logs-index when possible)",
    )
    parser.add_argument(
        "--kibana-url",
        default=os.getenv("KIBANA_ENDPOINT", os.getenv("KIBANA_URL", "")),
        help="Kibana URL for upload",
    )
    parser.add_argument(
        "--kibana-api-key",
        default=os.getenv("KIBANA_API_KEY", os.getenv("KEY", "")),
        help="API key for Kibana upload (defaults to KIBANA_API_KEY or KEY env var)",
    )
    parser.add_argument(
        "--space-id", default="",
        help="Optional Kibana space ID for upload",
    )
    parser.add_argument(
        "--smoke-output", default="",
        help="Optional path for the post-upload smoke report JSON",
    )
    parser.add_argument(
        "--smoke-timeout", type=int, default=30,
        help="Timeout in seconds for Kibana/Elasticsearch smoke requests",
    )
    parser.add_argument(
        "--browser-audit", action="store_true",
        help="During smoke validation, scan uploaded dashboards for visible browser-side runtime errors",
    )
    parser.add_argument(
        "--capture-screenshots", action="store_true",
        help="During smoke validation, capture dashboard screenshots",
    )
    parser.add_argument(
        "--chrome-binary", default=os.getenv("CHROME_BINARY", ""),
        help="Optional Chrome/Chromium binary path for browser audit or screenshots",
    )
    parser.add_argument(
        "--ensure-data-views", action="store_true",
        help="Auto-create required data views in the target Kibana cluster before upload",
    )
    parser.add_argument(
        "--list-dashboards", action="store_true",
        help="List dashboards currently in the target Kibana cluster and exit",
    )
    parser.add_argument(
        "--delete-dashboards", default="",
        help="Comma-separated dashboard IDs to delete (overwrite with empty) from Kibana and exit",
    )
    parser.add_argument(
        "--fetch-monitors", action="store_true",
        help="Extract Datadog monitors and produce alert migration artifacts",
    )
    parser.add_argument(
        "--monitor-ids", default="",
        help="Comma-separated Datadog monitor IDs to extract",
    )
    parser.add_argument(
        "--monitor-query", default="",
        help="Datadog monitor search query for filtered discovery",
    )

    return parser.parse_args(argv)


if __name__ == "__main__":
    main()
