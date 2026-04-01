import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from observability_migration.adapters.source.grafana import cli as grafana_cli
from observability_migration.core.reporting.report import MigrationResult, PanelResult


class GrafanaCliSmokeParityTests(unittest.TestCase):
    def test_parse_args_accepts_integrated_smoke_options(self):
        args = grafana_cli.parse_args(
            [
                "--smoke",
                "--browser-audit",
                "--capture-screenshots",
                "--smoke-output",
                "smoke.json",
                "--smoke-timeout",
                "45",
                "--time-from",
                "now-24h",
                "--time-to",
                "now-5m",
                "--chrome-binary",
                "/usr/bin/chrome",
            ]
        )

        self.assertTrue(args.smoke)
        self.assertTrue(args.browser_audit)
        self.assertTrue(args.capture_screenshots)
        self.assertEqual(args.smoke_output, "smoke.json")
        self.assertEqual(args.smoke_timeout, 45)
        self.assertEqual(args.time_from, "now-24h")
        self.assertEqual(args.time_to, "now-5m")
        self.assertEqual(args.chrome_binary, "/usr/bin/chrome")

    def test_normalize_execution_flags_auto_enables_upload_for_smoke(self):
        args = SimpleNamespace(
            preflight=False,
            upload=False,
            validate=False,
            smoke=True,
            browser_audit=False,
            capture_screenshots=False,
            smoke_report="",
            smoke_output="",
            es_url="https://example.es",
            kibana_url="https://kibana.example",
        )

        auto_enabled_upload, auto_enabled_validate = grafana_cli._normalize_execution_flags(args)

        self.assertTrue(auto_enabled_upload)
        self.assertTrue(auto_enabled_validate)
        self.assertTrue(args.upload)
        self.assertTrue(args.validate)

    def test_normalize_execution_flags_rejects_browser_audit_without_smoke(self):
        args = SimpleNamespace(
            preflight=False,
            upload=False,
            validate=False,
            smoke=False,
            browser_audit=True,
            capture_screenshots=False,
            smoke_report="",
            smoke_output="",
            es_url="https://example.es",
            kibana_url="https://kibana.example",
        )

        with self.assertRaises(SystemExit) as ctx:
            grafana_cli._normalize_execution_flags(args)

        self.assertEqual(ctx.exception.code, 2)

    def test_smoke_uploaded_dashboards_calls_kibana_smoke_with_output_artifacts(self):
        result = MigrationResult(
            dashboard_title="Dash",
            dashboard_uid="uid-1",
            uploaded=True,
            panel_results=[
                PanelResult(
                    title="CPU",
                    grafana_type="graph",
                    kibana_type="xy",
                    status="migrated",
                    confidence=1.0,
                )
            ],
        )
        smoke_payload = {
            "summary": {
                "runtime_error_panels": 0,
                "empty_panels": 0,
                "not_runtime_checked_panels": 0,
                "dashboards_with_layout_issues": 0,
                "dashboards_with_browser_errors": 0,
            },
            "dashboards": [
                {
                    "id": "kibana-1",
                    "title": "Dash",
                    "status": "pass",
                    "failing_panels": [],
                    "empty_panels": [],
                    "not_runtime_checked_panels": [],
                    "layout": {"overlaps": [], "invalid_sizes": [], "out_of_bounds": []},
                    "browser_audit": {"status": "clean", "issues": []},
                    "panels": [{"panel": "CPU", "status": "pass"}],
                }
            ],
        }
        args = SimpleNamespace(
            kibana_url="https://kibana.example",
            kibana_api_key="secret-kb",
            es_url="https://example.es",
            es_api_key="secret-es",
            shadow_space="shadow",
            smoke_output="",
            smoke_timeout=45,
            time_from="now-24h",
            time_to="now-5m",
            browser_audit=True,
            capture_screenshots=True,
            chrome_binary="/usr/bin/chrome",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(grafana_cli, "run_smoke_report", return_value=smoke_payload) as mock_smoke:
                with mock.patch.object(
                    grafana_cli,
                    "merge_smoke_into_results",
                    return_value={"merged": 1, "smoke_failed": 0, "browser_failed": 0, "empty_result": 0, "not_runtime_checked": 0},
                ) as mock_merge:
                    state = grafana_cli._smoke_uploaded_dashboards([result], Path(tmpdir), args)

        self.assertEqual(
            state["output_path"],
            str(Path(tmpdir) / "uploaded_dashboard_smoke_report.json"),
        )
        smoke_kwargs = mock_smoke.call_args.kwargs
        self.assertEqual(smoke_kwargs["space_id"], "shadow")
        self.assertEqual(smoke_kwargs["dashboard_titles"], ["Dash"])
        self.assertEqual(
            smoke_kwargs["browser_audit_dir"],
            str(Path(tmpdir) / "browser_qa"),
        )
        self.assertEqual(
            smoke_kwargs["screenshot_dir"],
            str(Path(tmpdir) / "dashboard_qa"),
        )
        self.assertEqual(smoke_kwargs["timeout"], 45)
        self.assertEqual(smoke_kwargs["time_from"], "now-24h")
        self.assertEqual(smoke_kwargs["time_to"], "now-5m")
        self.assertTrue(smoke_kwargs["browser_audit"])
        self.assertTrue(smoke_kwargs["capture_screenshots"])
        self.assertEqual(smoke_kwargs["chrome_binary"], "/usr/bin/chrome")
        mock_merge.assert_called_once_with([result], smoke_payload)


if __name__ == "__main__":
    unittest.main()
