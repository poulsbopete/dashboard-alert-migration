#!/usr/bin/env bash
# Instruqt / workshop VM: Datadog dashboard JSON → Elastic drafts → Kibana (Dashboards API, same publisher as Grafana path).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1090
[[ -f /root/.bashrc ]] && source /root/.bashrc

mkdir -p build/elastic-datadog-dashboards
echo "==> [1/3] Converting 10 Datadog dashboards to Elastic draft JSON..."
python3 tools/datadog_dashboard_to_elastic.py assets/datadog/dashboards/*.json --out-dir build/elastic-datadog-dashboards
n="$(find build/elastic-datadog-dashboards -maxdepth 1 -name '*-elastic-draft.json' | wc -l | tr -d ' ')"
echo "    Draft files: $n"
echo "==> [2/3] OpenTelemetry (Alloy → mOTLP) so Lens panels have data..."
if ! "$ROOT/scripts/start_workshop_otel.sh"; then
  echo "    WARN: start_workshop_otel.sh failed — publish may still run; charts can be empty." >&2
else
  echo "    Waiting ~25s for OTLP documents..."
  sleep 25
fi
echo "==> [3/3] Publishing Datadog-derived drafts to Kibana..."
python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-datadog-dashboards
echo "==> Done. Elastic Serverless → Dashboards — look for titles ending in '(Datadog dashboard import draft)'."
