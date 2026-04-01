#!/usr/bin/env python3
"""
Sets up TSDB index template and ingests realistic Prometheus-style metrics
into an Elastic Serverless cluster so that native PROMQL dashboards work.

Generates 48 hours of data at 30-second intervals with realistic diurnal
patterns, load spikes, gradual trends, and correlated metrics.

Data is generated only for the dashboard families present in
infra/grafana/dashboards/:
  - Node Exporter (node-exporter-full, node-exporter-old-schema)
  - Prometheus self-monitoring (prometheus-all)
  - Kubernetes (k8s-views-global, kube-state-metrics-v2)
  - OpenTelemetry Collector (otel-collector-dashboard)
  - Logs (loki-dashboard, diverse-panels-test)

Additional service families (cAdvisor, alertmanager, etc.) are emitted only
when the extracted dashboard metrics include their prefixes.
"""

import json
import os
import sys
import time
import random
import math
import datetime
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

ES_ENDPOINT = os.environ["ELASTICSEARCH_ENDPOINT"]
API_KEY = os.environ["KEY"]

HEADERS = {
    "Authorization": f"ApiKey {API_KEY}",
    "Content-Type": "application/json",
}

INDEX_NAME = "metrics-prometheus-default"
LOGS_INDEX_NAME = "logs-generic-default"

DATA_HOURS = float(os.environ.get("DATA_HOURS", "48"))
INTERVAL_SEC = int(os.environ.get("INTERVAL_SEC", "30"))
BULK_WORKERS = int(os.environ.get("BULK_WORKERS", "4"))
BATCH_DOC_LIMIT = int(os.environ.get("BATCH_DOC_LIMIT", "8000"))


def es_request(method, path, body=None, content_type="application/json"):
    url = f"{ES_ENDPOINT}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode() if isinstance(body, dict) else body
    headers = {**HEADERS}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        print(f"  HTTP {e.code}: {err_body[:300]}")
        return json.loads(err_body) if err_body else {}


# ---------------------------------------------------------------------------
# Realistic pattern helpers
# ---------------------------------------------------------------------------

def diurnal(hour_of_day):
    """Returns 0.0-1.0 load factor: peak ~14:00, valley ~04:00."""
    return 0.5 + 0.5 * math.sin(math.pi * (hour_of_day - 4) / 12)


def with_spike(base, t_idx, total_points, spike_pct=0.02, spike_mult=3.0):
    """Occasionally spike a value."""
    if random.random() < spike_pct:
        return base * spike_mult
    return base


def gauge_val(base, amplitude, hour, noise_frac=0.1):
    """Gauge with diurnal pattern + noise."""
    d = diurnal(hour)
    noise = random.gauss(0, base * noise_frac) if noise_frac else 0
    return max(0, base + amplitude * d + noise)


def counter_incr(rate_per_sec, interval, hour, burst_frac=0.15):
    """Monotonic counter increment with diurnal rate modulation."""
    d = diurnal(hour)
    effective_rate = rate_per_sec * (0.3 + 0.7 * d)
    burst = random.expovariate(1 / (effective_rate * interval * burst_frac)) if random.random() < 0.05 else 0
    return max(0, random.gauss(effective_rate * interval, effective_rate * interval * 0.1) + burst)


def _clamp(value, lower, upper):
    return max(lower, min(upper, value))


def _linux_cpu_mode_shares(hour, t_idx, total_points, cpu_id):
    """Return normalized per-core Linux CPU mode shares that sum to 1.0."""
    cycle = max(total_points, 1)
    phase = (2 * math.pi * (t_idx / cycle)) + cpu_id * 0.7
    busy = _clamp(0.15 + 0.45 * diurnal(hour) + 0.05 * math.sin(phase), 0.08, 0.80)
    iowait = 0.004 + 0.02 * diurnal(hour) + 0.004 * (1 + math.sin(phase + 0.9)) / 2
    irq = 0.002 + 0.003 * (1 + math.sin(phase + 1.7)) / 2
    softirq = 0.004 + 0.006 * (1 + math.cos(phase + 0.4)) / 2
    steal = 0.001 + 0.002 * (1 + math.sin(phase + 2.4)) / 2
    nice = 0.003 + 0.005 * (1 + math.cos(phase + 1.1)) / 2
    non_user_system = iowait + irq + softirq + steal + nice
    user_system = max(0.02, busy - non_user_system)
    shares = {
        "user": user_system * 0.72,
        "system": user_system * 0.28,
        "iowait": iowait,
        "nice": nice,
        "irq": irq,
        "softirq": softirq,
        "steal": steal,
    }
    shares["idle"] = max(0.05, 1 - sum(shares.values()))
    total = sum(shares.values())
    return {mode: share / total for mode, share in shares.items()}


def _windows_cpu_mode_shares(hour, core_id):
    """Return normalized Windows CPU mode shares that sum to 1.0."""
    phase = (2 * math.pi * (hour / 24.0)) + core_id * 0.6
    busy = _clamp(0.18 + 0.42 * diurnal(hour) + 0.04 * math.sin(phase), 0.08, 0.78)
    privileged = min(busy * 0.45, 0.03 + busy * 0.22)
    shares = {
        "user": max(0.02, busy - privileged),
        "privileged": privileged,
    }
    shares["idle"] = max(0.05, 1 - sum(shares.values()))
    total = sum(shares.values())
    return {mode: share / total for mode, share in shares.items()}


# ---------------------------------------------------------------------------
# Dimension labels used as TSDB routing/dimension fields
# ---------------------------------------------------------------------------

DIMENSION_LABELS = [
    "job", "instance", "namespace", "job_name", "node", "pod", "device",
    "fstype", "mountpoint", "mode", "cpu", "phase", "state",
    "handler", "receiver", "exporter", "name", "pool", "area",
    "id", "level", "status", "uri", "application", "operstate",
    "condition", "resource", "reason", "origin_prometheus",
    "nodename", "processor", "hpa", "integration",
    "service_instance_id", "quantile", "alertstate", "exception", "collector",
    "component", "tag", "path", "qos_class",
    "msg_type", "slice", "scrape_job",
    "exported_namespace",
    "chip", "chip_name", "sensor", "nic", "core", "container_id", "persistentvolumeclaim",
    "power_supply", "alertname", "severity",
    "action", "type", "le",
    "service", "cmd", "db", "release", "activity",
    "container", "image",
    "version", "cluster", "kubernetes_pod_name", "kubernetes_namespace",
]

ALIAS_DIMENSION_LABELS = [
    "service.name",
    "service.instance.id",
    "k8s.cluster.name",
    "k8s.node.name",
    "k8s.namespace.name",
    "k8s.pod.name",
]

EXTRA_COUNTER_METRICS = {
    "node_cpu_seconds_total",
    "go_memstats_alloc_bytes_total",
    "node_context_switches",
    "node_disk_reads_completed",
    "node_disk_bytes_read",
    "node_disk_bytes_written",
    "prometheus_notifications_dropped_total",
    "prometheus_target_sync_length_seconds_count",
    "prometheus_tsdb_compaction_duration_count",
    "prometheus_tsdb_compaction_duration_seconds",
    "prometheus_tsdb_compaction_duration_sum",
    "prometheus_tsdb_head_chunks_created_total",
    "prometheus_tsdb_head_samples_appended_total",
    "prometheus_tsdb_head_series_created_total",
    "prometheus_tsdb_reloads_total",
    "otelcol_receiver_accepted_spans",
    "otelcol_receiver_accepted_metric_points",
    "otelcol_receiver_refused_spans",
    "otelcol_receiver_refused_metric_points",
    "otelcol_processor_accepted_spans",
    "otelcol_processor_refused_spans",
    "otelcol_processor_dropped_spans",
    "otelcol_exporter_sent_spans",
    "otelcol_exporter_sent_metric_points",
    "otelcol_exporter_enqueue_failed_spans",
    "otelcol_exporter_enqueue_failed_metric_points",
    "otelcol_process_cpu_seconds",
    "node_netstat_Tcp_InSegs",
    "node_netstat_Tcp_OutSegs",
    "node_netstat_Tcp_RetransSegs",
    "node_vmstat_pgpgin",
    "node_vmstat_pgpgout",
    "node_vmstat_pswpin",
    "node_vmstat_pswpout",
    "node_vmstat_pgfault",
    "node_vmstat_pgmajfault",
    "node_vmstat_oom_kill",
    "process_resident_memory_bytes",
    "process_virtual_memory_bytes",
    "node_netstat_Icmp_InErrors",
    "node_netstat_Icmp_InMsgs",
    "node_netstat_Icmp_OutMsgs",
    "node_netstat_IpExt_InOctets",
    "node_netstat_IpExt_OutOctets",
    "node_netstat_Tcp_ActiveOpens",
    "node_netstat_Tcp_PassiveOpens",
    "node_netstat_Tcp_InErrs",
    "node_netstat_Tcp_OutRsts",
    "node_netstat_TcpExt_ListenOverflows",
    "node_netstat_TcpExt_ListenDrops",
    "node_netstat_TcpExt_TCPSynRetrans",
    "node_netstat_TcpExt_TCPRcvQDrop",
    "node_netstat_TcpExt_TCPOFOQueue",
    "node_netstat_TcpExt_SyncookiesFailed",
    "node_netstat_TcpExt_SyncookiesRecv",
    "node_netstat_TcpExt_SyncookiesSent",
    "node_netstat_Udp_InDatagrams",
    "node_netstat_Udp_OutDatagrams",
    "node_netstat_Udp_InErrors",
    "node_netstat_Udp_NoPorts",
    "node_netstat_Udp_RcvbufErrors",
    "node_netstat_Udp_SndbufErrors",
    "node_netstat_UdpLite_InErrors",
    "node_netstat_Ip_Forwarding",
    "node_cpu_core_throttles_total",
    "container_oom_events_total",
    "kube_pod_container_status_restarts_total",
    "http_request_duration_microseconds",
    "http_request_size_bytes",
    "otelcol_processor_batch_batch_send_size_count",
    "container_cpu_cfs_throttled_seconds_total",
    "http_requests_total",
    "container_cpu_usage_seconds_total",
    "container_network_receive_bytes_total",
    "node_cpu_guest_seconds_total",
    "node_disk_discard_time_seconds_total",
    "node_disk_discards_completed_total",
    "node_disk_discards_merged_total",
    "node_disk_io_time_seconds_total",
    "node_disk_io_time_weighted_seconds_total",
    "node_disk_read_bytes_total",
    "node_disk_read_time_seconds_total",
    "node_disk_reads_completed_total",
    "node_disk_reads_merged_total",
    "node_disk_write_time_seconds_total",
    "node_disk_writes_completed_total",
    "node_disk_writes_merged_total",
    "node_disk_written_bytes_total",
    "node_network_receive_bytes_total",
    "node_network_receive_compressed_total",
    "node_network_receive_drop_total",
    "node_network_receive_errs_total",
    "node_network_receive_fifo_total",
    "node_network_receive_packets_total",
    "node_network_transmit_compressed_total",
    "node_network_transmit_drop_total",
    "node_network_transmit_errs_total",
    "node_network_transmit_fifo_total",
    "node_network_transmit_packets_total",
    "node_pressure_memory_waiting_seconds_total",
    "node_schedstat_running_seconds_total",
    "node_schedstat_waiting_seconds_total",
    "node_softnet_processed_total",
    "node_softnet_dropped_total",
    "prometheus_target_scrapes_exceeded_sample_limit_total",
    "prometheus_target_scrapes_sample_duplicate_timestamp_total",
    "prometheus_target_scrapes_sample_out_of_bounds_total",
    "prometheus_target_scrapes_sample_out_of_order_total",
    "prometheus_tsdb_head_chunks_removed_total",
    "prometheus_tsdb_head_series_removed_total",
    "prometheus_rule_evaluation_failures_total",
    "prometheus_tsdb_compactions_failed_total",
    "prometheus_tsdb_reloads_failures_total",
    "prometheus_tsdb_head_series_not_found",
    "prometheus_evaluator_iterations_missed_total",
    "prometheus_evaluator_iterations_skipped_total",
    "prometheus_sd_consul_rpc_failures_total",
    "prometheus_sd_file_read_errors_total",
    "prometheus_sd_marathon_refresh_failures_total",
    "prometheus_sd_openstack_refresh_failures_total",
    "windows_cpu_time_total",
    "windows_container_cpu_usage_seconds_total",
    "windows_container_network_receive_bytes_total",
    "windows_container_network_transmit_bytes_total",
    "windows_net_bytes_received_total",
    "windows_net_bytes_sent_total",
    "windows_net_packets_received_discarded_total",
    "windows_net_packets_outbound_discarded_total",
    "node_network_transmit_bytes_total",
    "node_network_transmit_drop_total",
    "node_network_transmit_errs_total",
    "node_network_transmit_packets_total",
    "node_intr_total",
    "otelcol_processor_batch_batch_send_size_sum",
    "node_pressure_io_waiting_seconds_total",
    "node_pressure_memory_stalled_seconds_total",
    "node_pressure_io_stalled_seconds_total",
    "net_conntrack_dialer_conn_failed_total",
    "http_request_duration_seconds_bucket",
    "process_virtual_memory_max_bytes",
}

