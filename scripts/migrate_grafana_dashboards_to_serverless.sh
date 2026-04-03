#!/usr/bin/env bash
# Path A (Instruqt): OTLP (optional) → Grafana JSON → mig-to-kbn (grafana-migrate) → upload (--native-promql).
# Unified alerts under assets/grafana/alerts/ are migrated with --fetch-alerts; publish_grafana_alert_drafts_kibana.py
# POSTs rule payloads from build/mig-grafana/alert_comparison_results.json (rules created disabled by default).
# Default: Kibana-only upload (--kibana-url + --kibana-api-key, no --es-url / --validate) so empty clusters do not
#          fail live ES|QL pre-upload validation (Subham / team guidance). Set WORKSHOP_MIG_ES_VALIDATE=1 to pass
#          --es-url, --es-api-key, and --validate (auto-enabled by mig-to-kbn when --es-url is set with --upload).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1090
[[ -f /root/.bashrc ]] && source /root/.bashrc

MIG_VENV="${MIG_TO_KBN_VENV:-/opt/mig-to-kbn-venv}"
GRAFANA_MIGRATE="${MIG_VENV}/bin/grafana-migrate"
bash "${ROOT}/scripts/ensure_mig_to_kbn_install.sh" grafana-migrate

if [ -x /opt/workshop-venv/bin/python3 ]; then
  PY="${WORKSHOP_PYTHON:-/opt/workshop-venv/bin/python3}"
else
  PY="${WORKSHOP_PYTHON:-python3}"
fi

if [ -z "${KIBANA_URL:-}" ]; then
  echo "ERROR: KIBANA_URL is not set. Run: source ~/.bashrc" >&2
  exit 1
fi
if [ -z "${ES_URL:-}" ]; then
  echo "ERROR: ES_URL is not set. Run: source ~/.bashrc" >&2
  exit 1
fi
if [ -z "${ES_API_KEY:-}" ] && { [ -z "${ES_USERNAME:-}" ] || [ -z "${ES_PASSWORD:-}" ]; }; then
  echo "ERROR: Set ES_API_KEY (or ES_USERNAME + ES_PASSWORD). Run: source ~/.bashrc" >&2
  exit 1
fi

KIBANA_KEY="${KIBANA_API_KEY:-${ES_API_KEY:-}}"
if [ -z "${KIBANA_KEY}" ]; then
  echo "ERROR: Need KIBANA_API_KEY or ES_API_KEY for Kibana upload." >&2
  exit 1
fi

OUT="${ROOT}/build/mig-grafana"
mkdir -p "${OUT}"

WAIT_OTLP=0
if [ "${WORKSHOP_SKIP_OTEL:-0}" = "1" ]; then
  echo "==> [1/4] Skipping OTLP (WORKSHOP_SKIP_OTEL=1 — use only if telemetry is already in Elasticsearch)."
elif [ "${WORKSHOP_FORCE_OTEL_RESTART:-0}" != "1" ] \
  && curl -sf --max-time 3 "http://127.0.0.1:12345/metrics" >/dev/null 2>&1 \
  && pgrep -f '[o]tel_workshop_fleet.py' >/dev/null 2>&1; then
  echo "==> [1/4] OTLP already running (Alloy + fleet). Skipping restart — same situation as Path B after bootstrap."
  echo "    To force a full restart: WORKSHOP_FORCE_OTEL_RESTART=1 ./scripts/migrate_grafana_dashboards_to_serverless.sh"
  WAIT_OTLP=45
else
  echo "==> [1/4] OpenTelemetry pipeline (Alloy → Elastic mOTLP + OTLP SDK emitters)..."
  if ! "${ROOT}/scripts/start_workshop_otel.sh"; then
    echo "    ERROR: start_workshop_otel.sh failed (need ES_API_KEY and WORKSHOP_OTLP_ENDPOINT or derivable ES_URL/KIBANA_URL)." >&2
    exit 1
  fi
  WAIT_OTLP=45
fi

if [ "$WAIT_OTLP" -gt 0 ]; then
  echo "    Waiting ${WAIT_OTLP}s for logs/metrics/traces to land from OTLP..."
  sleep "$WAIT_OTLP"
fi

# mig-to-kbn defaults --es-url from ES_URL in the environment (~/.bashrc). Empty strings on the CLI override that
# so Kibana-only upload does not auto-enable live ES|QL validation (see datadog/grafana cli.py).
ES_ES_ARGS=(--es-url "" --es-api-key "")
if [ "${WORKSHOP_MIG_ES_VALIDATE:-0}" = "1" ]; then
  ES_ES_ARGS=(--es-url "${ES_URL}" --es-api-key "${ES_API_KEY}" --validate)
  echo "==> [2/4] grafana-migrate (… + live ES|QL validation: WORKSHOP_MIG_ES_VALIDATE=1)..."
else
  echo "==> [2/4] grafana-migrate (Kibana-only upload; ES_URL in env ignored for validation — WORKSHOP_MIG_ES_VALIDATE=1 to enable)..."
fi
"${GRAFANA_MIGRATE}" \
  --source files \
  --input-dir "${ROOT}/assets/grafana" \
  --output-dir "${OUT}" \
  --native-promql \
  --data-view "metrics-*" \
  --esql-index "metrics-*" \
  --logs-index "logs-*" \
  "${ES_ES_ARGS[@]}" \
  --upload \
  --kibana-url "${KIBANA_URL}" \
  --kibana-api-key "${KIBANA_KEY}" \
  --ensure-data-views \
  --fetch-alerts

n_yaml="$(find "${OUT}/yaml" -maxdepth 1 -name '*.yaml' 2>/dev/null | wc -l | tr -d ' ')"
echo "    YAML dashboards: ${n_yaml} (under ${OUT}/yaml/)"

echo "==> [3/4] Publishing Grafana-derived rules from alert_comparison_results.json (disabled in Kibana by default)..."
"${PY}" "${ROOT}/tools/publish_grafana_alert_drafts_kibana.py" --comparison "${OUT}/alert_comparison_results.json"

echo "==> [4/4] Open Elastic Serverless → Dashboards + Rules. Artifacts: ${OUT}/migration_report.json, ${OUT}/alert_comparison_results.json"
echo "==> Done."
