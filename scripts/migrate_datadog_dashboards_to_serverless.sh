#!/usr/bin/env bash
# Lab 2 one-shot (Instruqt / workshop VM): Datadog dashboards + monitors → Kibana Dashboards + Rules.
# Same idea as Lab 1 ./scripts/migrate_grafana_dashboards_to_serverless.sh — run in Terminal after source ~/.bashrc.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1090
[[ -f /root/.bashrc ]] && source /root/.bashrc

mkdir -p build/elastic-datadog-dashboards build/elastic-alerts

echo "==> [1/5] Converting 10 Datadog dashboards → Elastic draft JSON..."
python3 tools/datadog_dashboard_to_elastic.py assets/datadog/dashboards/*.json --out-dir build/elastic-datadog-dashboards
n="$(find build/elastic-datadog-dashboards -maxdepth 1 -name '*-elastic-draft.json' | wc -l | tr -d ' ')"
echo "    Draft files: $n"

echo "==> [2/5] Converting 4 Datadog monitors → Kibana rule drafts..."
for f in assets/datadog/monitor-*.json; do
  base="$(basename "$f" .json)"
  python3 tools/datadog_to_elastic_alert.py "$f" -o "build/elastic-alerts/${base}-elastic.json"
done
a="$(find build/elastic-alerts -maxdepth 1 -name 'monitor-*-elastic.json' | wc -l | tr -d ' ')"
echo "    Alert draft files: $a"

echo "==> [3/5] OpenTelemetry (Alloy → mOTLP) so Lens panels have data..."
if ! "$ROOT/scripts/start_workshop_otel.sh"; then
  echo "    WARN: start_workshop_otel.sh failed — publishes may still run; charts can be empty." >&2
else
  echo "    Waiting ~25s for OTLP documents..."
  sleep 25
fi

echo "==> [4/5] Publishing Datadog-derived dashboards to Kibana..."
python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-datadog-dashboards

echo "==> [5/5] Publishing Datadog-derived rules to Kibana (disabled by default; no connectors)..."
python3 tools/publish_datadog_alert_drafts_kibana.py --alerts-dir build/elastic-alerts

echo "==> Done."
echo "    Dashboards: Elastic Serverless → titles contain '(Datadog dashboard import draft)'."
echo "    Rules: Observability → Rules — workshop imports are created **disabled**; enable/edit queries in the UI."
