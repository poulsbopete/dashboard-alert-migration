import argparse
import json
import subprocess
import tempfile
import unittest
from unittest import mock

import pathlib

from observability_migration.adapters.source.grafana import smoke


class _FakeResponse:
    def __init__(self, payload, status_code=200, content_type="application/json", text=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.text = text if text is not None else (payload if isinstance(payload, str) else json.dumps(payload))

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class UploadedDashboardSmokeTests(unittest.TestCase):
    def test_build_dashboard_url_default_space(self):
        url = smoke.build_dashboard_url(
            "http://localhost:5601",
            "",
            "dashboard-123",
            time_from="now-1h",
            time_to="now",
        )
        self.assertEqual(
            url,
            "http://localhost:5601/app/dashboards#/view/dashboard-123?embed=true&_g=(time:(from:now-1h,to:now))",
        )

    def test_build_dashboard_url_with_space(self):
        url = smoke.build_dashboard_url(
            "http://localhost:5601",
            "observability",
            "dashboard-123",
            time_from="2026-03-24T00:00:00Z",
            time_to="2026-03-24T01:00:00Z",
        )
        self.assertEqual(
            url,
            "http://localhost:5601/s/observability/app/dashboards#/view/dashboard-123?embed=true&_g=(time:(from:2026-03-24T00:00:00Z,to:2026-03-24T01:00:00Z))",
        )

    def test_analyze_layout_detects_overlap(self):
        issues = smoke.analyze_layout(
            [
                {"panelIndex": "left", "gridData": {"x": 0, "y": 0, "w": 6, "h": 4}},
                {"panelIndex": "right", "gridData": {"x": 4, "y": 2, "w": 6, "h": 4}},
            ]
        )
        self.assertEqual(len(issues["overlaps"]), 1)
        self.assertEqual(issues["overlaps"][0]["left_panel"], "left")
        self.assertEqual(issues["overlaps"][0]["right_panel"], "right")

    def test_analyze_layout_ignores_overlaps_across_sections(self):
        issues = smoke.analyze_layout(
            [
                {"panelIndex": "left", "gridData": {"x": 0, "y": 0, "w": 6, "h": 4, "sectionId": "a"}},
                {"panelIndex": "right", "gridData": {"x": 0, "y": 0, "w": 6, "h": 4, "sectionId": "b"}},
            ]
        )

        self.assertEqual(issues["overlaps"], [])

    def test_load_dashboards_paginates_saved_objects(self):
        session = mock.Mock()
        session.get.side_effect = [
            _FakeResponse(
                {
                    "saved_objects": [{"id": "dashboard-1", "attributes": {"title": "First"}}],
                    "total": 2,
                }
            ),
            _FakeResponse(
                {
                    "saved_objects": [{"id": "dashboard-2", "attributes": {"title": "Second"}}],
                    "total": 2,
                }
            ),
        ]

        dashboards = smoke.load_dashboards(session, "http://localhost:5601", "", timeout=30, per_page=1)

        self.assertEqual([item["id"] for item in dashboards], ["dashboard-1", "dashboard-2"])
        first_call = session.get.call_args_list[0]
        second_call = session.get.call_args_list[1]
        self.assertEqual(first_call.kwargs["params"]["page"], 1)
        self.assertEqual(second_call.kwargs["params"]["page"], 2)

    def test_load_dashboards_falls_back_to_export_when_find_unavailable(self):
        session = mock.Mock()
        session.get.return_value = _FakeResponse(
            {
                "statusCode": 400,
                "error": "Bad Request",
                "message": "uri [/api/saved_objects/_find] with method [get] exists but is not available with the current configuration",
            },
            status_code=400,
        )
        session.post.return_value = _FakeResponse(
            {},
            text="\n".join(
                [
                    json.dumps({"type": "dashboard", "id": "dashboard-2", "attributes": {"title": "Second"}}),
                    json.dumps({"type": "dashboard", "id": "dashboard-1", "attributes": {"title": "First"}}),
                ]
            ),
        )

        dashboards = smoke.load_dashboards(session, "http://localhost:5601", "", timeout=30, per_page=1000)

        self.assertEqual([item["id"] for item in dashboards], ["dashboard-1", "dashboard-2"])
        session.post.assert_called_once()

    def test_validate_esql_materializes_dashboard_time_placeholders(self):
        captured = {}

        def fake_post(url, params, json, headers, timeout):
            captured["url"] = url
            captured["query"] = json["query"]
            captured["headers"] = headers
            return _FakeResponse(
                {
                    "columns": [{"name": "value"}],
                    "values": [[1]],
                }
            )

        with mock.patch.object(smoke.requests, "post", side_effect=fake_post):
            result = smoke.validate_esql(
                "http://localhost:9200",
                "FROM metrics-*\n| WHERE @timestamp >= ?_tstart AND @timestamp < ?_tend",
                timeout=30,
            )

        self.assertEqual(result["status"], "pass")
        self.assertIn("NOW() - 1 hour", captured["query"])
        self.assertIn("NOW()", captured["query"])
        self.assertEqual(result["materialized_query"], captured["query"])
        self.assertIsNone(captured["headers"])

    def test_validate_esql_sends_api_key_header(self):
        captured = {}

        def fake_post(url, params, json, headers, timeout):
            captured["headers"] = headers
            return _FakeResponse(
                {
                    "columns": [{"name": "value"}],
                    "values": [[1]],
                }
            )

        with mock.patch.object(smoke.requests, "post", side_effect=fake_post):
            result = smoke.validate_esql("http://localhost:9200", "FROM metrics-* | LIMIT 1", timeout=30, es_api_key="abc123")

        self.assertEqual(result["status"], "pass")
        self.assertEqual(captured["headers"], {"Authorization": "ApiKey abc123"})

    def test_extract_panel_queries_reads_recursive_query_locations(self):
        panel = {
            "type": "lens",
            "embeddableConfig": {
                "attributes": {
                    "state": {
                        "datasourceStates": {
                            "formBased": {
                                "layers": {
                                    "layer-1": {
                                        "query": {
                                            "esql": "FROM metrics-* | LIMIT 5",
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }

        self.assertEqual(smoke.extract_panel_queries(panel), ["FROM metrics-* | LIMIT 5"])

    def test_inspect_dashboard_distinguishes_non_query_panels_from_runtime_gaps(self):
        saved_object = {
            "id": "dashboard-123",
            "attributes": {
                "title": "Dashboard",
                "panelsJSON": json.dumps(
                    [
                        {
                            "panelIndex": "controls",
                            "type": "control_group",
                            "embeddableConfig": {"attributes": {"title": "Controls"}},
                            "gridData": {"x": 0, "y": 0, "w": 48, "h": 3},
                        },
                        {
                            "panelIndex": "lens-1",
                            "type": "lens",
                            "embeddableConfig": {"attributes": {"title": "Broken Lens", "visualizationType": "lnsXY"}},
                            "gridData": {"x": 0, "y": 3, "w": 24, "h": 8},
                        },
                    ]
                ),
            },
        }

        result = smoke.inspect_dashboard(saved_object, "http://localhost:9200", timeout=30)

        self.assertEqual(len(result["non_query_panels"]), 1)
        self.assertEqual(len(result["not_runtime_checked_panels"]), 1)
        self.assertEqual(result["status"], "has_runtime_gaps")
        self.assertEqual(result["panels"][0]["status"], "no_query_expected")
        self.assertEqual(result["panels"][1]["status"], "not_runtime_checked")

    def test_inspect_dashboard_treats_markdown_visualizations_as_non_query(self):
        saved_object = {
            "id": "dashboard-123",
            "attributes": {
                "title": "Dashboard",
                "panelsJSON": json.dumps(
                    [
                        {
                            "panelIndex": "markdown-vis",
                            "type": "visualization",
                            "embeddableConfig": {
                                "savedVis": {
                                    "type": "markdown",
                                    "title": "Placeholder",
                                    "params": {"markdown": "Manual review required."},
                                }
                            },
                            "gridData": {"x": 0, "y": 0, "w": 24, "h": 8},
                        }
                    ]
                ),
            },
        }

        result = smoke.inspect_dashboard(saved_object, "http://localhost:9200", timeout=30)

        self.assertEqual(len(result["non_query_panels"]), 1)
        self.assertEqual(len(result["not_runtime_checked_panels"]), 0)
        self.assertEqual(result["status"], "clean")
        self.assertEqual(result["panels"][0]["status"], "no_query_expected")

    def test_inspect_dashboard_records_materialized_query(self):
        saved_object = {
            "id": "dashboard-123",
            "attributes": {
                "title": "Dashboard",
                "panelsJSON": json.dumps(
                    [
                        {
                            "panelIndex": "lens-1",
                            "type": "lens",
                            "embeddableConfig": {
                                "attributes": {
                                    "title": "CPU Busy",
                                    "state": {
                                        "query": {
                                            "esql": "FROM metrics-*\n| WHERE @timestamp >= ?_tstart AND @timestamp < ?_tend"
                                        }
                                    },
                                }
                            },
                            "gridData": {"x": 0, "y": 0, "w": 24, "h": 8},
                        }
                    ]
                ),
            },
        }

        with mock.patch.object(
            smoke,
            "validate_esql",
            return_value={
                "status": "pass",
                "rows": 12,
                "columns": ["value"],
                "error": "",
                "materialized_query": "FROM metrics-*\n| WHERE @timestamp >= NOW() - 1 hour AND @timestamp < NOW()",
            },
        ):
            result = smoke.inspect_dashboard(saved_object, "http://localhost:9200", timeout=30)

        panel_result = result["panels"][0]
        self.assertEqual(panel_result["status"], "pass")
        self.assertIn("NOW() - 1 hour", panel_result["materialized_query"])

    def test_capture_browser_audit_detects_dom_errors(self):
        saved_object = {
            "id": "dashboard-123",
            "attributes": {"title": "Node Exporter Full"},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                kibana_url="http://localhost:5601",
                space_id="",
                output="uploaded_dashboard_smoke_report.json",
                screenshot_dir="",
                browser_audit_dir=tmpdir,
                chrome_binary="",
                time_from="now-1h",
                time_to="now",
                window_width=1600,
                window_height=2200,
                virtual_time_budget_ms=15000,
                screenshot_retries=1,
                timeout=30,
            )

            dom = "<html><body><div data-test-subj='dashboardPanelError'>Error loading data</div></body></html>"

            def fake_run(cmd, stdout=None, stderr=None, text=None, timeout=None, **kwargs):
                stdout.write(dom)
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(smoke, "discover_chrome_binary", return_value="/usr/bin/chrome"):
                with mock.patch.object(smoke.subprocess, "run", side_effect=fake_run):
                    result = smoke.capture_browser_audit(saved_object, args)

        self.assertEqual(result["status"], "error")
        self.assertTrue(result["issues"])
        self.assertTrue(result["path"].endswith("node_exporter_full.html"))

    def test_capture_browser_audit_streams_dom_to_file(self):
        saved_object = {
            "id": "dashboard-123",
            "attributes": {"title": "Node Exporter Full"},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                kibana_url="http://localhost:5601",
                space_id="",
                output="uploaded_dashboard_smoke_report.json",
                screenshot_dir="",
                browser_audit_dir=tmpdir,
                chrome_binary="",
                time_from="now-1h",
                time_to="now",
                window_width=1600,
                window_height=2200,
                virtual_time_budget_ms=15000,
                screenshot_retries=1,
                timeout=30,
            )

            dom = "<html><body><div data-test-subj='dashboardPanelError'>Error loading data</div></body></html>"

            def fake_run(cmd, stdout=None, stderr=None, text=None, timeout=None, **kwargs):
                self.assertIsNotNone(stdout)
                self.assertIsNone(kwargs.get("capture_output"))
                stdout.write(dom)
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(smoke, "discover_chrome_binary", return_value="/usr/bin/chrome"):
                with mock.patch.object(smoke.subprocess, "run", side_effect=fake_run):
                    result = smoke.capture_browser_audit(saved_object, args)

        self.assertEqual(result["status"], "error")
        self.assertTrue(result["issues"])
        self.assertTrue(result["path"].endswith("node_exporter_full.html"))

    def test_browser_audit_detects_invalid_column_error_text(self):
        issues = smoke._browser_audit_issues(
            "<html><body>Provided column name or index is invalid: a8294c09-9d68-cfec-47e2-a7614f7df5b5</body></html>"
        )
        self.assertTrue(issues)

    def test_capture_dashboard_screenshot_writes_png(self):
        saved_object = {
            "id": "dashboard-123",
            "attributes": {"title": "Node Exporter Full"},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                kibana_url="http://localhost:5601",
                space_id="",
                output="uploaded_dashboard_smoke_report.json",
                screenshot_dir=tmpdir,
                chrome_binary="",
                time_from="now-1h",
                time_to="now",
                window_width=1600,
                window_height=2200,
                virtual_time_budget_ms=15000,
                screenshot_retries=1,
                timeout=30,
            )

            def fake_run(cmd, capture_output, text, timeout):
                screenshot_arg = next(item for item in cmd if item.startswith("--screenshot="))
                output_path = pathlib.Path(screenshot_arg.split("=", 1)[1])
                output_path.write_bytes(b"png")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(smoke, "discover_chrome_binary", return_value="/usr/bin/chrome"):
                with mock.patch.object(smoke.subprocess, "run", side_effect=fake_run):
                    result = smoke.capture_dashboard_screenshot(saved_object, args)

        self.assertEqual(result["status"], "captured")
        self.assertTrue(result["path"].endswith("node_exporter_full.png"))

    def test_main_exits_nonzero_when_runtime_failures_are_strict(self):
        args = argparse.Namespace(
            kibana_url="http://localhost:5601",
            kibana_api_key="",
            es_url="http://localhost:9200",
            es_api_key="",
            space_id="",
            output="uploaded_dashboard_smoke_report.json",
            timeout=30,
            saved_objects_per_page=1000,
            dashboard_title=[],
            dashboard_id=[],
            capture_screenshots=False,
            browser_audit=False,
            screenshot_dir="",
            browser_audit_dir="",
            chrome_binary="",
            time_from="now-1h",
            time_to="now",
            window_width=1600,
            window_height=2200,
            virtual_time_budget_ms=15000,
            screenshot_retries=1,
            fail_on_runtime_errors=True,
            fail_on_layout_issues=False,
            fail_on_empty_panels=False,
            fail_on_not_runtime_checked=False,
            fail_on_browser_errors=False,
        )

        dashboard_item = {"id": "dashboard-123", "attributes": {"title": "Dashboard"}}
        dashboard_result = {
            "id": "dashboard-123",
            "title": "Dashboard",
            "total_panels": 1,
            "esql_panels": 1,
            "runtime_checked_panels": 1,
            "failing_panels": [{"panel": "CPU Busy", "status": "fail"}],
            "empty_panels": [],
            "not_runtime_checked_panels": [],
            "non_query_panels": [],
            "layout": {"overlaps": [], "invalid_sizes": [], "out_of_bounds": [], "max_x": 24, "max_y": 8},
            "screenshot": {"status": "not_requested", "path": "", "error": "", "url": ""},
            "browser_audit": {"status": "not_requested", "path": "", "error": "", "issues": [], "url": ""},
            "status": "has_runtime_errors",
            "panels": [{"panel": "CPU Busy", "status": "fail"}],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            args.output = str(pathlib.Path(tmpdir) / "upload_smoke_report.json")
            with mock.patch.object(smoke, "parse_args", return_value=args):
                with mock.patch.object(smoke, "load_dashboards", return_value=[dashboard_item]):
                    with mock.patch.object(smoke, "load_dashboard", return_value=dashboard_item):
                        with mock.patch.object(smoke, "inspect_dashboard", return_value=dashboard_result):
                            with self.assertRaises(SystemExit) as ctx:
                                smoke.main()

        self.assertIn("Smoke validation failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