EXTRA_GAUGE_METRICS = {
    "ALERTS",
    "up",
    "go_goroutines",
    "kube_persistentvolumeclaim_resource_requests_storage_bytes",
    "node_cpu",
    "node_power_supply_online",
    "node_disk_io_time_ms",
    "node_disk_sectors_read",
    "node_filesystem_avail",
    "node_memory_Buffers",
    "node_memory_Cached",
    "node_memory_MemFree",
    "node_memory_MemTotal",
    "node_memory_MemAvailable",
    "node_memory_PageTables",
    "node_memory_Slab",
    "node_memory_SwapCached",
    "node_memory_VmallocUsed",
    "node_network_receive_bytes",
    "node_netstat_Tcp_CurrEstab",
    "prometheus_build_info",
    "prometheus_engine_queries",
    "prometheus_engine_query_duration_seconds",
    "prometheus_notifications_alertmanagers_discovered",
    "prometheus_notifications_queue_capacity",
    "prometheus_target_interval_length_seconds",
    "prometheus_tsdb_blocks_loaded",
    "prometheus_tsdb_head_chunks",
    "prometheus_tsdb_head_gc_duration_seconds",
    "prometheus_tsdb_head_max_time",
    "prometheus_tsdb_head_min_time",
    "prometheus_tsdb_head_series",
    "prometheus_tsdb_wal_truncate_duration_seconds",
    "tsdb_wal_fsync_duration_seconds",
    "cluster_autoscaler_last_activity",
    "process_resident_memory_bytes",
    "system_cpu_count",
    "node_memory_AnonHugePages_bytes",
    "node_memory_AnonPages_bytes",
    "node_memory_Active_anon_bytes",
    "node_memory_Active_file_bytes",
    "node_memory_Bounce_bytes",
    "node_memory_DirectMap1G_bytes",
    "node_memory_DirectMap2M_bytes",
    "node_memory_DirectMap4k_bytes",
    "node_memory_HardwareCorrupted_bytes",
    "node_memory_HugePages_Rsvd",
    "node_memory_HugePages_Surp",
    "node_memory_Hugepagesize_bytes",
    "node_memory_Inactive_anon_bytes",
    "node_memory_Inactive_file_bytes",
    "node_memory_Mlocked_bytes",
    "node_memory_NFS_Unstable_bytes",
    "node_memory_Percpu_bytes",
    "node_memory_ShmemHugePages_bytes",
    "node_memory_ShmemPmdMapped_bytes",
    "node_memory_Unevictable_bytes",
    "node_memory_VmallocChunk_bytes",
    "node_memory_WritebackTmp_bytes",
    "node_sockstat_FRAG_inuse",
    "node_sockstat_FRAG_memory",
    "node_sockstat_RAW_inuse",
    "node_sockstat_TCP_alloc",
    "node_sockstat_TCP_inuse",
    "node_sockstat_TCP_mem_bytes",
    "node_sockstat_TCP_orphan",
    "node_sockstat_TCP_tw",
    "node_sockstat_UDP_inuse",
    "node_sockstat_UDP_mem",
    "node_sockstat_UDP_mem_bytes",
    "node_sockstat_UDPLITE_inuse",
    "node_netstat_Tcp_MaxConn",
    "node_disk_io_now",
    "node_network_transmit_queue_length",
    "node_sockstat_sockets_used",
    "node_tcp_connection_states",
    "node_timex_estimated_error_seconds",
    "node_timex_loop_time_constant",
    "node_timex_sync_status",
    "node_timex_tick_seconds",
    "node_processes_state",
    "node_processes_pids",
    "node_processes_threads",
    "node_systemd_units",
    "kube_node_status_condition",
    "kube_statefulset_status_replicas_ready",
    "kube_job_status_completion_time",
    "kube_statefulset_status_replicas",
    "node_scrape_collector_success",
    "go_memstats_alloc_bytes",
    "kube_deployment_labels",
    "kube_statefulset_labels",
    "kube_endpoint_info",
    "kube_ingress_info",
    "kube_pod_container_resource_limits",
    "kube_service_info",
    "machine_cpu_cores",
    "machine_memory_bytes",
    "node_cooling_device_cur_state",
    "node_cooling_device_max_state",
    "node_cpu_scaling_frequency_hertz",
    "node_cpu_scaling_frequency_max_hertz",
    "node_processes_max_processes",
    "node_processes_max_threads",
    "node_textfile_scrape_error",
    "node_scrape_collector_duration_seconds",
    "node_hwmon_chip_names",
    "node_hwmon_temp_celsius",
    "node_hwmon_temp_crit_alarm_celsius",
    "node_hwmon_temp_crit_celsius",
    "node_hwmon_temp_crit_hyst_celsius",
    "node_hwmon_temp_max_celsius",
    "node_timex_frequency_adjustment_ratio",
    "node_timex_maxerror_seconds",
    "node_timex_offset_seconds",
    "node_timex_tai_offset_seconds",
    "node_cpu_scaling_frequency_min_hertz",
    "prometheus_engine_queries_concurrent_max",
    "prometheus_notifications_queue_length",
    "windows_memory_available_bytes",
    "windows_memory_cache_bytes",
    "windows_os_visible_memory_bytes",
    "windows_container_memory_usage_commit_bytes",
}


# ---------------------------------------------------------------------------
# Generator context (replaces the 18-parameter generate_batch signature)
# ---------------------------------------------------------------------------

