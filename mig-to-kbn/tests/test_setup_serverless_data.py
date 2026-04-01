import collections
import importlib.util
import json
import os
import pathlib
import types
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXTRACT_SCRIPT = ROOT / "scripts" / "extract_dashboard_metrics.py"
SETUP_SCRIPT = ROOT / "scripts" / "setup_serverless_data.py"


def _load_module(path: pathlib.Path, module_name: str, env: dict[str, str] | None = None) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, env or {}, clear=False):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class ExtractDashboardMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extract = _load_module(EXTRACT_SCRIPT, "test_extract_dashboard_metrics")

    def test_native_promql_command_extracts_special_metrics(self):
        counters, gauges, labels = self.extract.extract_from_query(
            'PROMQL index=metrics-prometheus-* step=1m value=(count(up == 1) + sum(ALERTS{alertstate="firing"}))'
        )
        self.assertIn("up", gauges)
        self.assertIn("ALERTS", gauges)
        self.assertIn("alertstate", labels)

    def test_native_promql_command_extracts_counters_and_grouping_labels(self):
        counters, gauges, labels = self.extract.extract_from_query(
            'PROMQL index=metrics-prometheus-* step=1m value=(sum(increase(http_request_size_bytes{instance=~".*", quantile="0.99"}[5m])) by (instance, handler) > 0)'
        )
        self.assertIn("http_request_size_bytes", counters)
        self.assertNotIn("http_request_size_bytes", gauges)
        self.assertTrue({"instance", "handler", "quantile"} <= labels)

    def test_native_promql_binary_expression_extracts_all_metrics(self):
        counters, gauges, labels = self.extract.extract_from_query(
            'PROMQL index=metrics-prometheus-* step=1m value=(sum(kube_pod_info{cluster=~".*"}) / sum(kube_node_status_allocatable{resource="pods"}))'
        )
        self.assertTrue({"kube_pod_info", "kube_node_status_allocatable"} <= gauges)
        self.assertTrue({"cluster", "resource"} <= labels)


class SetupServerlessDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.setup = _load_module(
            SETUP_SCRIPT,
            "test_setup_serverless_data",
            env={
                "ELASTICSEARCH_ENDPOINT": "https://example.invalid",
                "KEY": "test-key",
            },
        )

    def _decode_docs(self, lines):
        return [json.loads(doc) for doc in lines[1::2]]

    def test_generate_k8s_docs_emits_required_labels_and_shapes(self):
        ctx = self.setup.GeneratorContext(
            counters={"kube_pod_container_status_restarts_total"},
            gauges={
                "kube_node_status_condition",
                "kube_persistentvolumeclaim_info",
                "kube_persistentvolumeclaim_status_phase",
                "kube_pod_container_info",
                "kube_pod_info",
                "kube_pod_status_reason",
                "kube_node_status_allocatable",
                "kube_node_status_capacity",
            },
            kube_counter_set={"kube_pod_container_status_restarts_total"},
            kube_gauge_set={
                "kube_node_status_condition",
                "kube_persistentvolumeclaim_info",
                "kube_persistentvolumeclaim_status_phase",
                "kube_pod_container_info",
                "kube_pod_info",
                "kube_pod_status_reason",
                "kube_node_status_allocatable",
                "kube_node_status_capacity",
            },
        )
        docs = self._decode_docs(self.setup._generate_k8s_docs("2026-03-26T00:00:00Z", 12.0, '{"create":{}}', ctx))

        self.assertTrue(any(d.get("condition") == "Ready" and d.get("status") == "false" and d.get("kube_node_status_condition") == 1.0 for d in docs))
        self.assertTrue(any(d.get("phase") == "Bound" and d.get("kube_persistentvolumeclaim_status_phase") == 1.0 for d in docs))
        self.assertTrue(any(d.get("reason") == "Evicted" and d.get("kube_pod_status_reason") == 1.0 for d in docs))
        self.assertTrue(any(d.get("resource") == "pods" and "kube_node_status_allocatable" in d for d in docs))
        self.assertTrue(any("container_id" in d and d.get("kube_pod_container_info") == 1.0 for d in docs))

        pvc_info_docs = [d for d in docs if d.get("kube_persistentvolumeclaim_info") == 1.0]
        self.assertTrue(pvc_info_docs)
        self.assertTrue(all("phase" not in d for d in pvc_info_docs))

        dim_fields = ["@timestamp", *self.setup.DIMENSION_LABELS, *self.setup.ALIAS_DIMENSION_LABELS]
        pvc_keys = [
            tuple((field, d.get(field)) for field in dim_fields if field in d)
            for d in docs
            if "kube_persistentvolumeclaim_info" in d or "kube_persistentvolumeclaim_status_phase" in d
        ]
        duplicates = [key for key, count in collections.Counter(pvc_keys).items() if count > 1]
        self.assertFalse(duplicates, f"duplicate PVC time-series keys: {duplicates}")

    def test_generate_windows_docs_emits_cpu_network_and_container_series(self):
        ctx = self.setup.GeneratorContext(
            counters={
                "windows_cpu_time_total",
                "windows_net_bytes_sent_total",
                "windows_net_packets_outbound_discarded_total",
                "windows_container_cpu_usage_seconds_total",
            },
            gauges={
                "windows_os_visible_memory_bytes",
                "windows_memory_available_bytes",
                "windows_container_memory_usage_commit_bytes",
            },
            windows_counter_set={
                "windows_cpu_time_total",
                "windows_net_bytes_sent_total",
                "windows_net_packets_outbound_discarded_total",
                "windows_container_cpu_usage_seconds_total",
            },
            windows_gauge_set={
                "windows_os_visible_memory_bytes",
                "windows_memory_available_bytes",
                "windows_container_memory_usage_commit_bytes",
            },
        )
        docs = self._decode_docs(self.setup._generate_windows_docs("2026-03-26T00:00:00Z", 12.0, '{"create":{}}', ctx))

        self.assertTrue(any("windows_cpu_time_total" in d and "core" in d and "mode" in d for d in docs))
        self.assertTrue(any("windows_net_bytes_sent_total" in d and "nic" in d for d in docs))
        self.assertTrue(any("windows_container_cpu_usage_seconds_total" in d and "container_id" in d for d in docs))
        self.assertTrue(any("windows_os_visible_memory_bytes" in d for d in docs))

    def test_generate_node_cpu_docs_preserve_single_core_time_budget(self):
        ctx = self.setup.GeneratorContext(
            counters={"node_cpu_seconds_total"},
            gauges=set(),
            node_counter_set={"node_cpu_seconds_total"},
        )

        docs_t0 = self._decode_docs(
            self.setup._generate_node_docs("2026-03-26T00:00:00Z", 12.0, 0, 720, '{"create":{}}', ctx)
        )
        docs_t1 = self._decode_docs(
            self.setup._generate_node_docs("2026-03-26T00:00:30Z", 12.0, 1, 720, '{"create":{}}', ctx)
        )

        first = {
            (doc["instance"], doc["cpu"], doc["mode"]): doc["node_cpu_seconds_total"]
            for doc in docs_t0
            if "node_cpu_seconds_total" in doc and "cpu" in doc and "mode" in doc
        }
        second = {
            (doc["instance"], doc["cpu"], doc["mode"]): doc["node_cpu_seconds_total"]
            for doc in docs_t1
            if "node_cpu_seconds_total" in doc and "cpu" in doc and "mode" in doc
        }

        stray_cpu_docs = [
            doc for doc in docs_t0 if "node_cpu_seconds_total" in doc and ("cpu" not in doc or "mode" not in doc)
        ]
        self.assertFalse(stray_cpu_docs, f"unexpected unlabeled cpu docs: {stray_cpu_docs[:2]}")

        per_core_deltas = collections.defaultdict(float)
        for key, end_value in second.items():
            delta = end_value - first[key]
            self.assertGreaterEqual(delta, 0.0, f"counter regressed for {key}")
            per_core_deltas[key[:2]] += delta

        self.assertTrue(per_core_deltas)
        for core_key, total_delta in per_core_deltas.items():
            self.assertAlmostEqual(
                total_delta,
                float(self.setup.INTERVAL_SEC),
                delta=0.05,
                msg=f"cpu modes exceeded one core-second budget for {core_key}",
            )

    def test_generate_node_docs_keep_dimensioned_metrics_on_dimensioned_docs(self):
        ctx = self.setup.GeneratorContext(
            counters={
                "node_cpu_seconds_total",
                "node_disk_reads_completed_total",
                "node_schedstat_running_seconds_total",
                "node_softnet_processed_total",
            },
            gauges={"node_arp_entries", "node_network_transmit_queue_length"},
            node_counter_set={
                "node_cpu_seconds_total",
                "node_disk_reads_completed_total",
                "node_schedstat_running_seconds_total",
                "node_softnet_processed_total",
            },
            node_gauge_set={"node_arp_entries", "node_network_transmit_queue_length"},
        )

        docs = self._decode_docs(
            self.setup._generate_node_docs("2026-03-26T00:00:00Z", 12.0, 0, 720, '{"create":{}}', ctx)
        )

        self.assertTrue(any("node_disk_reads_completed_total" in d and "device" in d for d in docs))
        self.assertTrue(any("node_schedstat_running_seconds_total" in d and "cpu" in d for d in docs))
        self.assertTrue(any("node_softnet_processed_total" in d and "cpu" in d for d in docs))
        self.assertTrue(any("node_arp_entries" in d and "device" in d for d in docs))
        self.assertTrue(any("node_network_transmit_queue_length" in d and "device" in d for d in docs))

        self.assertTrue(
            all("device" in d for d in docs if "node_disk_reads_completed_total" in d),
            "disk metrics must stay on per-device documents",
        )
        self.assertTrue(
            all("cpu" in d and "mode" in d for d in docs if "node_cpu_seconds_total" in d),
            "cpu metrics must stay on per-cpu/per-mode documents",
        )

    def test_generate_node_docs_emit_core_throttles_per_instance(self):
        ctx = self.setup.GeneratorContext(
            counters={"node_cpu_core_throttles_total"},
            gauges=set(),
            node_counter_set={"node_cpu_core_throttles_total"},
        )
        docs = self._decode_docs(
            self.setup._generate_node_docs("2026-03-26T00:00:00Z", 12.0, 0, 720, '{"create":{}}', ctx)
        )
        throttle_docs = [d for d in docs if "node_cpu_core_throttles_total" in d]
        self.assertTrue(throttle_docs)
        self.assertTrue(all("instance" in d for d in throttle_docs))

    def test_generate_node_docs_emit_cpu_scaling_metrics_per_cpu(self):
        metrics = {
            "node_cpu_scaling_frequency_hertz",
            "node_cpu_scaling_frequency_max_hertz",
            "node_cpu_scaling_frequency_min_hertz",
        }
        ctx = self.setup.GeneratorContext(
            counters=set(),
            gauges=set(metrics),
            node_gauge_set=set(metrics),
        )
        docs = self._decode_docs(
            self.setup._generate_node_docs("2026-03-26T00:00:00Z", 12.0, 0, 720, '{"create":{}}', ctx)
        )
        scaling_docs = [d for d in docs if "node_cpu_scaling_frequency_hertz" in d]
        self.assertTrue(scaling_docs)
        self.assertTrue(all("cpu" in d for d in scaling_docs))
        self.assertTrue(all(d["node_cpu_scaling_frequency_min_hertz"] < d["node_cpu_scaling_frequency_hertz"] < d["node_cpu_scaling_frequency_max_hertz"] for d in scaling_docs))

    def test_generate_node_docs_emit_labeled_gauges_with_expected_dimensions(self):
        labeled_metrics = {
            "node_systemd_units",
            "node_processes_state",
            "node_hwmon_chip_names",
            "node_hwmon_temp_celsius",
            "node_hwmon_temp_crit_celsius",
            "node_hwmon_temp_max_celsius",
            "node_scrape_collector_duration_seconds",
            "node_scrape_collector_success",
            "node_textfile_scrape_error",
        }
        ctx = self.setup.GeneratorContext(
            counters=set(),
            gauges=set(labeled_metrics),
            node_gauge_set=set(labeled_metrics),
        )
        docs = self._decode_docs(
            self.setup._generate_node_docs("2026-03-26T00:00:00Z", 12.0, 0, 720, '{"create":{}}', ctx)
        )

        systemd_docs = [d for d in docs if "node_systemd_units" in d]
        self.assertTrue(systemd_docs)
        self.assertTrue(all("state" in d and d["state"] for d in systemd_docs))

        process_docs = [d for d in docs if "node_processes_state" in d]
        self.assertTrue(process_docs)
        self.assertTrue(all("state" in d and d["state"] for d in process_docs))

        hwmon_docs = [d for d in docs if "node_hwmon_temp_celsius" in d]
        self.assertTrue(hwmon_docs)
        self.assertTrue(all({"chip", "chip_name", "sensor"} <= set(d) for d in hwmon_docs))
        self.assertTrue(all(0 < d["node_hwmon_temp_celsius"] < 150 for d in hwmon_docs))

        scrape_docs = [d for d in docs if "node_scrape_collector_duration_seconds" in d]
        self.assertTrue(scrape_docs)
        self.assertTrue(all("collector" in d and d["collector"] for d in scrape_docs))
        self.assertTrue(all(0 < d["node_scrape_collector_duration_seconds"] < 1 for d in scrape_docs))

        textfile_docs = [d for d in docs if "node_textfile_scrape_error" in d]
        self.assertTrue(textfile_docs)
        self.assertTrue(all("collector" in d and d["collector"] for d in textfile_docs))

        self.assertFalse([d for d in docs if "node_systemd_units" in d and "state" not in d])
        self.assertFalse([d for d in docs if "node_processes_state" in d and "state" not in d])
        self.assertFalse([d for d in docs if "node_hwmon_temp_celsius" in d and "chip" not in d])
        self.assertFalse([d for d in docs if "node_scrape_collector_duration_seconds" in d and "collector" not in d])

    def test_generate_prometheus_docs_emits_alerts_and_quantiles(self):
        ctx = self.setup.GeneratorContext(
            counters={"net_conntrack_dialer_conn_failed_total"},
            gauges={"ALERTS", "prometheus_target_interval_length_seconds"},
            prom_counter_set={"net_conntrack_dialer_conn_failed_total"},
            prom_gauge_set={"ALERTS", "prometheus_target_interval_length_seconds"},
            prom_labeled_metrics={"ALERTS", "prometheus_target_interval_length_seconds"},
        )
        docs = self._decode_docs(self.setup._generate_prometheus_docs("2026-03-26T00:00:00Z", 12.0, 4, '{"create":{}}', ctx))

        self.assertTrue(any(d.get("quantile") == "0.99" and d.get("prometheus_target_interval_length_seconds") for d in docs))
        self.assertTrue(any(d.get("alertstate") == "firing" and d.get("ALERTS") == 1.0 for d in docs))
        self.assertTrue(any("net_conntrack_dialer_conn_failed_total" in d for d in docs))

    def test_generate_prometheus_docs_emit_error_metrics_when_requested(self):
        required_metrics = {
            "prometheus_target_scrapes_sample_out_of_bounds_total",
            "prometheus_target_scrapes_sample_out_of_order_total",
            "prometheus_rule_evaluation_failures_total",
            "prometheus_tsdb_compactions_failed_total",
            "prometheus_tsdb_reloads_failures_total",
            "prometheus_tsdb_head_series_not_found",
            "prometheus_evaluator_iterations_missed_total",
            "prometheus_evaluator_iterations_skipped_total",
        }
        self.assertTrue(required_metrics <= self.setup.EXTRA_COUNTER_METRICS)

        ctx = self.setup.GeneratorContext(
            counters=set(required_metrics),
            gauges=set(),
            prom_counter_set=set(required_metrics),
        )
        docs = self._decode_docs(
            self.setup._generate_prometheus_docs("2026-03-26T00:00:00Z", 12.0, 4, '{"create":{}}', ctx)
        )

        for metric in required_metrics:
            self.assertTrue(any(metric in d for d in docs), f"missing generated metric {metric}")

    def test_generate_prometheus_docs_emits_go_goroutines_when_requested(self):
        self.assertIn("go_goroutines", self.setup.EXTRA_GAUGE_METRICS)

        ctx = self.setup.GeneratorContext(
            counters=set(),
            gauges={"go_goroutines"},
            prom_gauge_set={"go_goroutines"},
        )
        docs = self._decode_docs(self.setup._generate_prometheus_docs("2026-03-26T00:00:00Z", 12.0, 4, '{"create":{}}', ctx))

        self.assertTrue(any(d.get("go_goroutines", 0) > 0 for d in docs))

    def test_generate_k8s_docs_emit_job_status_metrics_with_job_name(self):
        ctx = self.setup.GeneratorContext(
            counters=set(),
            gauges={
                "kube_job_status_active",
                "kube_job_status_failed",
                "kube_job_status_succeeded",
                "kube_job_status_completion_time",
            },
            kube_gauge_set={
                "kube_job_status_active",
                "kube_job_status_failed",
                "kube_job_status_succeeded",
                "kube_job_status_completion_time",
            },
        )
        docs = self._decode_docs(
            self.setup._generate_k8s_docs("2026-03-26T00:00:00Z", 12.0, '{"create":{}}', ctx)
        )

        job_docs = [d for d in docs if d.get("job_name")]
        self.assertTrue(job_docs)
        self.assertTrue(any(d.get("kube_job_status_completion_time") for d in job_docs))
        self.assertTrue(any(d.get("kube_job_status_failed", 0) > 1 for d in job_docs))
        dim_fields = ["@timestamp", *self.setup.DIMENSION_LABELS, *self.setup.ALIAS_DIMENSION_LABELS]
        job_keys = [tuple((field, d.get(field)) for field in dim_fields if field in d) for d in job_docs]
        duplicates = [key for key, count in collections.Counter(job_keys).items() if count > 1]
        self.assertFalse(duplicates, f"duplicate job time-series keys: {duplicates}")
