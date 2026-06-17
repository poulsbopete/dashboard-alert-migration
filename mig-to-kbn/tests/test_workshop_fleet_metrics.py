# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one or more contributor license agreements.
# SPDX-License-Identifier: Elastic-2.0

import ast
import pathlib

FLEET_PATH = pathlib.Path(__file__).resolve().parents[2] / "tools" / "otel_workshop_fleet.py"

EXPECTED_METRIC_NAMES = [
    # trace
    "trace_http_client_errors",
    "trace_spans_finished",
    "trace_dns_lookup_duration",
    # container extended
    "container_cpu_user",
    "container_cpu_system",
    "container_cpu_shares",
    "container_filesystem_usage",
    "container_restarts",
    "container_oom_events",
    # memory
    "system_mem_cached",
    "system_mem_usable",
    "system_mem_buffered",
    "system_mem_slab",
    "system_mem_commit_limit",
    "system_mem_page_faults",
    # swap
    "system_swap_used",
    "system_swap_pct_free",
    # disk / IO
    "system_disk_free",
    "system_disk_in_use",
    "system_disk_queue_size",
    "system_disk_read_time_pct",
    "system_disk_write_time_pct",
    "system_io_util",
    # cpu minor
    "system_cpu_nice",
    "system_cpu_stolen",
    "system_cpu_guest",
    "system_cpu_interrupt",
]


def test_fleet_file_parses():
    source = FLEET_PATH.read_text(encoding="utf-8")
    ast.parse(source)


def test_all_expected_metrics_registered():
    source = FLEET_PATH.read_text(encoding="utf-8")
    missing = [name for name in EXPECTED_METRIC_NAMES if f'"{name}"' not in source]
    assert not missing, f"Metrics not found in {FLEET_PATH.name}: {missing}"
