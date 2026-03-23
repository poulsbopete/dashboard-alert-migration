#!/usr/bin/env bash
# Path A (Instruqt Terminal): convert all Grafana exports → Elastic drafts → create dashboards in Kibana via API.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1090
[[ -f /root/.bashrc ]] && source /root/.bashrc

if [ -x /opt/workshop-venv/bin/python3 ]; then
  PY="${WORKSHOP_PYTHON:-/opt/workshop-venv/bin/python3}"
else
  PY="${WORKSHOP_PYTHON:-python3}"
fi

if [ -z "${KIBANA_URL:-}" ]; then
  echo "ERROR: KIBANA_URL is not set. Run: source ~/.bashrc" >&2
  exit 1
fi
if [ -z "${ES_API_KEY:-}" ] && { [ -z "${ES_USERNAME:-}" ] || [ -z "${ES_PASSWORD:-}" ]; }; then
  echo "ERROR: Set ES_API_KEY (or ES_USERNAME + ES_PASSWORD). Run: source ~/.bashrc" >&2
  exit 1
fi

mkdir -p build/elastic-dashboards
echo "==> [1/3] Converting 20 Grafana exports to Elastic draft JSON..."
"$PY" tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
n="$(find build/elastic-dashboards -maxdepth 1 -name '*-elastic-draft.json' | wc -l | tr -d ' ')"
echo "    Draft files: $n"

# Path B on a laptop publishes against data already flowing from track bootstrap. Path A used to pkill+restart
# OTLP every time, which drops the pipeline and makes Lens probes weaker than Path B. Skip restart when healthy.
WAIT_OTLP=0
if [ "${WORKSHOP_SKIP_OTEL:-0}" = "1" ]; then
  echo "==> [2/3] Skipping OTLP (WORKSHOP_SKIP_OTEL=1 — use only if telemetry is already in Elasticsearch)."
elif [ "${WORKSHOP_FORCE_OTEL_RESTART:-0}" != "1" ] \
  && curl -sf --max-time 3 "http://127.0.0.1:12345/metrics" >/dev/null 2>&1 \
  && pgrep -f '[o]tel_workshop_fleet.py' >/dev/null 2>&1; then
  echo "==> [2/3] OTLP already running (Alloy + fleet). Skipping restart — same situation as Path B after bootstrap."
  echo "    To force a full restart: WORKSHOP_FORCE_OTEL_RESTART=1 ./scripts/migrate_grafana_dashboards_to_serverless.sh"
  WAIT_OTLP=12
else
  echo "==> [2/3] OpenTelemetry pipeline (Alloy → Elastic mOTLP + OTLP SDK emitters) — real OTLP, not bulk-indexed JSON..."
  if ! "$ROOT/scripts/start_workshop_otel.sh"; then
    echo "    ERROR: start_workshop_otel.sh failed (need ES_API_KEY and WORKSHOP_OTLP_ENDPOINT or derivable ES_URL/KIBANA_URL)." >&2
    exit 1
  fi
  WAIT_OTLP=45
fi

if [ "$WAIT_OTLP" -gt 0 ]; then
  echo "    Waiting ${WAIT_OTLP}s for logs/metrics/traces to land from OTLP..."
  sleep "$WAIT_OTLP"
fi

echo "==> [3/3] Publishing to Kibana (Dashboards API; saved-objects import fallback)..."
"$PY" tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-dashboards
echo "==> Done. Open the Elastic Serverless tab → Dashboards — look for titles ending in '(Grafana import draft)'."
