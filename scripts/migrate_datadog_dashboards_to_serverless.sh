#!/usr/bin/env bash
# Lab 2 one-shot (Instruqt / workshop VM): Datadog dashboards + monitors → Kibana Dashboards + Rules.
# Same idea as Lab 1 ./scripts/migrate_grafana_dashboards_to_serverless.sh — run in Terminal after source ~/.bashrc.
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

mkdir -p build/elastic-datadog-dashboards build/elastic-alerts

echo "==> [1/5] Converting 10 Datadog dashboards → Elastic draft JSON..."
"$PY" tools/datadog_dashboard_to_elastic.py assets/datadog/dashboards/*.json --out-dir build/elastic-datadog-dashboards
n="$(find build/elastic-datadog-dashboards -maxdepth 1 -name '*-elastic-draft.json' | wc -l | tr -d ' ')"
echo "    Draft files: $n"

echo "==> [2/5] Converting 4 Datadog monitors → Kibana rule drafts..."
for f in assets/datadog/monitor-*.json; do
  base="$(basename "$f" .json)"
  "$PY" tools/datadog_to_elastic_alert.py "$f" -o "build/elastic-alerts/${base}-elastic.json"
done
a="$(find build/elastic-alerts -maxdepth 1 -name 'monitor-*-elastic.json' | wc -l | tr -d ' ')"
echo "    Alert draft files: $a"

WAIT_OTLP=0
if [ "${WORKSHOP_SKIP_OTEL:-0}" = "1" ]; then
  echo "==> [3/5] Skipping OTLP (WORKSHOP_SKIP_OTEL=1)."
elif [ "${WORKSHOP_FORCE_OTEL_RESTART:-0}" != "1" ] \
  && curl -sf --max-time 3 "http://127.0.0.1:12345/metrics" >/dev/null 2>&1 \
  && pgrep -f '[o]tel_workshop_fleet.py' >/dev/null 2>&1; then
  echo "==> [3/5] OTLP already running — skipping restart."
  WAIT_OTLP=12
else
  echo "==> [3/5] OpenTelemetry (Alloy → mOTLP) so Lens panels have data..."
  if ! "$ROOT/scripts/start_workshop_otel.sh"; then
    echo "    WARN: start_workshop_otel.sh failed — publishes may still run; charts can be empty." >&2
  else
    WAIT_OTLP=45
  fi
fi
if [ "$WAIT_OTLP" -gt 0 ]; then
  echo "    Waiting ${WAIT_OTLP}s for OTLP documents..."
  sleep "$WAIT_OTLP"
fi

echo "==> [4/5] Publishing Datadog-derived dashboards to Kibana..."
"$PY" tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-datadog-dashboards

echo "==> [5/5] Publishing Datadog-derived rules to Kibana (disabled by default; no connectors)..."
"$PY" tools/publish_datadog_alert_drafts_kibana.py --alerts-dir build/elastic-alerts

echo "==> Done."
echo "    Dashboards: Elastic Serverless → titles contain '(Datadog dashboard import draft)'."
echo "    Rules: Observability → Rules — workshop imports are created **disabled**; enable/edit queries in the UI."
