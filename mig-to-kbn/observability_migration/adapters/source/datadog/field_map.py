"""Configurable field name mapping from Datadog metric/tag names to Elasticsearch fields.

Datadog uses dotted metric names (system.cpu.user) and tag keys (host, env, service).
Elasticsearch field names depend on the ingestion pipeline:
    - OTel Collector: system.cpu.utilization, host.name, deployment.environment
    - Elastic Agent / Metricbeat: system.cpu.user.pct, host.name
    - Custom: arbitrary

This module provides pluggable mapping profiles.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .extension_schema import FieldMapProfileModel, validate_field_profile_payload
from observability_migration.core.verification.field_capabilities import (
    FieldCapability,
    fetch_field_capabilities,
    has_conflicting_types,
    is_aggregatable_field,
    is_numeric_field,
    is_searchable_field,
    is_text_like_field,
)


@dataclass
class FieldMapProfile:
    """A mapping profile from Datadog names to Elasticsearch names."""

    name: str = "default"
    metric_index: str = "metrics-*"
    logs_index: str = "logs-*"
    log_index_map: dict[str, str] = field(default_factory=dict)
    timestamp_field: str = "@timestamp"
    metrics_dataset_filter: str = ""
    logs_dataset_filter: str = ""

    metric_map: dict[str, str] = field(default_factory=dict)
    tag_map: dict[str, str] = field(default_factory=dict)
    field_caps: dict[str, FieldCapability] = field(default_factory=dict)
    metric_field_caps: dict[str, FieldCapability] = field(default_factory=dict)
    log_field_caps: dict[str, FieldCapability] = field(default_factory=dict)

    metric_prefix: str = ""
    metric_suffix: str = ""
    tag_prefix: str = ""

    def map_metric(self, dd_metric: str) -> str:
        if dd_metric in self.metric_map:
            return self.metric_map[dd_metric]
        es_name = dd_metric.replace(".", "_")
        if self.metric_prefix:
            es_name = f"{self.metric_prefix}{es_name}"
        if self.metric_suffix:
            es_name = f"{es_name}{self.metric_suffix}"
        return es_name

    def map_tag(self, dd_tag: str, context: str = "") -> str:
        """Map a Datadog tag to an ES field.

        Args:
            context: "metric" or "log" — used to avoid mapping tags like
                     "status" to log-only fields (log.level) in metric queries.
        """
        if dd_tag in self.tag_map:
            mapped = self.tag_map[dd_tag]
            if context == "metric" and mapped in _LOG_ONLY_FIELDS:
                return dd_tag
            return mapped
        if self.tag_prefix:
            return f"{self.tag_prefix}{dd_tag}"
        return dd_tag

    def map_log_field(self, dd_field: str) -> str:
        """Map a Datadog log attribute (@field) to an ES field."""
        if dd_field in self.tag_map:
            return self.tag_map[dd_field]
        return dd_field

    def map_log_index(self, dd_index: str) -> str:
        """Map a Datadog log index name to an ES index pattern."""
        return self.log_index_map.get(dd_index, "")

    def field_capability(self, field_name: str, context: str = "") -> FieldCapability | None:
        if context == "metric":
            return self.metric_field_caps.get(field_name) or self.field_caps.get(field_name)
        if context == "log":
            return self.log_field_caps.get(field_name) or self.field_caps.get(field_name)
        return (
            self.field_caps.get(field_name)
            or self.metric_field_caps.get(field_name)
            or self.log_field_caps.get(field_name)
        )

    def is_numeric_field(self, field_name: str, context: str = "") -> bool:
        return is_numeric_field(self.field_capability(field_name, context=context))

    def is_searchable_field(self, field_name: str, context: str = "") -> bool:
        return is_searchable_field(self.field_capability(field_name, context=context))

    def is_aggregatable_field(self, field_name: str, context: str = "") -> bool:
        return is_aggregatable_field(self.field_capability(field_name, context=context))

    def is_text_like_field(self, field_name: str, context: str = "") -> bool:
        return is_text_like_field(self.field_capability(field_name, context=context))

    def has_conflicting_types(self, field_name: str, context: str = "") -> bool:
        return has_conflicting_types(self.field_capability(field_name, context=context))

    def load_live_field_capabilities(self, es_url: str, es_api_key: str = "") -> dict[str, int]:
        """Populate field capabilities from the live target cluster."""
        metric_caps = fetch_field_capabilities(es_url, self.metric_index, es_api_key=es_api_key)
        log_caps = {}
        if self.logs_index:
            if self.logs_index == self.metric_index:
                log_caps = metric_caps
            else:
                log_caps = fetch_field_capabilities(es_url, self.logs_index, es_api_key=es_api_key)
        self.metric_field_caps = metric_caps
        self.log_field_caps = log_caps
        merged = {}
        merged.update(log_caps)
        merged.update(metric_caps)
        self.field_caps = merged
        return {
            "metric_fields": len(metric_caps),
            "log_fields": len(log_caps),
        }


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------

_LOG_ONLY_FIELDS = {"log.level"}


def derive_dataset_from_index(index_pattern: str) -> str:
    """Derive the ``data_stream.dataset`` value from an Elastic data stream index pattern.

    The Elastic naming convention is ``{type}-{dataset}-{namespace}``.
    Returns the *dataset* segment when the pattern has at least three parts
    and the dataset segment is not a wildcard, otherwise returns ``""``.
    """
    parts = index_pattern.split("-")
    if len(parts) < 3:
        return ""
    dataset = parts[1]
    if "*" in dataset or "?" in dataset:
        return ""
    return dataset


def _default_tag_map() -> dict[str, str]:
    return {
        "host": "host.name",
        "env": "deployment.environment",
        "service": "service.name",
        "version": "service.version",
        "source": "service.name",
        "status": "log.level",
        "container_name": "container.name",
        "container_id": "container.id",
        "pod_name": "kubernetes.pod.name",
        "kube_namespace": "kubernetes.namespace",
        "kube_cluster_name": "kubernetes.cluster.name",
        "kube_deployment": "kubernetes.deployment.name",
        "image_name": "container.image.name",
        "image_tag": "container.image.tag",
    }


def _workshop_otel_tag_map() -> dict[str, str]:
    """Extra tag mappings for the migration workshop OTLP fleet (tools/otel_workshop_fleet.py).

    Logical hosts map to ``host.name``; there are no real disks/interfaces/containers, so
    ``device`` / ``interface`` break down by ``service.name``.     Workshop logs: OTLP from ``tools/datadog_otel_to_elastic.py`` uses **http.route** (not
    ``url.path``) on log attributes; bulk seed duplicates **http.route** for the same value.
    """
    return {
        **_default_tag_map(),
        "device": "service.name",
        "interface": "service.name",
        # Fleet runs on the host, not in k8s — treat "container" as logical service.
        "container_name": "service.name",
        "kube_namespace": "deployment.environment",
        # Datadog @http.url_details.path / http.url facet → OTel-style route (exists in mOTLP logs).
        "http.url": "http.route",
        "@http.url_details.path": "http.route",
    }


# Datadog synthetic dashboards in assets/datadog/dashboards/05–10 target classic host/container
# metrics. The workshop fleet only emits OTLP gauges and HTTP/error counters; map those names
# so migrated Lens / ES|QL panels resolve to real ``metrics-*`` fields.
_WORKSHOP_OTEL_METRIC_MAP: dict[str, str] = {
    # --- Host CPU (05) ---
    "system.cpu.user": "system.cpu.utilization",
    "system.cpu.system": "system.cpu.utilization",
    "system.cpu.idle": "system.cpu.utilization",
    "system.cpu.iowait": "system.cpu.utilization",
    "system.cpu.stolen": "system.cpu.utilization",
    "system.cpu.nice": "system.cpu.utilization",
    "system.cpu.guest": "system.cpu.utilization",
    "system.load.1": "system.cpu.utilization",
    "system.load.5": "system.cpu.utilization",
    "system.load.15": "system.cpu.utilization",
    "system.cpu.context_switches": "http_requests_total",
    "system.cpu.interrupt": "http_requests_total",
    # --- Host memory (06) ---
    "system.mem.pct_usable": "system.memory.utilization",
    "system.mem.used": "system.memory.utilization",
    "system.mem.free": "system.memory.utilization",
    "system.mem.slab": "system.memory.utilization",
    "system.mem.buffered": "system.memory.utilization",
    "system.mem.cached": "system.memory.utilization",
    "system.mem.total": "system.memory.utilization",
    "system.mem.usable": "system.memory.utilization",
    "system.mem.commit_limit": "system.memory.utilization",
    "system.swap.used": "system.memory.utilization",
    "system.swap.pct_free": "system.memory.utilization",
    "system.mem.page_faults": "http_requests_total",
    # --- Disk I/O (07) ---
    "system.disk.io": "system.cpu.utilization",
    "system.disk.in_use": "system.memory.utilization",
    "system.disk.read_bytes": "http_requests_total",
    "system.disk.write_bytes": "http_requests_total",
    "system.disk.read_time_pct": "system.cpu.utilization",
    "system.disk.write_time_pct": "system.cpu.utilization",
    "system.disk.queue_size": "system.memory.utilization",
    "system.disk.read_ops": "http_requests_total",
    "system.disk.write_ops": "http_requests_total",
    "system.disk.free": "system.memory.utilization",
    "system.io.util": "system.cpu.utilization",
    # --- Network (08) ---
    "system.net.bytes_sent": "http_requests_total",
    "system.net.bytes_rcvd": "http_requests_total",
    "system.net.tcp.retrans_segs": "operation_errors_total",
    "system.net.udp.in_errors": "operation_errors_total",
    "system.net.packets_in.count": "http_requests_total",
    "system.net.packets_out.count": "http_requests_total",
    "system.net.tcp.connections": "system.cpu.utilization",
    "system.net.tcp.listen_overflows": "operation_errors_total",
    "system.net.errors_in": "operation_errors_total",
    "system.net.errors_out": "operation_errors_total",
    "trace.http.request.hits": "http_requests_total",
    "trace.dns.lookup.duration": "system.cpu.utilization",
    # --- Container (09) ---
    "container.cpu.throttled": "system.cpu.utilization",
    "container.cpu.usage": "system.cpu.utilization",
    "container.cpu.user": "system.cpu.utilization",
    "container.cpu.system": "system.cpu.utilization",
    "container.cpu.shares": "system.cpu.utilization",
    "container.memory.usage": "system.memory.utilization",
    "container.memory.limit": "system.memory.utilization",
    "container.net.rcvd": "http_requests_total",
    "container.net.sent": "http_requests_total",
    "container.restarts": "operation_errors_total",
    "container.oom_events": "operation_errors_total",
    "container.filesystem.usage": "system.memory.utilization",
    # --- Log dashboard metric rows (10) ---
    "trace.http.request.errors": "operation_errors_total",
    "trace.http.request.duration": "system.memory.utilization",
}


OTEL_PROFILE = FieldMapProfile(
    name="otel",
    metric_index="metrics-*",
    logs_index="logs-*",
    timestamp_field="@timestamp",
    tag_map=_workshop_otel_tag_map(),
    metric_map=dict(_WORKSHOP_OTEL_METRIC_MAP),
    metric_prefix="",
    metric_suffix="",
)

PROMETHEUS_PROFILE = FieldMapProfile(
    name="prometheus",
    metric_index="metrics-prometheus-*",
    logs_index="logs-*",
    timestamp_field="@timestamp",
    metrics_dataset_filter="prometheus",
    tag_map={
        **_default_tag_map(),
        "host": "instance",
    },
    metric_prefix="prometheus.metrics.",
    metric_suffix="",
)

ELASTIC_AGENT_PROFILE = FieldMapProfile(
    name="elastic_agent",
    metric_index="metrics-*",
    logs_index="logs-*",
    timestamp_field="@timestamp",
    tag_map=_default_tag_map(),
    metric_prefix="",
    metric_suffix="",
    metric_map={
        "system.cpu.user": "system.cpu.user.pct",
        "system.cpu.system": "system.cpu.system.pct",
        "system.cpu.idle": "system.cpu.idle.pct",
        "system.cpu.iowait": "system.cpu.iowait.pct",
        "system.mem.usable": "system.memory.actual.used.bytes",
        "system.mem.total": "system.memory.total",
        "system.disk.read_time": "system.diskio.read.time",
        "system.disk.write_time": "system.diskio.write.time",
        "system.disk.in_use": "system.filesystem.used.pct",
        "system.disk.free": "system.filesystem.free",
        "system.disk.total": "system.filesystem.total",
        "system.net.bytes_rcvd": "system.network.in.bytes",
        "system.net.bytes_sent": "system.network.out.bytes",
        "system.load.1": "system.load.1",
        "system.load.5": "system.load.5",
        "system.load.15": "system.load.15",
        "system.swap.used": "system.memory.swap.used.bytes",
        "system.swap.free": "system.memory.swap.free",
    },
)

PASSTHROUGH_PROFILE = FieldMapProfile(
    name="passthrough",
    metric_index="metrics-*",
    logs_index="logs-*",
    timestamp_field="@timestamp",
)

BUILTIN_PROFILES: dict[str, FieldMapProfile] = {
    "default": OTEL_PROFILE,
    "otel": OTEL_PROFILE,
    "prometheus": PROMETHEUS_PROFILE,
    "elastic_agent": ELASTIC_AGENT_PROFILE,
    "passthrough": PASSTHROUGH_PROFILE,
}


def load_profile(name_or_path: str) -> FieldMapProfile:
    """Load a field map profile by name or from a YAML file."""
    if name_or_path in BUILTIN_PROFILES:
        return _clone_profile(BUILTIN_PROFILES[name_or_path])

    path = Path(name_or_path)
    if path.exists() and path.suffix in (".yml", ".yaml"):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return _profile_from_model(validate_field_profile_payload(raw, source=str(path)))

    raise ValueError(
        f"Unknown field profile '{name_or_path}'. "
        f"Use one of: {', '.join(sorted(BUILTIN_PROFILES))}, or pass a YAML path."
    )


def _profile_from_dict(raw: dict[str, Any]) -> FieldMapProfile:
    return _profile_from_model(validate_field_profile_payload(raw))


def _profile_from_model(model: FieldMapProfileModel) -> FieldMapProfile:
    metrics_ds = model.metrics_dataset_filter or derive_dataset_from_index(model.metric_index)
    logs_ds = model.logs_dataset_filter or derive_dataset_from_index(model.logs_index)
    return FieldMapProfile(
        name=model.name,
        metric_index=model.metric_index,
        logs_index=model.logs_index,
        log_index_map=dict(model.log_index_map),
        timestamp_field=model.timestamp_field,
        metrics_dataset_filter=metrics_ds,
        logs_dataset_filter=logs_ds,
        metric_map=dict(model.metric_map),
        tag_map=dict(model.tag_map),
        metric_prefix=model.metric_prefix,
        metric_suffix=model.metric_suffix,
        tag_prefix=model.tag_prefix,
    )


def _clone_profile(profile: FieldMapProfile) -> FieldMapProfile:
    return FieldMapProfile(
        name=profile.name,
        metric_index=profile.metric_index,
        logs_index=profile.logs_index,
        log_index_map=deepcopy(profile.log_index_map),
        timestamp_field=profile.timestamp_field,
        metrics_dataset_filter=profile.metrics_dataset_filter,
        logs_dataset_filter=profile.logs_dataset_filter,
        metric_map=deepcopy(profile.metric_map),
        tag_map=deepcopy(profile.tag_map),
        field_caps=deepcopy(profile.field_caps),
        metric_field_caps=deepcopy(profile.metric_field_caps),
        log_field_caps=deepcopy(profile.log_field_caps),
        metric_prefix=profile.metric_prefix,
        metric_suffix=profile.metric_suffix,
        tag_prefix=profile.tag_prefix,
    )
