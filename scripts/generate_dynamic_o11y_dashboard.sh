#!/usr/bin/env bash
# Create a Kibana dashboard from live workshop OTLP data (logs-*, metrics-*, …).
# Requires KIBANA_URL, ES_URL, ES_API_KEY (or basic auth) — same as migrate scripts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${ROOT}/tools${PYTHONPATH:+:$PYTHONPATH}"
python3 "${ROOT}/tools/generate_dynamic_o11y_dashboard.py" "$@"
