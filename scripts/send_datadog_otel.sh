#!/usr/bin/env bash
# Send Datadog-style OTLP (traces/metrics/logs) into Alloy → Elastic managed OTLP.
set -euo pipefail
cd /root/workshop
# shellcheck disable=SC1090
source ~/.bashrc
exec python3 /root/workshop/tools/datadog_otel_to_elastic.py "$@"
