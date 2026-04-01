#!/usr/bin/env bash
# Path A (Instruqt): OTLP (optional) → Grafana JSON → mig-to-kbn (grafana-migrate) → validate → upload to Kibana Serverless (--native-promql).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1090
[[ -f /root/.bashrc ]] && source /root/.bashrc

MIG_VENV="${MIG_TO_KBN_VENV:-/opt/mig-to-kbn-venv}"
GRAFANA_MIGRATE="${MIG_VENV}/bin/grafana-migrate"
bash "${ROOT}/scripts/ensure_mig_to_kbn_install.sh" grafana-migrate

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
  echo "==> [1/3] Skipping OTLP (WORKSHOP_SKIP_OTEL=1 — use only if telemetry is already in Elasticsearch)."
elif [ "${WORKSHOP_FORCE_OTEL_RESTART:-0}" != "1" ] \
  && curl -sf --max-time 3 "http://127.0.0.1:12345/metrics" >/dev/null 2>&1 \
  && pgrep -f '[o]tel_workshop_fleet.py' >/dev/null 2>&1; then
  echo "==> [1/3] OTLP already running (Alloy + fleet). Skipping restart — same situation as Path B after bootstrap."
  echo "    To force a full restart: WORKSHOP_FORCE_OTEL_RESTART=1 ./scripts/migrate_grafana_dashboards_to_serverless.sh"
  WAIT_OTLP=12
else
  echo "==> [1/3] OpenTelemetry pipeline (Alloy → Elastic mOTLP + OTLP SDK emitters)..."
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

echo "==> [2/3] grafana-migrate (files → YAML → compile → validate → upload, native PromQL for Serverless)..."
"${GRAFANA_MIGRATE}" \
  --source files \
  --input-dir "${ROOT}/assets/grafana" \
  --output-dir "${OUT}" \
  --native-promql \
  --data-view "metrics-*" \
  --logs-index "logs-*" \
  --es-url "${ES_URL}" \
  --es-api-key "${ES_API_KEY}" \
  --validate \
  --upload \
  --kibana-url "${KIBANA_URL}" \
  --kibana-api-key "${KIBANA_KEY}" \
  --ensure-data-views

n_yaml="$(find "${OUT}/yaml" -maxdepth 1 -name '*.yaml' 2>/dev/null | wc -l | tr -d ' ')"
echo "    YAML dashboards: ${n_yaml} (under ${OUT}/yaml/)"

echo "==> [3/3] Open Elastic Serverless → Dashboards (titles match Grafana exports). Artifacts: ${OUT}/migration_report.json"
echo "==> Done."