@dataclass
class GeneratorContext:
    counters: set[str]
    gauges: set[str]
    counter_state: dict = field(default_factory=dict)
    node_counter_set: set[str] = field(default_factory=set)
    node_gauge_set: set[str] = field(default_factory=set)
    kube_counter_set: set[str] = field(default_factory=set)
    kube_gauge_set: set[str] = field(default_factory=set)
    container_set: set[str] = field(default_factory=set)
    otel_set: set[str] = field(default_factory=set)
    prom_counter_set: set[str] = field(default_factory=set)
    prom_gauge_set: set[str] = field(default_factory=set)
    process_set: set[str] = field(default_factory=set)
    windows_counter_set: set[str] = field(default_factory=set)
    windows_gauge_set: set[str] = field(default_factory=set)
    prom_labeled_metrics: set[str] = field(default_factory=set)
    gated_services: dict[str, set[str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Gated service registry -- fires only when extracted metrics match prefixes.
# Maps service key -> list of instance label dicts to emit docs for.
# ---------------------------------------------------------------------------

GATED_SERVICE_INSTANCES: dict[str, list[dict[str, str]]] = {
    "cadvisor": [
        {
            "job": "cadvisor",
            "instance": "cadvisor:8080",
            "cluster": "prod-cluster",
            "namespace": "default",
            "pod": "app-pod-abc",
            "container": "app",
            "container_id": "containerd://abc123",
            "id": "/docker/abc123",
            "image": "ghcr.io/example/app:1.0.0",
        },
        {
            "job": "cadvisor",
            "instance": "cadvisor:8080",
            "cluster": "prod-cluster",
            "namespace": "kube-system",
            "pod": "coredns-xyz",
            "container": "coredns",
            "container_id": "containerd://cde456",
            "id": "/docker/cde456",
            "image": "registry.k8s.io/coredns/coredns:v1.11.1",
        },
        {
            "job": "cadvisor",
            "instance": "cadvisor:8080",
            "cluster": "prod-cluster",
            "namespace": "monitoring",
            "pod": "prometheus-0",
            "container": "prometheus",
            "container_id": "containerd://prm789",
            "id": "/docker/prm789",
            "image": "quay.io/prometheus/prometheus:v2.52.0",
        },
    ],
    "alertmanager": [
        {"job": "alertmanager", "instance": "alertmanager:9093"},
    ],
    "etcd": [
        {"job": "etcd", "instance": "etcd-1:2379"},
    ],
    "coredns": [
        {"job": "coredns", "instance": "coredns:9153"},
    ],
    "redis": [
        {"job": "redis", "instance": "redis:9121"},
    ],
    "pg": [
        {"job": "postgres", "instance": "postgres:9187", "release": "pg-exporter"},
    ],
    "mysql": [
        {"job": "mysql", "instance": "mysql:9104"},
    ],
    "rabbitmq": [
        {"job": "rabbitmq", "instance": "rabbitmq:15692"},
    ],
    "kafka": [
        {"job": "kafka", "instance": "kafka:9308"},
    ],
    "grafana": [
        {"job": "grafana", "instance": "grafana:3000"},
    ],
    "istio": [
        {"job": "istio-mesh", "instance": "istio-proxy:15090"},
    ],
    "traefik": [
        {"job": "traefik", "instance": "traefik:8080"},
    ],
    "certmanager": [
        {"job": "cert-manager", "instance": "cert-manager:9402"},
    ],
    "loki": [
        {"job": "loki", "instance": "loki:3100"},
    ],
    "go": [
        {"job": "go-app", "instance": "goapp:8080"},
    ],
    "docker": [
        {"job": "docker", "instance": "docker:9323"},
    ],
    "http": [
        {"job": "prometheus", "instance": "prom:9090", "handler": "/metrics", "quantile": "0.99"},
        {"job": "prometheus", "instance": "prom:9090", "handler": "/api/v1/query", "quantile": "0.99"},
        {"job": "prometheus", "instance": "prom:9090", "handler": "/api/v1/query_range", "quantile": "0.99"},
    ],
    "windows": [
        {"job": "windows-exporter", "instance": "windows-1:9182", "cluster": "prod-cluster", "node": "win-node-1", "nic": "Ethernet0"},
        {"job": "windows-exporter", "instance": "windows-2:9182", "cluster": "prod-cluster", "node": "win-node-2", "nic": "Ethernet1"},
    ],
}

GATED_SERVICE_PREFIXES: dict[str, list[str]] = {
    "cadvisor": ["container_"],
    "alertmanager": ["alertmanager_"],
    "etcd": ["etcd_"],
    "coredns": ["coredns_"],
    "redis": ["redis_"],
    "pg": ["pg_"],
    "mysql": ["mysql_"],
    "rabbitmq": ["rabbitmq_"],
    "kafka": ["kafka_"],
    "grafana": ["grafana_"],
    "istio": ["istio_"],
    "traefik": ["traefik_"],
    "certmanager": ["certmanager_"],
    "loki": ["loki_", "promtail_"],
    "go": ["go_"],
    "docker": ["machine_"],
    "http": ["http_"],
    "windows": ["windows_"],
}


# ---------------------------------------------------------------------------
# Template builders
# ---------------------------------------------------------------------------

def build_template(counters, gauges):
    properties: dict[str, dict[str, object]] = {
        "@timestamp": {"type": "date"},
    }
    dim_set = set(DIMENSION_LABELS)
    for label in DIMENSION_LABELS:
        properties[label] = {"type": "keyword", "time_series_dimension": True}
    for label in ALIAS_DIMENSION_LABELS:
        properties[label] = {"type": "keyword", "time_series_dimension": True}

    for m in counters:
        if m not in dim_set:
            properties[m] = {"type": "double", "time_series_metric": "counter"}
    for m in gauges:
        if m not in dim_set:
            properties[m] = {"type": "double", "time_series_metric": "gauge"}

    ds_parts = INDEX_NAME.split("-")
    ds_type = ds_parts[0] if len(ds_parts) >= 1 else "metrics"
    ds_dataset = ds_parts[1] if len(ds_parts) >= 2 else "generic"
    ds_namespace = ds_parts[2] if len(ds_parts) >= 3 else "default"

    properties["data_stream.type"] = {
        "type": "constant_keyword",
        "value": ds_type,
    }
    properties["data_stream.dataset"] = {
        "type": "constant_keyword",
        "value": ds_dataset,
    }
    properties["data_stream.namespace"] = {
        "type": "constant_keyword",
        "value": ds_namespace,
    }

    index_pattern = f"{ds_type}-{ds_dataset}-*"
    return {
        "index_patterns": [index_pattern],
        "data_stream": {},
        "template": {
            "settings": {
                "index.mode": "time_series",
                "index.routing_path": ["job", "instance"],
            },
            "mappings": {
                "subobjects": False,
                "properties": properties,
            },
        },
        "priority": 700,
    }


def build_logs_template():
    return {
        "index_patterns": [LOGS_INDEX_NAME],
        "data_stream": {},
        "template": {
            "mappings": {
                "subobjects": False,
                "properties": {
                    "@timestamp": {"type": "date"},
                    "__name__": {"type": "keyword"},
                    "message": {"type": "keyword"},
                    "namespace": {"type": "keyword"},
                    "instance": {"type": "keyword"},
                    "service.instance.id": {"type": "keyword"},
                    "service.name": {"type": "keyword"},
                    "host.name": {"type": "keyword"},
                    "k8s.namespace.name": {"type": "keyword"},
                    "k8s.pod.name": {"type": "keyword"},
                    "log.level": {"type": "keyword"},
                    "http.url": {"type": "keyword"},
                    "http.status_code": {"type": "keyword"},
                    "container.name": {"type": "keyword"},
                    "source": {"type": "keyword"},
                },
            },
        },
        "priority": 700,
    }


def ensure_time_series_data_stream(index_name, *, expected_index_mode="time_series"):
    """Create the data stream explicitly and optionally verify its backing index mode."""
    result = {}
    for _attempt in range(5):
        result = es_request("PUT", f"/_data_stream/{index_name}")
        if result.get("acknowledged"):
            break
        error = result.get("error", {}) if isinstance(result, dict) else {}
        if error.get("type") == "resource_already_exists_exception":
            es_request("DELETE", f"/_data_stream/{index_name}")
            time.sleep(2)
            continue
        print(f"   Data stream creation failed: {result}")
        sys.exit(1)
    else:
        print(f"   Data stream creation failed after retries: {result}")
        sys.exit(1)

    info = es_request("GET", f"/_data_stream/{index_name}")
    streams = info.get("data_streams") or []
    if not streams:
        print(f"   Data stream lookup failed: {info}")
        sys.exit(1)

    backing_indices = streams[0].get("indices") or []
    backing_mode = (backing_indices[0] or {}).get("index_mode") if backing_indices else ""
    if expected_index_mode and backing_mode != expected_index_mode:
        print(
            f"   Backing index mode is not {expected_index_mode}; "
            f"got {backing_mode or 'unknown'} for {index_name}"
        )
        sys.exit(1)

    print(f"   Data stream created successfully ({backing_mode or 'standard'})")


# ---------------------------------------------------------------------------
# ECS alias population
# ---------------------------------------------------------------------------

def apply_dashboard_aliases(doc):
    """Populate ECS-style alias dimensions expected by translated dashboards."""
    if "service.name" not in doc:
        value = doc.get("service") or doc.get("job")
        if value:
            doc["service.name"] = value

    if "service.instance.id" not in doc:
        value = doc.get("service_instance_id") or doc.get("instance")
        if value:
            doc["service.instance.id"] = value

    if "k8s.cluster.name" not in doc:
        value = doc.get("cluster")
        if value:
            doc["k8s.cluster.name"] = value

    if "k8s.node.name" not in doc:
        value = doc.get("node") or doc.get("nodename")
        if value:
            doc["k8s.node.name"] = value

    if "k8s.namespace.name" not in doc:
        value = doc.get("namespace") or doc.get("kubernetes_namespace") or doc.get("exported_namespace")
        if value:
            doc["k8s.namespace.name"] = value

    if "k8s.pod.name" not in doc:
        value = doc.get("pod") or doc.get("kubernetes_pod_name")
        if value:
            doc["k8s.pod.name"] = value

    return doc


def serialize_dashboard_docs(lines):
    """Add alias fields to NDJSON document lines without touching bulk actions."""
    output = []
    expecting_doc = False
    for line in lines:
        if expecting_doc:
            output.append(json.dumps(apply_dashboard_aliases(json.loads(line))))
            expecting_doc = False
            continue
        output.append(line)
        expecting_doc = line.lstrip().startswith('{"create"')
    return output


# ---------------------------------------------------------------------------
# Per-service generators
# ---------------------------------------------------------------------------

def _generate_node_docs(ts_iso, hour, t_idx, total_points, action, ctx):
    """Node Exporter metrics -- CPU per-core, memory, filesystem, network, misc."""
    lines = []
    sec_since_start = t_idx * INTERVAL_SEC

    MEM_TOTAL = 16 * 1024**3
    SWAP_TOTAL = 4 * 1024**3
    FS_SIZE = 500 * 1024**3

    node_instances = [
        {"job": "node", "instance": "node1:9100", "nodename": "node1"},
        {"job": "node", "instance": "node2:9100", "nodename": "node2"},
        {"job": "node", "instance": "node3:9100", "nodename": "node3"},
    ]
    dimensioned_prefixes = (
        "node_cpu",
        "node_disk_",
        "node_filesystem_",
        "node_network_",
        "node_schedstat_",
        "node_softnet_",
    )
    explicit_labeled_metrics = {
        "node_systemd_units",
        "node_processes_state",
        "node_hwmon_chip_names",
        "node_hwmon_temp_celsius",
        "node_hwmon_temp_crit_alarm_celsius",
        "node_hwmon_temp_crit_celsius",
        "node_hwmon_temp_crit_hyst_celsius",
        "node_hwmon_temp_max_celsius",
        "node_scrape_collector_duration_seconds",
        "node_scrape_collector_success",
        "node_textfile_scrape_error",
    }

    def set_counter(doc, key, metric, rate_per_sec=None, *, share=None):
        ck = ("node",) + tuple(key) + (metric,)
        if ck not in ctx.counter_state:
            ctx.counter_state[ck] = random.uniform(0, 1e7)
        if share is not None:
            ctx.counter_state[ck] += INTERVAL_SEC * share
        else:
            rate = max(rate_per_sec or 0.0, 0.0)
            if rate:
                ctx.counter_state[ck] += counter_incr(rate, INTERVAL_SEC, hour)
        doc[metric] = round(ctx.counter_state[ck], 3)

    for inst in node_instances:
        # CPU per-core per-mode
        for cpu_id in range(4):
            mode_shares = _linux_cpu_mode_shares(hour, t_idx, total_points, cpu_id)
            for mode in ["user", "system", "idle", "iowait", "nice", "irq", "softirq", "steal"]:
                doc = {"@timestamp": ts_iso, **inst, "cpu": str(cpu_id), "mode": mode}
                ck = (inst["instance"], cpu_id, mode)
                if ck not in ctx.counter_state:
                    ctx.counter_state[ck] = random.uniform(1e3, 5e4)
                ctx.counter_state[ck] += INTERVAL_SEC * mode_shares[mode]
                doc["node_cpu_seconds_total"] = round(ctx.counter_state[ck], 3)
                lines.append(action)
                lines.append(json.dumps(doc))

            cpu_doc = {"@timestamp": ts_iso, **inst, "cpu": str(cpu_id)}
            busy_share = 1.0 - mode_shares["idle"]
            wait_share = min(0.35, mode_shares["iowait"] + 0.02 + 0.01 * diurnal(hour))
            if "node_schedstat_running_seconds_total" in ctx.node_counter_set:
                set_counter(
                    cpu_doc,
                    (inst["instance"], cpu_id, "running"),
                    "node_schedstat_running_seconds_total",
                    share=busy_share,
                )
            if "node_schedstat_waiting_seconds_total" in ctx.node_counter_set:
                set_counter(
                    cpu_doc,
                    (inst["instance"], cpu_id, "waiting"),
                    "node_schedstat_waiting_seconds_total",
                    share=wait_share,
                )
            if "node_schedstat_timeslices_total" in ctx.node_counter_set:
                set_counter(
                    cpu_doc,
                    (inst["instance"], cpu_id, "timeslices"),
                    "node_schedstat_timeslices_total",
                    rate_per_sec=180 + 90 * busy_share,
                )
            if "node_softnet_processed_total" in ctx.node_counter_set:
                set_counter(
                    cpu_doc,
                    (inst["instance"], cpu_id, "softnet_processed"),
                    "node_softnet_processed_total",
                    rate_per_sec=1500 + 1200 * busy_share,
                )
            if "node_softnet_dropped_total" in ctx.node_counter_set:
                set_counter(
                    cpu_doc,
                    (inst["instance"], cpu_id, "softnet_dropped"),
                    "node_softnet_dropped_total",
                    rate_per_sec=0.1 + 6 * mode_shares["iowait"],
                )
            if "node_softnet_times_squeezed_total" in ctx.node_counter_set:
                set_counter(
                    cpu_doc,
                    (inst["instance"], cpu_id, "softnet_squeezed"),
                    "node_softnet_times_squeezed_total",
                    rate_per_sec=0.05 + 2 * busy_share,
                )
            freq_base = 2.25e9 + cpu_id * 6.5e7
            freq_variation = 1.2e8 * math.sin((2 * math.pi * t_idx / max(total_points, 1)) + cpu_id * 0.5)
            if "node_cpu_scaling_frequency_hertz" in ctx.node_gauge_set:
                cpu_doc["node_cpu_scaling_frequency_hertz"] = round(max(1.4e9, freq_base + freq_variation), 3)
            if "node_cpu_scaling_frequency_max_hertz" in ctx.node_gauge_set:
                cpu_doc["node_cpu_scaling_frequency_max_hertz"] = 3.4e9
            if "node_cpu_scaling_frequency_min_hertz" in ctx.node_gauge_set:
                cpu_doc["node_cpu_scaling_frequency_min_hertz"] = 1.2e9
            if len(cpu_doc) > len(inst) + 2:
                lines.append(action)
                lines.append(json.dumps(cpu_doc))

        # Filesystem
        for dev, fs in [("sda", "/"), ("sda", "/home"), ("sdb", "/data"), ("nvme0n1p1", "/var")]:
            doc = {"@timestamp": ts_iso, **inst, "device": dev, "fstype": "ext4", "mountpoint": fs}
            usage_drift = 0.4 + 0.1 * math.sin(2 * math.pi * t_idx / total_points)
            noise = random.gauss(0, 0.02)
            used_frac = max(0.1, min(0.95, usage_drift + noise))
            avail = FS_SIZE * (1 - used_frac)
            doc["node_filesystem_size_bytes"] = float(FS_SIZE)
            doc["node_filesystem_avail_bytes"] = round(avail)
            doc["node_filesystem_free_bytes"] = round(avail + random.uniform(0, 1e9))
            doc["node_filesystem_files"] = 32768000.0
            doc["node_filesystem_files_free"] = round(32768000 * (1 - used_frac * 0.3))
            doc["node_filesystem_readonly"] = 0.0
            doc["node_filesystem_device_error"] = 0.0
            doc["node_filesystem_size"] = doc["node_filesystem_size_bytes"]
            doc["node_filesystem_free"] = doc["node_filesystem_free_bytes"]
            if "node_filesystem_avail" in ctx.node_gauge_set:
                doc["node_filesystem_avail"] = doc["node_filesystem_avail_bytes"]
            lines.append(action)
            lines.append(json.dumps(doc))

        # Disk
        for dev in ["sda", "sdb", "nvme0n1"]:
            doc = {"@timestamp": ts_iso, **inst, "device": dev}
            io_scale = 1.4 if dev == "nvme0n1" else (1.0 if dev == "sda" else 0.7)
            set_counter(doc, (inst["instance"], dev, "reads"), "node_disk_reads_completed_total", rate_per_sec=45 * io_scale)
            set_counter(doc, (inst["instance"], dev, "writes"), "node_disk_writes_completed_total", rate_per_sec=38 * io_scale)
            set_counter(doc, (inst["instance"], dev, "read_bytes"), "node_disk_read_bytes_total", rate_per_sec=2.4e6 * io_scale)
            set_counter(doc, (inst["instance"], dev, "write_bytes"), "node_disk_written_bytes_total", rate_per_sec=2.0e6 * io_scale)
            set_counter(doc, (inst["instance"], dev, "read_time"), "node_disk_read_time_seconds_total", rate_per_sec=0.08 * io_scale)
            set_counter(doc, (inst["instance"], dev, "write_time"), "node_disk_write_time_seconds_total", rate_per_sec=0.06 * io_scale)
            set_counter(doc, (inst["instance"], dev, "io_time"), "node_disk_io_time_seconds_total", rate_per_sec=0.18 * io_scale)
            set_counter(doc, (inst["instance"], dev, "weighted_time"), "node_disk_io_time_weighted_seconds_total", rate_per_sec=0.3 * io_scale)
            set_counter(doc, (inst["instance"], dev, "reads_merged"), "node_disk_reads_merged_total", rate_per_sec=3.5 * io_scale)
            set_counter(doc, (inst["instance"], dev, "writes_merged"), "node_disk_writes_merged_total", rate_per_sec=2.8 * io_scale)
            set_counter(doc, (inst["instance"], dev, "discards"), "node_disk_discards_completed_total", rate_per_sec=0.8 * io_scale)
            set_counter(doc, (inst["instance"], dev, "discards_merged"), "node_disk_discards_merged_total", rate_per_sec=0.2 * io_scale)
            set_counter(doc, (inst["instance"], dev, "discard_time"), "node_disk_discard_time_seconds_total", rate_per_sec=0.01 * io_scale)
            doc["node_disk_io_now"] = max(0.0, round(gauge_val(0.5 * io_scale, 4 * io_scale, hour, 0.25), 3))
            doc["node_disk_bytes_read"] = doc["node_disk_read_bytes_total"]
            doc["node_disk_bytes_written"] = doc["node_disk_written_bytes_total"]
            doc["node_disk_reads_completed"] = doc["node_disk_reads_completed_total"]
            doc["node_disk_io_time_ms"] = round(doc["node_disk_io_time_seconds_total"] * 1000, 3)
            doc["node_disk_sectors_read"] = round(doc["node_disk_read_bytes_total"] / 512, 3)
            lines.append(action)
            lines.append(json.dumps(doc))

        # Network
        for dev in ["eth0", "lo", "docker0"]:
            doc = {"@timestamp": ts_iso, **inst, "device": dev, "operstate": "up"}
            base_rate = 5e6 if dev == "eth0" else (1e5 if dev == "docker0" else 1e4)
            for direction, pfx in [("rx", "receive"), ("tx", "transmit")]:
                ck_b = (inst["instance"], dev, direction)
                if ck_b not in ctx.counter_state:
                    ctx.counter_state[ck_b] = random.uniform(1e9, 1e11)
                ctx.counter_state[ck_b] += counter_incr(base_rate, INTERVAL_SEC, hour)
                doc[f"node_network_{pfx}_bytes_total"] = round(ctx.counter_state[ck_b])
                doc[f"node_network_{pfx}_packets_total"] = round(ctx.counter_state[ck_b] / 1200)
                doc[f"node_network_{pfx}_errs_total"] = round(random.expovariate(2), 1)
                doc[f"node_network_{pfx}_drop_total"] = round(random.expovariate(5), 1)
            set_counter(doc, (inst["instance"], dev, "rx_compressed"), "node_network_receive_compressed_total", rate_per_sec=0.2 if dev == "eth0" else 0.01)
            set_counter(doc, (inst["instance"], dev, "tx_compressed"), "node_network_transmit_compressed_total", rate_per_sec=0.1 if dev == "eth0" else 0.01)
            set_counter(doc, (inst["instance"], dev, "rx_fifo"), "node_network_receive_fifo_total", rate_per_sec=0.05 if dev == "eth0" else 0.005)
            set_counter(doc, (inst["instance"], dev, "tx_fifo"), "node_network_transmit_fifo_total", rate_per_sec=0.03 if dev == "eth0" else 0.003)
            set_counter(doc, (inst["instance"], dev, "rx_frame"), "node_network_receive_frame_total", rate_per_sec=0.02 if dev == "eth0" else 0.002)
            set_counter(doc, (inst["instance"], dev, "rx_multicast"), "node_network_receive_multicast_total", rate_per_sec=3 if dev == "eth0" else 0.05)
            set_counter(doc, (inst["instance"], dev, "tx_carrier"), "node_network_transmit_carrier_total", rate_per_sec=0.01 if dev == "eth0" else 0.0)
            set_counter(doc, (inst["instance"], dev, "tx_colls"), "node_network_transmit_colls_total", rate_per_sec=0.02 if dev == "eth0" else 0.0)
            doc["node_network_up"] = 1.0
            doc["node_network_mtu_bytes"] = 1500.0
            doc["node_network_speed_bytes"] = 125000000.0
            doc["node_network_carrier"] = 1.0
            doc["node_network_transmit_queue_length"] = round(gauge_val(0.5 if dev == "eth0" else 0.05, 3, hour, 0.3))
            doc["node_arp_entries"] = max(0, round(gauge_val(12 if dev == "eth0" else 1, 8 if dev == "eth0" else 0.5, hour, 0.2)))
            doc["node_network_receive_bytes"] = doc["node_network_receive_bytes_total"]
            lines.append(action)
            lines.append(json.dumps(doc))

        if "node_power_supply_online" in ctx.node_gauge_set:
            for power_supply in ["PSU1", "PSU2"]:
                ps_doc = {"@timestamp": ts_iso, **inst, "power_supply": power_supply}
                ps_doc["node_power_supply_online"] = 1.0
                lines.append(action)
                lines.append(json.dumps(ps_doc))

        if "node_systemd_units" in ctx.node_gauge_set:
            systemd_profiles = [
                ("active", 820.0, 45.0),
                ("activating", 3.0, 2.0),
                ("deactivating", 1.5, 1.0),
                ("failed", 1.0, 0.8),
                ("inactive", 155.0, 20.0),
            ]
            node_offset = float(inst["nodename"][-1]) - 1.0
            cycle = max(total_points, 1)
            for idx, (state, base, spread) in enumerate(systemd_profiles):
                phase = (2 * math.pi * (t_idx / cycle)) + node_offset * 0.4 + idx * 0.7
                state_doc = {"@timestamp": ts_iso, **inst, "state": state}
                state_doc["node_systemd_units"] = round(
                    max(0.0, base + spread * math.sin(phase) + random.gauss(0, spread * 0.08)),
                    3,
                )
                lines.append(action)
                lines.append(json.dumps(state_doc))

        if "node_processes_state" in ctx.node_gauge_set:
            process_profiles = [
                ("running", 6.0, 2.0),
                ("sleeping", 235.0, 35.0),
                ("blocked", 2.0, 1.2),
                ("zombie", 0.3, 0.4),
                ("stopped", 1.0, 0.6),
            ]
            node_offset = float(inst["nodename"][-1]) - 1.0
            cycle = max(total_points, 1)
            for idx, (state, base, spread) in enumerate(process_profiles):
                phase = (2 * math.pi * (t_idx / cycle)) + node_offset * 0.5 + idx * 0.9
                proc_doc = {"@timestamp": ts_iso, **inst, "state": state}
                proc_doc["node_processes_state"] = round(
                    max(0.0, base + spread * math.sin(phase) + random.gauss(0, spread * 0.06)),
                    3,
                )
                lines.append(action)
                lines.append(json.dumps(proc_doc))

        if any(metric in ctx.node_gauge_set for metric in {
            "node_hwmon_chip_names",
            "node_hwmon_temp_celsius",
            "node_hwmon_temp_crit_alarm_celsius",
            "node_hwmon_temp_crit_celsius",
            "node_hwmon_temp_crit_hyst_celsius",
            "node_hwmon_temp_max_celsius",
        }):
            hwmon_specs = [
                {
                    "chip": "platform_coretemp_0",
                    "chip_name": "coretemp",
                    "sensor": "Package id 0",
                    "temp_base": 56.0,
                    "crit": 90.0,
                    "hyst": 86.0,
                    "max": 82.0,
                },
                {
                    "chip": "platform_acpitz_0",
                    "chip_name": "acpitz",
                    "sensor": "temp1",
                    "temp_base": 43.0,
                    "crit": 95.0,
                    "hyst": 90.0,
                    "max": 76.0,
                },
            ]
            node_offset = float(inst["nodename"][-1]) - 1.0
            cycle = max(total_points, 1)
            if "node_hwmon_chip_names" in ctx.node_gauge_set:
                for spec in hwmon_specs:
                    chip_doc = {
                        "@timestamp": ts_iso,
                        **inst,
                        "chip": spec["chip"],
                        "chip_name": spec["chip_name"],
                    }
                    chip_doc["node_hwmon_chip_names"] = 1.0
                    lines.append(action)
                    lines.append(json.dumps(chip_doc))
            for idx, spec in enumerate(hwmon_specs):
                phase = (2 * math.pi * (t_idx / cycle)) + node_offset * 0.35 + idx * 0.8
                temp = spec["temp_base"] + 5.5 * math.sin(phase) + random.gauss(0, 0.8)
                hw_doc = {
                    "@timestamp": ts_iso,
                    **inst,
                    "chip": spec["chip"],
                    "chip_name": spec["chip_name"],
                    "sensor": spec["sensor"],
                }
                if "node_hwmon_temp_celsius" in ctx.node_gauge_set:
                    hw_doc["node_hwmon_temp_celsius"] = round(temp, 3)
                if "node_hwmon_temp_crit_alarm_celsius" in ctx.node_gauge_set:
                    hw_doc["node_hwmon_temp_crit_alarm_celsius"] = 1.0 if temp >= spec["crit"] - 1 else 0.0
                if "node_hwmon_temp_crit_celsius" in ctx.node_gauge_set:
                    hw_doc["node_hwmon_temp_crit_celsius"] = spec["crit"]
                if "node_hwmon_temp_crit_hyst_celsius" in ctx.node_gauge_set:
                    hw_doc["node_hwmon_temp_crit_hyst_celsius"] = spec["hyst"]
                if "node_hwmon_temp_max_celsius" in ctx.node_gauge_set:
                    hw_doc["node_hwmon_temp_max_celsius"] = spec["max"]
                lines.append(action)
                lines.append(json.dumps(hw_doc))

        if any(metric in ctx.node_gauge_set for metric in {
            "node_scrape_collector_duration_seconds",
            "node_scrape_collector_success",
            "node_textfile_scrape_error",
        }):
            collector_profiles = [
                ("cpu", 0.065),
                ("filesystem", 0.090),
                ("meminfo", 0.032),
                ("netdev", 0.024),
                ("textfile", 0.008),
            ]
            node_offset = float(inst["nodename"][-1]) - 1.0
            cycle = max(total_points, 1)
            for idx, (collector, base_duration) in enumerate(collector_profiles):
                phase = (2 * math.pi * (t_idx / cycle)) + node_offset * 0.4 + idx * 0.9
                scrape_doc = {"@timestamp": ts_iso, **inst, "collector": collector}
                textfile_error = 1.0 if collector == "textfile" and inst["instance"] == "node2:9100" and (t_idx % 97 in {0, 1}) else 0.0
                if "node_scrape_collector_duration_seconds" in ctx.node_gauge_set:
                    scrape_doc["node_scrape_collector_duration_seconds"] = round(
                        max(0.001, base_duration + base_duration * 0.35 * math.sin(phase) + random.gauss(0, base_duration * 0.08)),
                        4,
                    )
                if "node_scrape_collector_success" in ctx.node_gauge_set:
                    scrape_doc["node_scrape_collector_success"] = 0.0 if textfile_error else 1.0
                if "node_textfile_scrape_error" in ctx.node_gauge_set:
                    scrape_doc["node_textfile_scrape_error"] = textfile_error if collector == "textfile" else 0.0
                lines.append(action)
                lines.append(json.dumps(scrape_doc))

        # Base metrics (memory, load, misc)
        doc = {"@timestamp": ts_iso, **inst}
        d = diurnal(hour)
        doc["up"] = 1.0 if random.random() > 0.002 else 0.0
        doc["node_load1"] = with_spike(gauge_val(1.5, 4.0, hour, 0.15), t_idx, total_points)
        doc["node_load5"] = gauge_val(1.2, 3.5, hour, 0.10)
        doc["node_load15"] = gauge_val(1.0, 3.0, hour, 0.05)

        mem_pressure = 0.4 + 0.3 * d + 0.1 * math.sin(2 * math.pi * t_idx / total_points * 3)
        mem_used = MEM_TOTAL * min(0.95, max(0.15, mem_pressure + random.gauss(0, 0.03)))
        doc["node_memory_MemTotal_bytes"] = float(MEM_TOTAL)
        doc["node_memory_MemAvailable_bytes"] = round(MEM_TOTAL - mem_used)
        doc["node_memory_MemFree_bytes"] = round((MEM_TOTAL - mem_used) * 0.35 + random.gauss(0, 1e8))
        doc["node_memory_Buffers_bytes"] = round(gauge_val(3e8, 2e8, hour))
        doc["node_memory_Cached_bytes"] = round(gauge_val(2e9, 1e9, hour))
        doc["node_memory_SwapTotal_bytes"] = float(SWAP_TOTAL)
        swap_used = SWAP_TOTAL * max(0, 0.05 * d + random.gauss(0, 0.01))
        doc["node_memory_SwapFree_bytes"] = round(SWAP_TOTAL - swap_used)
        doc["node_memory_SwapCached_bytes"] = round(swap_used * 0.1)
        doc["node_memory_Active_bytes"] = round(mem_used * 0.6 + random.gauss(0, 1e8))
        doc["node_memory_Inactive_bytes"] = round(mem_used * 0.25 + random.gauss(0, 5e7))
        doc["node_memory_Slab_bytes"] = round(gauge_val(2e8, 1e8, hour))
        doc["node_memory_SReclaimable_bytes"] = round(gauge_val(1.2e8, 5e7, hour))
        doc["node_memory_SUnreclaim_bytes"] = round(gauge_val(8e7, 3e7, hour))
        doc["node_memory_Committed_AS_bytes"] = round(mem_used * 1.2 + random.gauss(0, 2e8))
        doc["node_memory_CommitLimit_bytes"] = float(MEM_TOTAL + SWAP_TOTAL)
        doc["node_memory_Shmem_bytes"] = round(gauge_val(3e7, 2e7, hour))
        doc["node_memory_Mapped_bytes"] = round(gauge_val(2e8, 1e8, hour))
        doc["node_memory_VmallocTotal_bytes"] = 35184372087808.0
        doc["node_memory_VmallocUsed_bytes"] = round(gauge_val(3e7, 2e7, hour))
        doc["node_memory_PageTables_bytes"] = round(gauge_val(3e7, 1e7, hour))
        doc["node_memory_KernelStack_bytes"] = round(gauge_val(1.5e7, 5e6, hour))
        doc["node_memory_Dirty_bytes"] = round(gauge_val(2e6, 3e6, hour))
        doc["node_memory_Writeback_bytes"] = round(gauge_val(5e5, 5e5, hour))
        doc["node_memory_WritebackTmp_bytes"] = round(gauge_val(1e5, 1e5, hour))
        doc["node_memory_HardwareCorrupted_bytes"] = 0.0
        doc["node_memory_HugePages_Total"] = 0.0
        doc["node_memory_HugePages_Free"] = 0.0
        doc["node_memory_HugePages_Rsvd"] = 0.0
        doc["node_memory_HugePages_Surp"] = 0.0
        doc["node_memory_Hugepagesize_bytes"] = 2097152.0

        boot_ts = time.time() - DATA_HOURS * 3600 - 86400
        doc["node_boot_time_seconds"] = boot_ts
        doc["node_time_seconds"] = boot_ts + sec_since_start + DATA_HOURS * 3600
        doc["node_uname_info"] = 1.0
        doc["node_entropy_available_bits"] = gauge_val(3500, 500, hour)
        doc["node_filefd_allocated"] = gauge_val(2000, 3000, hour)
        doc["node_filefd_maximum"] = 65536.0
        doc["node_procs_running"] = max(1, round(gauge_val(2, 6, hour)))
        doc["node_procs_blocked"] = max(0, round(gauge_val(0.2, 1.5, hour)))
        doc["node_arp_entries"] = gauge_val(10, 10, hour)
        doc["node_nf_conntrack_entries"] = gauge_val(1500, 3000, hour)
        doc["node_nf_conntrack_entries_limit"] = 65536.0
        doc["node_netstat_Tcp_CurrEstab"] = round(gauge_val(20, 40, hour))
        doc["node_memory_MemAvailable"] = doc["node_memory_MemAvailable_bytes"]
        doc["node_memory_AnonHugePages_bytes"] = round(gauge_val(1e8, 5e7, hour))
        doc["node_memory_AnonPages_bytes"] = round(gauge_val(3e9, 8e8, hour))
        doc["node_memory_Bounce_bytes"] = 0.0
        doc["node_memory_Active_file_bytes"] = round(gauge_val(1.5e9, 4e8, hour))
        doc["node_memory_Active_anon_bytes"] = round(max(0.0, doc["node_memory_Active_bytes"] - doc["node_memory_Active_file_bytes"]))
        doc["node_memory_DirectMap1G_bytes"] = 34359738368.0
        doc["node_memory_DirectMap2M_bytes"] = 17179869184.0
        doc["node_memory_DirectMap4k_bytes"] = 1073741824.0
        doc["node_memory_Inactive_anon_bytes"] = round(gauge_val(7e8, 2e8, hour))
        doc["node_memory_Inactive_file_bytes"] = round(gauge_val(2e9, 5e8, hour))
        doc["node_memory_Mlocked_bytes"] = round(gauge_val(5e5, 2e5, hour))
        doc["node_memory_NFS_Unstable_bytes"] = 0.0
        doc["node_memory_Percpu_bytes"] = round(gauge_val(2e6, 5e5, hour))
        doc["node_memory_ShmemHugePages_bytes"] = 0.0
        doc["node_memory_ShmemPmdMapped_bytes"] = 0.0
        doc["node_memory_Unevictable_bytes"] = round(gauge_val(1e6, 5e5, hour))
        doc["node_memory_VmallocChunk_bytes"] = 35184370000000.0
        ck_ip_fwd = ("node", "ip_fwd")
        if ck_ip_fwd not in ctx.counter_state:
            ctx.counter_state[ck_ip_fwd] = random.uniform(0, 1e4)
        ctx.counter_state[ck_ip_fwd] += counter_incr(0.1, INTERVAL_SEC, hour)
        doc["node_netstat_Ip_Forwarding"] = round(ctx.counter_state[ck_ip_fwd])
        doc["node_sockstat_FRAG_inuse"] = round(gauge_val(0, 3, hour))
        doc["node_sockstat_TCP_alloc"] = round(gauge_val(50, 80, hour))
        doc["node_sockstat_TCP_mem_bytes"] = round(gauge_val(1e6, 5e5, hour))
        doc["node_sockstat_UDPLITE_inuse"] = 0.0
        ck_icmp_err = ("node", "icmp_err")
        if ck_icmp_err not in ctx.counter_state:
            ctx.counter_state[ck_icmp_err] = random.uniform(0, 1e4)
        ctx.counter_state[ck_icmp_err] += counter_incr(0.5, INTERVAL_SEC, hour)
        doc["node_netstat_Icmp_InErrors"] = round(ctx.counter_state[ck_icmp_err])
        doc["node_netstat_Icmp_InMsgs"] = round(ctx.counter_state[ck_icmp_err] * 10)
        ck_ip_oct = ("node", "ip_oct")
        if ck_ip_oct not in ctx.counter_state:
            ctx.counter_state[ck_ip_oct] = random.uniform(0, 1e9)
        ctx.counter_state[ck_ip_oct] += counter_incr(5000, INTERVAL_SEC, hour)
        doc["node_netstat_IpExt_InOctets"] = round(ctx.counter_state[ck_ip_oct])
        ck_tcp_ao = ("node", "tcp_ao")
        if ck_tcp_ao not in ctx.counter_state:
            ctx.counter_state[ck_tcp_ao] = random.uniform(0, 1e5)
        ctx.counter_state[ck_tcp_ao] += counter_incr(2, INTERVAL_SEC, hour)
        doc["node_netstat_Tcp_ActiveOpens"] = round(ctx.counter_state[ck_tcp_ao])
        doc["node_netstat_TcpExt_ListenOverflows"] = round(ctx.counter_state.get(ck_tcp_ao, 0) * 0.001)
        doc["node_netstat_TcpExt_SyncookiesFailed"] = round(ctx.counter_state.get(ck_tcp_ao, 0) * 0.0001)
        ck_udp = ("node", "udp_in")
        if ck_udp not in ctx.counter_state:
            ctx.counter_state[ck_udp] = random.uniform(0, 1e6)
        ctx.counter_state[ck_udp] += counter_incr(10, INTERVAL_SEC, hour)
        doc["node_netstat_Udp_InDatagrams"] = round(ctx.counter_state[ck_udp])
        doc["node_netstat_Udp_InErrors"] = round(ctx.counter_state[ck_udp] * 0.001)
        doc["cluster_autoscaler_last_activity"] = time.time() - random.uniform(0, 300)

        ck_ctx = (inst["instance"], "ctx")
        if ck_ctx not in ctx.counter_state:
            ctx.counter_state[ck_ctx] = random.uniform(1e9, 5e9)
        ctx.counter_state[ck_ctx] += counter_incr(5e4, INTERVAL_SEC, hour)
        doc["node_context_switches_total"] = round(ctx.counter_state[ck_ctx])
        doc["node_forks_total"] = round(ctx.counter_state[ck_ctx] / 100)
        doc["node_intr_total"] = round(ctx.counter_state[ck_ctx] * 2)
        if "node_cpu_core_throttles_total" in ctx.node_counter_set:
            ck_throttle = (inst["instance"], "cpu_core_throttles")
            if ck_throttle not in ctx.counter_state:
                ctx.counter_state[ck_throttle] = random.uniform(0, 1e6)
            ctx.counter_state[ck_throttle] += counter_incr(0.2 + 0.4 * diurnal(hour), INTERVAL_SEC, hour)
            doc["node_cpu_core_throttles_total"] = round(ctx.counter_state[ck_throttle], 3)

        for g in ctx.node_gauge_set:
            if (
                g == "node_power_supply_online"
                or g.startswith(dimensioned_prefixes)
                or g == "node_arp_entries"
                or g in explicit_labeled_metrics
            ):
                continue
            if g not in doc:
                doc[g] = gauge_val(500, 400, hour)
        for c in ctx.node_counter_set:
            if c.startswith(dimensioned_prefixes) or c in explicit_labeled_metrics:
                continue
            if c not in doc:
                ck = (inst["instance"], c)
                if ck not in ctx.counter_state:
                    ctx.counter_state[ck] = random.uniform(0, 1e7)
                ctx.counter_state[ck] += counter_incr(50, INTERVAL_SEC, hour)
                doc[c] = round(ctx.counter_state[ck], 3)
        lines.append(action)
        lines.append(json.dumps(doc))

    return lines


def _generate_prometheus_docs(ts_iso, hour, t_idx, action, ctx):
    """Prometheus self-monitoring metrics."""
    lines = []
    sec_since_start = t_idx * INTERVAL_SEC

    for inst in [{"job": "prometheus", "instance": "prom:9090"}]:
        doc = {"@timestamp": ts_iso, **inst, "up": 1.0}
        ck_pcpu = (inst["instance"], "pcpu")
        if ck_pcpu not in ctx.counter_state:
            ctx.counter_state[ck_pcpu] = random.uniform(100, 1000)
        ctx.counter_state[ck_pcpu] += counter_incr(0.05, INTERVAL_SEC, hour)
        doc["process_cpu_seconds_total"] = round(ctx.counter_state[ck_pcpu], 3)
        doc["process_resident_memory_bytes"] = round(gauge_val(1.2e8, 8e7, hour))
        doc["process_virtual_memory_bytes"] = round(gauge_val(7e8, 3e8, hour))
        doc["process_open_fds"] = round(gauge_val(25, 20, hour))
        doc["process_max_fds"] = 65536.0
        doc["process_start_time_seconds"] = time.time() - DATA_HOURS * 3600
        doc["scrape_duration_seconds"] = gauge_val(0.01, 0.03, hour, 0.3)
        if "go_goroutines" in ctx.prom_gauge_set:
            doc["go_goroutines"] = round(gauge_val(180, 60, hour, 0.15))
        doc["prometheus_build_info"] = 1.0
        doc["prometheus_engine_queries"] = round(gauge_val(10, 15, hour))
        doc["prometheus_notifications_queue_capacity"] = 100.0
        doc["prometheus_notifications_alertmanagers_discovered"] = 1.0
        doc["prometheus_tsdb_blocks_loaded"] = round(gauge_val(3, 3, hour))
        series_count = gauge_val(3000, 2000, hour)
        doc["prometheus_tsdb_head_series"] = round(series_count)
        doc["prometheus_tsdb_head_chunks"] = round(series_count * 2.2)
        doc["prometheus_tsdb_head_max_time"] = (time.time() - (DATA_HOURS * 3600 - sec_since_start)) * 1000
        doc["prometheus_tsdb_head_min_time"] = doc["prometheus_tsdb_head_max_time"] - 7200000
        doc["prometheus_target_interval_length_seconds"] = 15.0
        for pm in ctx.process_set:
            if pm not in doc:
                doc[pm] = gauge_val(500, 400, hour)
        for pg in ctx.prom_gauge_set:
            if pg in ctx.prom_labeled_metrics or pg in doc:
                continue
            doc[pg] = gauge_val(500, 300, hour)
        for pc in ctx.prom_counter_set:
            if pc in ctx.prom_labeled_metrics or pc in doc:
                continue
            ck = (inst["instance"], pc)
            if ck not in ctx.counter_state:
                ctx.counter_state[ck] = random.uniform(0, 1e7)
            ctx.counter_state[ck] += counter_incr(10, INTERVAL_SEC, hour)
            doc[pc] = round(ctx.counter_state[ck], 3)
        lines.append(action)
        lines.append(json.dumps(doc))

        if "prometheus_target_interval_length_seconds" in ctx.prom_gauge_set:
            for quantile, value in [("0.5", 14.8), ("0.9", 15.1), ("0.99", 15.3)]:
                q_doc = {"@timestamp": ts_iso, **inst, "quantile": quantile}
                q_doc["prometheus_target_interval_length_seconds"] = value
                lines.append(action)
                lines.append(json.dumps(q_doc))

        if "ALERTS" in ctx.gauges:
            alert_specs = [
                {"alertname": "HighCPUUsage", "severity": "warning", "alertstate": "firing", "value": 1.0},
                {"alertname": "PrometheusTargetDown", "severity": "critical", "alertstate": "pending", "value": 1.0},
            ]
            for alert in alert_specs:
                alert_doc = {"@timestamp": ts_iso, **inst, **alert}
                alert_doc["ALERTS"] = alert_doc.pop("value")
                lines.append(action)
                lines.append(json.dumps(alert_doc))

        for sl in ["prepare", "queue", "eval"]:
            sd = {"@timestamp": ts_iso, **inst, "slice": sl}
            sd["prometheus_engine_query_duration_seconds"] = gauge_val(0.05, 0.2, hour, 0.4)
            lines.append(action)
            lines.append(json.dumps(sd))

        for sj in ["consul", "marathon", "kubernetes"]:
            sd = {"@timestamp": ts_iso, **inst, "scrape_job": sj}
            ck = (inst["instance"], sj, "sync")
            if ck not in ctx.counter_state:
                ctx.counter_state[ck] = random.uniform(0, 1e4)
            ctx.counter_state[ck] += counter_incr(1, INTERVAL_SEC, hour)
            sd["prometheus_target_sync_length_seconds_count"] = round(ctx.counter_state[ck], 3)
            lines.append(action)
            lines.append(json.dumps(sd))

    return lines


_KUBE_PHASE_VALUES = ["Running", "Succeeded", "Failed", "Pending", "Unknown"]
_KUBE_CONDITION_VALUES = ["Ready", "DiskPressure", "MemoryPressure", "PIDPressure"]
_KUBE_PVC_PHASE_VALUES = ["Bound", "Pending", "Lost"]
_KUBE_REASON_VALUES = ["Evicted", "NodeLost", "UnexpectedAdmissionError"]


def _generate_k8s_docs(ts_iso, hour, action, ctx):
    """Kubernetes kube-state-metrics docs."""
    lines = []
    pod_records = [
        {
            "job": "kube-state-metrics",
            "instance": "kube-sm:8080",
            "namespace": "default",
            "node": "node1",
            "pod": "app-pod-abc",
            "container": "app",
            "container_id": "containerd://abc123",
            "persistentvolumeclaim": "data-app-pod-abc",
            "cluster": "prod-cluster",
            "qos_class": "Burstable",
            "phase": "Running",
        },
        {
            "job": "kube-state-metrics",
            "instance": "kube-sm:8080",
            "namespace": "kube-system",
            "node": "node2",
            "pod": "coredns-xyz",
            "container": "coredns",
            "container_id": "containerd://cde456",
            "persistentvolumeclaim": "cache-coredns-xyz",
            "cluster": "prod-cluster",
            "qos_class": "Guaranteed",
            "phase": "Running",
        },
        {
            "job": "kube-state-metrics",
            "instance": "kube-sm:8080",
            "namespace": "monitoring",
            "node": "node3",
            "pod": "prometheus-0",
            "container": "prometheus",
            "container_id": "containerd://prm789",
            "persistentvolumeclaim": "prometheus-db-prometheus-0",
            "cluster": "prod-cluster",
            "qos_class": "Burstable",
            "phase": "Pending",
        },
    ]
    node_records = [
        {"job": "kube-state-metrics", "instance": "kube-sm:8080", "cluster": "prod-cluster", "node": "node1"},
        {"job": "kube-state-metrics", "instance": "kube-sm:8080", "cluster": "prod-cluster", "node": "node2"},
        {"job": "kube-state-metrics", "instance": "kube-sm:8080", "cluster": "prod-cluster", "node": "node3"},
    ]
    pvc_records = [
        {"job": "kube-state-metrics", "instance": "kube-sm:8080", "cluster": "prod-cluster", "namespace": "default", "persistentvolumeclaim": "data-app-pod-abc", "active_phase": "Bound"},
        {"job": "kube-state-metrics", "instance": "kube-sm:8080", "cluster": "prod-cluster", "namespace": "monitoring", "persistentvolumeclaim": "prometheus-db-prometheus-0", "active_phase": "Pending"},
    ]
    job_records = [
        {"job": "kube-state-metrics", "instance": "kube-sm:8080", "cluster": "prod-cluster", "namespace": "default", "job_name": "batch-report", "active": 0.0, "failed": 0.0, "succeeded": 1.0, "completion_age_hours": 6},
        {"job": "kube-state-metrics", "instance": "kube-sm:8080", "cluster": "prod-cluster", "namespace": "monitoring", "job_name": "db-backup", "active": 0.0, "failed": 2.0, "succeeded": 0.0, "completion_age_hours": 72},
        {"job": "kube-state-metrics", "instance": "kube-sm:8080", "cluster": "prod-cluster", "namespace": "default", "job_name": "cleanup", "active": 1.0, "failed": 0.0, "succeeded": 0.0, "completion_age_hours": 1},
    ]
    node_condition_state = {
        "node1": {"Ready": "true", "DiskPressure": "false", "MemoryPressure": "false", "PIDPressure": "false"},
        "node2": {"Ready": "false", "DiskPressure": "true", "MemoryPressure": "false", "PIDPressure": "false"},
        "node3": {"Ready": "true", "DiskPressure": "false", "MemoryPressure": "true", "PIDPressure": "true"},
    }
    pod_reason_state = {
        "app-pod-abc": "Evicted",
        "coredns-xyz": "NodeLost",
        "prometheus-0": "UnexpectedAdmissionError",
    }

    all_kube_metrics = ctx.kube_counter_set | ctx.kube_gauge_set
    phase_metrics = {km for km in ctx.kube_gauge_set if "phase" in km}
    pvc_phase_metrics = {km for km in phase_metrics if "persistentvolumeclaim" in km}
    pod_phase_metrics = phase_metrics - pvc_phase_metrics
    condition_metrics = {km for km in ctx.kube_gauge_set if "condition" in km}
    reason_metrics = {
        km for km in ctx.kube_gauge_set
        if km.endswith("_reason") or "status_reason" in km
    }
    pod_container_info_metrics = {km for km in all_kube_metrics if km == "kube_pod_container_info"}
    pvc_info_metrics = {km for km in all_kube_metrics if km == "kube_persistentvolumeclaim_info"}
    pod_resource_metrics = {
        km for km in all_kube_metrics
        if km.startswith("kube_pod_container_resource_")
    }
    job_metrics = {km for km in all_kube_metrics if km.startswith("kube_job_status_")}
    node_resource_metrics = {
        km for km in all_kube_metrics
        if km.startswith("kube_node_status_")
        and km not in condition_metrics
    }
    special_metrics = (
        pvc_phase_metrics
        | pod_phase_metrics
        | condition_metrics
        | reason_metrics
        | pod_container_info_metrics
        | pvc_info_metrics
        | pod_resource_metrics
        | job_metrics
        | node_resource_metrics
    )
    normal_gauge_metrics = ctx.kube_gauge_set - special_metrics
    normal_counter_metrics = ctx.kube_counter_set - special_metrics

    def append_doc(doc: dict[str, object]) -> None:
        lines.append(action)
        lines.append(json.dumps(doc))

    def set_counter(doc: dict[str, object], key: tuple[object, ...], metric: str, rate: float = 0.01) -> None:
        ck = ("kube",) + key + (metric,)
        if ck not in ctx.counter_state:
            ctx.counter_state[ck] = random.uniform(0, 1e5)
        ctx.counter_state[ck] += counter_incr(rate, INTERVAL_SEC, hour)
        doc[metric] = round(ctx.counter_state[ck], 3)

    for pod in pod_records:
        base = {"@timestamp": ts_iso, **pod, "up": 1.0}
        doc = dict(base)
        for km in normal_gauge_metrics:
            if km in doc:
                continue
            if km == "kube_pod_info":
                doc[km] = 1.0
            elif km.endswith("_created") or km.endswith("_completion_time"):
                doc[km] = time.time() - random.uniform(300, DATA_HOURS * 3600)
            elif "status_replicas" in km:
                doc[km] = random.choice([1, 2, 3])
            elif "unschedulable" in km:
                doc[km] = 0.0
            elif "cpu" in km.lower():
                doc[km] = random.choice([1, 2, 4])
            elif "memory" in km.lower():
                doc[km] = gauge_val(4e9, 8e9, hour)
            elif "pods" in km:
                doc[km] = round(gauge_val(30, 60, hour))
            else:
                doc[km] = gauge_val(5, 5, hour)
        for km in normal_counter_metrics:
            rate = 0.002 if "restart" in km else 0.02
            set_counter(doc, (pod["pod"], pod["namespace"]), km, rate=rate)
        append_doc(doc)

        if pod_container_info_metrics:
            info_doc = dict(base)
            for km in pod_container_info_metrics:
                info_doc[km] = 1.0
            append_doc(info_doc)

        if pod_resource_metrics:
            cpu_request = 0.4 + 0.1 * (1 + pod_records.index(pod))
            cpu_limit = cpu_request * 1.5
            mem_request = 768 * 1024**2 + pod_records.index(pod) * 128 * 1024**2
            mem_limit = mem_request * 1.6
            for resource, request_value, limit_value in [
                ("cpu", cpu_request, cpu_limit),
                ("memory", mem_request, mem_limit),
            ]:
                resource_doc = dict(base)
                resource_doc["resource"] = resource
                for km in pod_resource_metrics:
                    if km.endswith("_requests_cpu_cores") and resource == "cpu":
                        resource_doc[km] = request_value
                    elif km.endswith("_requests_memory_bytes") and resource == "memory":
                        resource_doc[km] = request_value
                    elif km.endswith("_limits_cpu_cores") and resource == "cpu":
                        resource_doc[km] = limit_value
                    elif km.endswith("_limits_memory_bytes") and resource == "memory":
                        resource_doc[km] = limit_value
                    elif km.endswith("_resource_requests"):
                        resource_doc[km] = request_value
                    elif km.endswith("_resource_limits"):
                        resource_doc[km] = limit_value
                if any(metric in resource_doc for metric in pod_resource_metrics):
                    append_doc(resource_doc)

        if pod_phase_metrics:
            for phase in _KUBE_PHASE_VALUES:
                phase_doc = {
                    "@timestamp": ts_iso,
                    "job": pod["job"],
                    "instance": pod["instance"],
                    "namespace": pod["namespace"],
                    "node": pod["node"],
                    "pod": pod["pod"],
                    "cluster": pod["cluster"],
                    "phase": phase,
                    "up": 1.0,
                }
                for km in pod_phase_metrics:
                    phase_doc[km] = 1.0 if phase == pod["phase"] else 0.0
                append_doc(phase_doc)

        if reason_metrics:
            active_reason = pod_reason_state[pod["pod"]]
            for reason in _KUBE_REASON_VALUES:
                reason_doc = {
                    "@timestamp": ts_iso,
                    "job": pod["job"],
                    "instance": pod["instance"],
                    "namespace": pod["namespace"],
                    "node": pod["node"],
                    "pod": pod["pod"],
                    "cluster": pod["cluster"],
                    "reason": reason,
                    "up": 1.0,
                }
                for km in reason_metrics:
                    reason_doc[km] = 1.0 if reason == active_reason else 0.0
                append_doc(reason_doc)

    if node_resource_metrics:
        resource_values = {
            "pods": {"kube_node_status_allocatable": 30.0, "kube_node_status_capacity": 32.0},
            "cpu": {"kube_node_status_allocatable": 8.0, "kube_node_status_capacity": 8.0},
            "memory": {"kube_node_status_allocatable": 28 * 1024**3, "kube_node_status_capacity": 32 * 1024**3},
        }
        for node in node_records:
            for resource, values in resource_values.items():
                resource_doc = {"@timestamp": ts_iso, **node, "resource": resource, "up": 1.0}
                for km in node_resource_metrics:
                    if km in values:
                        resource_doc[km] = values[km]
                if any(metric in resource_doc for metric in node_resource_metrics):
                    append_doc(resource_doc)

    if condition_metrics:
        for node in node_records:
            for condition in _KUBE_CONDITION_VALUES:
                active_status = node_condition_state[node["node"]][condition]
                for status in ["true", "false"]:
                    condition_doc = {
                        "@timestamp": ts_iso,
                        **node,
                        "condition": condition,
                        "status": status,
                        "up": 1.0,
                    }
                    for km in condition_metrics:
                        condition_doc[km] = 1.0 if status == active_status else 0.0
                    append_doc(condition_doc)

    for pvc in pvc_records:
        pvc_base = {k: v for k, v in pvc.items() if k != "active_phase"}
        if pvc_info_metrics:
            pvc_info_doc = {"@timestamp": ts_iso, **pvc_base, "up": 1.0}
            for km in pvc_info_metrics:
                pvc_info_doc[km] = 1.0
            append_doc(pvc_info_doc)

        if pvc_phase_metrics:
            for phase in _KUBE_PVC_PHASE_VALUES:
                pvc_doc = {"@timestamp": ts_iso, **pvc_base, "phase": phase, "up": 1.0}
                for km in pvc_phase_metrics:
                    pvc_doc[km] = 1.0 if phase == pvc["active_phase"] else 0.0
                append_doc(pvc_doc)

    if job_metrics:
        for job_record in job_records:
            job_base = {k: v for k, v in job_record.items() if k != "completion_age_hours"}
            job_doc = {"@timestamp": ts_iso, **job_base, "up": 1.0}
            completion_ts = time.time() - job_record["completion_age_hours"] * 3600
            for km in job_metrics:
                if km == "kube_job_status_active":
                    job_doc[km] = job_record["active"]
                elif km == "kube_job_status_failed":
                    job_doc[km] = job_record["failed"]
                elif km == "kube_job_status_succeeded":
                    job_doc[km] = job_record["succeeded"]
                elif km == "kube_job_status_completion_time":
                    job_doc[km] = completion_ts
            append_doc(job_doc)

    return lines


def _generate_otel_docs(ts_iso, hour, action, ctx):
    """OpenTelemetry Collector self-telemetry counters."""
    lines = []
    for inst in [{"job": "otel-collector", "instance": "otel:8888",
                  "processor": "batch", "receiver": "otlp", "exporter": "otlp"}]:
        doc = {"@timestamp": ts_iso, **inst, "up": 1.0}
        for om in ctx.otel_set:
            ck = (inst["instance"], om)
            if ck not in ctx.counter_state:
                ctx.counter_state[ck] = random.uniform(0, 1e5)
            ctx.counter_state[ck] += counter_incr(30, INTERVAL_SEC, hour)
            doc[om] = round(ctx.counter_state[ck], 1)
        lines.append(action)
        lines.append(json.dumps(doc))
    return lines


def _generate_windows_docs(ts_iso, hour, action, ctx):
    """Synthetic Windows exporter metrics used by the mixed Linux/Windows dashboards."""
    if not ctx.windows_counter_set and not ctx.windows_gauge_set:
        return []

    lines = []
    windows_instances = [
        {"job": "windows-exporter", "instance": "windows-1:9182", "cluster": "prod-cluster", "node": "win-node-1"},
        {"job": "windows-exporter", "instance": "windows-2:9182", "cluster": "prod-cluster", "node": "win-node-2"},
    ]
    nic_names = ["Ethernet0", "Ethernet1", "vEthernet (Virtual Switch)"]
    windows_containers = [
        {
            "job": "windows-exporter",
            "instance": "windows-1:9182",
            "cluster": "prod-cluster",
            "node": "win-node-1",
            "namespace": "default",
            "pod": "app-pod-abc",
            "container": "app",
            "container_id": "containerd://abc123",
            "image": "mcr.microsoft.com/windows/servercore:ltsc2022",
        },
        {
            "job": "windows-exporter",
            "instance": "windows-2:9182",
            "cluster": "prod-cluster",
            "node": "win-node-2",
            "namespace": "monitoring",
            "pod": "prometheus-0",
            "container": "prometheus",
            "container_id": "containerd://prm789",
            "image": "mcr.microsoft.com/windows/nanoserver:ltsc2022",
        },
    ]

    def append_doc(doc: dict[str, object]) -> None:
        lines.append(action)
        lines.append(json.dumps(doc))

    def set_counter(doc: dict[str, object], key: tuple[object, ...], metric: str, rate: float) -> None:
        ck = ("windows",) + key + (metric,)
        if ck not in ctx.counter_state:
            ctx.counter_state[ck] = random.uniform(0, 1e6)
        ctx.counter_state[ck] += counter_incr(rate, INTERVAL_SEC, hour)
        doc[metric] = round(ctx.counter_state[ck], 3)

    for inst in windows_instances:
        if "windows_cpu_time_total" in ctx.windows_counter_set:
            for core in range(4):
                mode_shares = _windows_cpu_mode_shares(hour, core)
                for mode in ["idle", "user", "privileged"]:
                    cpu_doc = {"@timestamp": ts_iso, **inst, "core": str(core), "mode": mode}
                    set_counter(
                        cpu_doc,
                        (inst["instance"], core, mode),
                        "windows_cpu_time_total",
                        rate=mode_shares[mode],
                    )
                    append_doc(cpu_doc)

        memory_doc = {"@timestamp": ts_iso, **inst}
        if "windows_os_visible_memory_bytes" in ctx.windows_gauge_set:
            memory_doc["windows_os_visible_memory_bytes"] = 32 * 1024**3
        if "windows_memory_available_bytes" in ctx.windows_gauge_set:
            memory_doc["windows_memory_available_bytes"] = round(gauge_val(11 * 1024**3, 3 * 1024**3, hour))
        if "windows_memory_cache_bytes" in ctx.windows_gauge_set:
            memory_doc["windows_memory_cache_bytes"] = round(gauge_val(2 * 1024**3, 0.6 * 1024**3, hour))
        if any(metric in memory_doc for metric in ctx.windows_gauge_set):
            append_doc(memory_doc)

        for nic in nic_names:
            net_doc = {"@timestamp": ts_iso, **inst, "nic": nic}
            if "windows_net_bytes_received_total" in ctx.windows_counter_set:
                set_counter(net_doc, (inst["instance"], nic, "rx"), "windows_net_bytes_received_total", rate=2.4e6)
            if "windows_net_bytes_sent_total" in ctx.windows_counter_set:
                set_counter(net_doc, (inst["instance"], nic, "tx"), "windows_net_bytes_sent_total", rate=1.8e6)
            if "windows_net_packets_received_discarded_total" in ctx.windows_counter_set:
                set_counter(net_doc, (inst["instance"], nic, "rx_disc"), "windows_net_packets_received_discarded_total", rate=0.02)
            if "windows_net_packets_outbound_discarded_total" in ctx.windows_counter_set:
                set_counter(net_doc, (inst["instance"], nic, "tx_disc"), "windows_net_packets_outbound_discarded_total", rate=0.015)
            if any(metric in net_doc for metric in ctx.windows_counter_set | ctx.windows_gauge_set):
                append_doc(net_doc)

    for container in windows_containers:
        container_doc = {"@timestamp": ts_iso, **container}
        if "windows_container_memory_usage_commit_bytes" in ctx.windows_gauge_set:
            container_doc["windows_container_memory_usage_commit_bytes"] = round(gauge_val(900 * 1024**2, 250 * 1024**2, hour))
        if "windows_container_cpu_usage_seconds_total" in ctx.windows_counter_set:
            set_counter(container_doc, (container["container_id"], "cpu"), "windows_container_cpu_usage_seconds_total", rate=0.05)
        if "windows_container_network_receive_bytes_total" in ctx.windows_counter_set:
            set_counter(container_doc, (container["container_id"], "rx"), "windows_container_network_receive_bytes_total", rate=6e5)
        if "windows_container_network_transmit_bytes_total" in ctx.windows_counter_set:
            set_counter(container_doc, (container["container_id"], "tx"), "windows_container_network_transmit_bytes_total", rate=4e5)
        if any(metric in container_doc for metric in ctx.windows_counter_set | ctx.windows_gauge_set):
            append_doc(container_doc)

    return lines


def _generate_gated_service_docs(ts_iso, hour, action, ctx):
    """Generic emitter for additional services whose metrics were extracted
    from compiled dashboards.  Only emits data for services that have at
    least one matching metric in the extracted set."""
    lines = []
    all_set = ctx.counters | ctx.gauges
    counter_lookup = ctx.counters

    for svc_key, metric_names in ctx.gated_services.items():
        if not metric_names or svc_key == "windows":
            continue
        for inst in GATED_SERVICE_INSTANCES.get(svc_key, []):
            doc = {"@timestamp": ts_iso, **inst, "up": 1.0}
            for mn in metric_names:
                if mn in counter_lookup:
                    ck = (inst["instance"], mn)
                    if ck not in ctx.counter_state:
                        ctx.counter_state[ck] = random.uniform(0, 1e7)
                    ctx.counter_state[ck] += counter_incr(10, INTERVAL_SEC, hour)
                    doc[mn] = round(ctx.counter_state[ck], 3)
                else:
                    doc[mn] = gauge_val(500, 400, hour)
            lines.append(action)
            lines.append(json.dumps(doc))

    return lines


def generate_log_batch(ts_iso, t_idx):
    """Generate a small synthetic logs dataset for translated logs-* panels."""
    action = json.dumps({"create": {"_index": LOGS_INDEX_NAME}})
    level = "error" if t_idx % 17 == 0 else "info"
    load_metric = "node_load1" if t_idx % 2 == 0 else "node_load5"
    return [
        action,
        json.dumps(
            {
                "@timestamp": ts_iso,
                "__name__": load_metric,
                "message": f"{load_metric} sample={round(0.5 + (t_idx % 10) / 10, 2)}",
                "namespace": "monitoring",
                "instance": "node1:9100",
                "service.instance.id": "node1:9100",
                "k8s.namespace.name": "monitoring",
                "k8s.pod.name": "node-exporter-7xk2p",
            }
        ),
        action,
        json.dumps(
            {
                "@timestamp": ts_iso,
                "message": f"{level} sample log from synthetic loki stream #{t_idx}",
                "namespace": "default",
                "instance": "goapp:8080",
                "service.instance.id": "goapp:8080",
                "k8s.namespace.name": "default",
                "k8s.pod.name": "goapp-5f8c9d7b4-" + ["abc12", "def34", "ghi56"][t_idx % 3],
            }
        ),
    ]


# ---------------------------------------------------------------------------
# Batch dispatcher
# ---------------------------------------------------------------------------

def generate_batch(ts_iso, hour, t_idx, total_points, ctx):
    """Generate all documents for a single timestamp."""
    action = json.dumps({"create": {"_index": INDEX_NAME}})
    lines = []
    lines.extend(_generate_node_docs(ts_iso, hour, t_idx, total_points, action, ctx))
    lines.extend(_generate_prometheus_docs(ts_iso, hour, t_idx, action, ctx))
    lines.extend(_generate_k8s_docs(ts_iso, hour, action, ctx))
    lines.extend(_generate_otel_docs(ts_iso, hour, action, ctx))
    lines.extend(_generate_windows_docs(ts_iso, hour, action, ctx))
    lines.extend(_generate_gated_service_docs(ts_iso, hour, action, ctx))
    return serialize_dashboard_docs(lines)


# ---------------------------------------------------------------------------
# Bulk ingest
# ---------------------------------------------------------------------------

def _ingest_one_bulk(payload_bytes):
    """Send a single pre-encoded NDJSON payload. Returns (ok, err, sample)."""
    result = es_request("POST", "/_bulk", body=payload_bytes, content_type="application/x-ndjson")
    ok = err = 0
    sample = None
    if isinstance(result, dict):
        items = result.get("items", [])
        err = sum(1 for it in items if it.get("create", {}).get("error"))
        ok = len(items) - err
        if err:
            for it in items:
                e = it.get("create", {}).get("error")
                if e:
                    sample = e.get("reason", "")[:140]
                    break
    return ok, err, sample


def ingest_bulk(lines, stats):
    """Send a list of NDJSON lines to the bulk API. Updates stats dict in-place."""
    payload = ("\n".join(lines) + "\n").encode()
    ok, err, sample = _ingest_one_bulk(payload)
    stats["ok"] += ok
    stats["err"] += err
    if sample and stats["err_samples"] < 3:
        stats["err_samples"] += 1
        print(f"\n   Error sample: {sample}")


# ---------------------------------------------------------------------------
# Metric extraction helper
# ---------------------------------------------------------------------------

def auto_extract_metrics(yaml_dir: str) -> dict:
    """Run extract_dashboard_metrics inline to auto-generate the metrics JSON."""
    from pathlib import Path
    extract_script = Path(__file__).parent / "extract_dashboard_metrics.py"
    if not extract_script.exists():
        raise FileNotFoundError(f"Cannot find {extract_script}")

    import subprocess
    output_path = "/tmp/dashboard_metrics.json"
    result = subprocess.run(
        [sys.executable, str(extract_script), yaml_dir, output_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  Extraction failed: {result.stderr}")
        raise RuntimeError("Metric extraction failed")
    print(result.stdout)
    with open(output_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    yaml_dir = os.environ.get("DASHBOARD_YAML_DIR", "")
    if yaml_dir:
        print(f"Auto-extracting metrics from {yaml_dir}...")
        data = auto_extract_metrics(yaml_dir)
    elif os.path.exists("/tmp/dashboard_metrics.json"):
        with open("/tmp/dashboard_metrics.json") as f:
            data = json.load(f)
    else:
        print("ERROR: No /tmp/dashboard_metrics.json and DASHBOARD_YAML_DIR not set.")
        print("  Run: python3 scripts/extract_dashboard_metrics.py <yaml_dir>")
        print("  Or:  DASHBOARD_YAML_DIR=<yaml_dir> python3 scripts/setup_serverless_data.py")
        sys.exit(1)

    extracted_counters = set(data.get("counters", []))
    extracted_gauges = set(data.get("gauges", []))
    extracted_all = extracted_counters | extracted_gauges

    counters = sorted((extracted_counters | EXTRA_COUNTER_METRICS) - EXTRA_GAUGE_METRICS)
    gauges = sorted((extracted_gauges | EXTRA_GAUGE_METRICS) - set(counters))

    all_metrics = set(counters) | set(gauges)

    # --- Preflight: detect metrics the dashboards need but the generator won't produce ---
    missing = extracted_all - all_metrics
    if missing:
        print(f"\n  WARNING: {len(missing)} dashboard metrics not in generator:")
        for m in sorted(missing):
            print(f"    MISSING: {m}")
        print("  Add them to EXTRA_COUNTER_METRICS or EXTRA_GAUGE_METRICS.\n")

    # --- Preflight: detect counter/gauge type conflicts ---
    type_conflicts = extracted_counters & set(gauges)
    if type_conflicts:
        print(f"\n  WARNING: {len(type_conflicts)} metrics used with RATE/IRATE but mapped as gauge:")
        for m in sorted(type_conflicts):
            print(f"    WRONG TYPE: {m} (needs counter)")
        print("  Move them from EXTRA_GAUGE_METRICS to EXTRA_COUNTER_METRICS.\n")

    # --- Preflight: data_stream.dataset consistency ---
    ds_dataset = INDEX_NAME.split("-")[1] if "-" in INDEX_NAME else ""
    print(f"Metrics: {len(counters)} counters + {len(gauges)} gauges = {len(counters) + len(gauges)} total")
    print(f"data_stream.dataset = \"{ds_dataset}\" (from INDEX_NAME=\"{INDEX_NAME}\")")

    preflight_errors = len(missing) + len(type_conflicts)
    if preflight_errors and not os.environ.get("SKIP_PREFLIGHT"):
        print(f"\n  PREFLIGHT FAILED: {preflight_errors} issue(s) detected.")
        print(f"  Fix the issues above or set SKIP_PREFLIGHT=1 to proceed anyway.")
        sys.exit(1)
    elif preflight_errors:
        print(f"  SKIP_PREFLIGHT set — continuing despite {preflight_errors} issue(s).")

    gated_services: dict[str, set[str]] = {}
    for svc_key, prefixes in GATED_SERVICE_PREFIXES.items():
        gated_services[svc_key] = {
            m for m in all_metrics
            if any(m.startswith(p) for p in prefixes)
        }
    svc_count = sum(1 for v in gated_services.values() if v)
    svc_metrics = sum(len(v) for v in gated_services.values())
    print(f"Gated services: {svc_count} active families, {svc_metrics} metrics")

    prom_set = {m for m in all_metrics
                if m.startswith(("prometheus_", "go_memstats_", "tsdb_", "go_", "net_")) or m == "ALERTS"}

    ctx = GeneratorContext(
        counters=set(counters),
        gauges=set(gauges),
        node_counter_set={m for m in counters if m.startswith("node_")},
        node_gauge_set={m for m in gauges if m.startswith("node_")},
        kube_counter_set={m for m in counters if m.startswith("kube_")},
        kube_gauge_set={m for m in gauges if m.startswith("kube_")},
        container_set={m for m in all_metrics if m.startswith("container_")},
        otel_set={m for m in all_metrics if m.startswith("otelcol_")},
        prom_counter_set={m for m in counters if m in prom_set},
        prom_gauge_set={m for m in gauges if m in prom_set},
        process_set={m for m in all_metrics if m.startswith("process_")},
        windows_counter_set={m for m in counters if m.startswith("windows_")},
        windows_gauge_set={m for m in gauges if m.startswith("windows_")},
        prom_labeled_metrics={
            "ALERTS",
            "prometheus_engine_query_duration_seconds",
            "prometheus_target_interval_length_seconds",
            "prometheus_target_sync_length_seconds_count",
        },
        gated_services=gated_services,
    )

    # --- 1. Cleanup ---
    print("\n1. Cleaning up old data...")
    es_request("DELETE", "/_data_stream/metrics-prometheus-default")
    es_request("DELETE", "/_data_stream/logs-generic-default")
    es_request("DELETE", "/_index_template/dashboard-metrics")
    es_request("DELETE", "/_index_template/dashboard-logs")

    # --- 2. Template ---
    print("\n2. Creating TSDB index template (look_back_time=7d)...")
    template = build_template(counters, gauges)
    template["template"]["settings"]["index.look_back_time"] = "7d"
    result = es_request("PUT", "/_index_template/dashboard-metrics", template)
    if result.get("acknowledged"):
        print("   Template created successfully")
    else:
        print(f"   Template creation failed: {result}")
        sys.exit(1)

    logs_template = build_logs_template()
    result = es_request("PUT", "/_index_template/dashboard-logs", logs_template)
    if result.get("acknowledged"):
        print("   Logs template created successfully")
    else:
        print(f"   Logs template creation failed: {result}")
        sys.exit(1)

    # --- 3. Data streams ---
    print(f"\n3. Creating data stream {INDEX_NAME}...")
    ensure_time_series_data_stream(INDEX_NAME)
    print(f"   Creating logs data stream {LOGS_INDEX_NAME}...")
    ensure_time_series_data_stream(LOGS_INDEX_NAME, expected_index_mode="")

    # --- 4. Generate and stream-ingest (concurrent) ---
    now = datetime.datetime.now(datetime.timezone.utc)
    total_points = int(DATA_HOURS * 3600 // INTERVAL_SEC)
    print(f"\n4. Generating {DATA_HOURS}h of data at {INTERVAL_SEC}s intervals "
          f"({total_points} timestamps, {BULK_WORKERS} workers, batch={BATCH_DOC_LIMIT})...")

    random.seed(42)
    stats = {"ok": 0, "err": 0, "err_samples": 0}
    batch_buf: list[str] = []
    pending_payloads: list[bytes] = []
    t0 = time.time()

    def _flush_payloads(payloads):
        """Send all queued payloads concurrently."""
        if not payloads:
            return
        with ThreadPoolExecutor(max_workers=BULK_WORKERS) as pool:
            futures = [pool.submit(_ingest_one_bulk, p) for p in payloads]
            for fut in as_completed(futures):
                ok, err, sample = fut.result()
                stats["ok"] += ok
                stats["err"] += err
                if sample and stats["err_samples"] < 3:
                    stats["err_samples"] += 1
                    print(f"\n   Error sample: {sample}")

    for t_idx in range(total_points):
        ts_dt = now - datetime.timedelta(seconds=(total_points - t_idx) * INTERVAL_SEC)
        ts_iso = ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        hour = ts_dt.hour + ts_dt.minute / 60.0

        batch_buf.extend(generate_batch(ts_iso, hour, t_idx, total_points, ctx))
        batch_buf.extend(generate_log_batch(ts_iso, t_idx))

        if len(batch_buf) >= BATCH_DOC_LIMIT * 2:
            pending_payloads.append(("\n".join(batch_buf) + "\n").encode())
            batch_buf = []

        if len(pending_payloads) >= BULK_WORKERS:
            _flush_payloads(pending_payloads)
            pending_payloads = []
            elapsed = time.time() - t0
            pct = (t_idx + 1) / total_points * 100
            rate = stats["ok"] / max(elapsed, 1)
            eta = (total_points - t_idx - 1) / max(t_idx + 1, 1) * elapsed
            sys.stdout.write(
                f"\r   [{pct:5.1f}%] {stats['ok']:,} ok, {stats['err']} err | "
                f"{rate:.0f} docs/s | ETA {eta/60:.1f}m   "
            )
            sys.stdout.flush()

    if batch_buf:
        pending_payloads.append(("\n".join(batch_buf) + "\n").encode())
    _flush_payloads(pending_payloads)

    elapsed = time.time() - t0
    print(f"\n   Done: {stats['ok']:,} docs ingested, {stats['err']} errors in {elapsed:.0f}s")

    # --- 5. Verify ---
    print("\n5. Verifying data...")
    time.sleep(2)
    result = es_request("POST", "/_query", {
        "query": "FROM metrics-prometheus-* | STATS c = COUNT(*) | LIMIT 1"
    })
    if result.get("values"):
        count = result["values"][0][0]
        print(f"   Total documents: {count:,}")

    result = es_request("POST", "/_query", {
        "query": "FROM metrics-prometheus-* | STATS mn = MIN(@timestamp), mx = MAX(@timestamp) | LIMIT 1"
    })
    if result.get("values"):
        print(f"   Time range: {result['values'][0][0]} → {result['values'][0][1]}")

    # --- 6. Test PROMQL ---
    print("\n6. Testing native PROMQL...")
    test_queries = [
        ("up", "PROMQL index=metrics-prometheus-* step=5m (up) | LIMIT 5"),
        ("rate(cpu[5m])", "PROMQL index=metrics-prometheus-* step=5m (rate(node_cpu_seconds_total[5m])) | LIMIT 5"),
        ("avg by (job)(load)", "PROMQL index=metrics-prometheus-* step=5m (avg by (job) (node_load1)) | LIMIT 5"),
        ("memory %", "PROMQL index=metrics-prometheus-* step=5m ((node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100) | LIMIT 5"),
        ("increase(ctx[1h])", "PROMQL index=metrics-prometheus-* step=5m (increase(node_context_switches_total[1h])) | LIMIT 5"),
        ("go goroutines", "PROMQL index=metrics-prometheus-* step=5m (go_goroutines) | LIMIT 5"),
    ]
    for name, query in test_queries:
        result = es_request("POST", "/_query", {"query": query})
        if result.get("error"):
            print(f"   FAIL {name}: {result['error'].get('reason', '')[:100]}")
        else:
            rows = len(result.get("values", []))
            cols = [c["name"] for c in result.get("columns", [])]
            print(f"   OK   {name}: {rows} rows, cols={cols}")

    print("\nSetup complete!")


if __name__ == "__main__":
    main()
