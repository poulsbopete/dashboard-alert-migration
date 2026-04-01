#!/usr/bin/env bash
# Lab 2 (Instruqt): OTLP (optional) → Datadog dashboards via datadog-migrate; monitors → legacy Kibana rule drafts + publisher (hybrid).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1090
[[ -f /root/.bashrc ]] && source /root/.bashrc

MIG_VENV="${MIG_TO_KBN_VENV:-/opt/mig-to-kbn-venv}"
DD_MIGRATE="${MIG_VENV}/bin/datadog-migrate"
bash "${ROOT}/scripts/ensure_mig_to_kbn_install.sh" datadog-migrate

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

STAGE="${ROOT}/build/mig-datadog-stage"
OUT="${ROOT}/build/mig-datadog"
rm -rf "${STAGE}"
mkdir -p "${STAGE}/monitors"
cp "${ROOT}/assets/datadog/dashboards/"*.json "${STAGE}/"
for f in "${ROOT}/assets/datadog/monitor-"*.json; do
  [ -f "$f" ] || continue
  cp "$f" "${STAGE}/monitors/"
done

mkdir -p "${ROOT}/build/elastic-alerts"

WAIT_OTLP=0
if [ "${WORKSHOP_SKIP_OTEL:-0}" = "1" ]; then
  echo "==> [1/5] Skipping OTLP (WORKSHOP_SKIP_OTEL=1)."
elif [ "${WORKSHOP_FORCE_OTEL_RESTART:-0}" != "1" ] \
  && curl -sf --max-time 3 "http://127.0.0.1:12345/metrics" >/dev/null 2>&1 \
  && pgrep -f '[o]tel_workshop_fleet.py' >/dev/null 2>&1; then
  echo "==> [1/5] OTLP already running — skipping restart."
  WAIT_OTLP=12
else
  echo "==> [1/5] OpenTelemetry (Alloy → mOTLP) so Lens panels have data..."
  if ! "${ROOT}/scripts/start_workshop_otel.sh"; then
    echo "    WARN: start_workshop_otel.sh failed — publishes may still run; charts can be empty." >&2
  else
    WAIT_OTLP=45
  fi
fi
if [ "$WAIT_OTLP" -gt 0 ]; then
  echo "    Waiting ${WAIT_OTLP}s for OTLP documents..."
  sleep "$WAIT_OTLP"
fi

echo "==> [2/5] datadog-migrate (OTEL field profile, validate, compile, upload) + monitor IR extract..."
"${DD_MIGRATE}" \
  --source files \
  --input-dir "${STAGE}" \
  --output-dir "${OUT}" \
  --field-profile otel \
  --data-view "metrics-*" \
  --logs-index "logs-*" \
  --es-url "${ES_URL}" \
  --es-api-key "${ES_API_KEY}" \
  --validate \
  --upload \
  --kibana-url "${KIBANA_URL}" \
  --kibana-api-key "${KIBANA_KEY}" \
  --ensure-data-views \
  --fetch-monitors

n_yaml="$(find "${OUT}/yaml" -maxdepth 1 -name '*.yaml' 2>/dev/null | wc -l | tr -d ' ')"
echo "    YAML dashboards: ${n_yaml} (under ${OUT}/yaml/)"

echo "==> [3/5] Converting 4 Datadog monitors → Kibana rule drafts (workshop publisher)..."
for f in "${ROOT}/assets/datadog/monitor-"*.json; do
  [ -f "$f" ] || continue
  base="$(basename "$f" .json)"
  "${PY}" "${ROOT}/tools/datadog_to_elastic_alert.py" "$f" -o "${ROOT}/build/elastic-alerts/${base}-elastic.json"
done
a="$(find "${ROOT}/build/elastic-alerts" -maxdepth 1 -name 'monitor-*-elastic.json' | wc -l | tr -d ' ')"
echo "    Alert draft files: ${a}"

echo "==> [4/5] Datadog dashboards already uploaded by datadog-migrate (skip legacy draft publisher)."

echo "==> [5/5] Publishing Datadog-derived rules to Kibana (disabled by default; no connectors)..."
"${PY}" "${ROOT}/tools/publish_datadog_alert_drafts_kibana.py" --alerts-dir "${ROOT}/build/elastic-alerts"

echo "==> Done."
echo "    Dashboards: Elastic Serverless → search for migrated Datadog titles; artifacts under ${OUT}/"
echo "    Monitor IR summary: ${OUT}/monitor_migration_results.json (datadog-migrate) + published rules from build/elastic-alerts/"
echo "    Rules: Observability → Rules — workshop imports are created **disabled**; enable/edit queries in the UI."
