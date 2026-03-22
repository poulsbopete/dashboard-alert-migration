#!/usr/bin/env bash
# Path A (Instruqt Terminal): convert all Grafana exports → Elastic drafts → create dashboards in Kibana via API.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1090
[[ -f /root/.bashrc ]] && source /root/.bashrc

mkdir -p build/elastic-dashboards
echo "==> [1/3] Converting 20 Grafana exports to Elastic draft JSON..."
python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
n="$(find build/elastic-dashboards -maxdepth 1 -name '*-elastic-draft.json' | wc -l | tr -d ' ')"
echo "    Draft files: $n"
echo "==> [2/3] Seeding logs + metrics + traces (workshop-*-default @timestamp) for Discover / ES|QL probes..."
if python3 tools/seed_workshop_telemetry.py; then
  echo "    Seed OK (or already populated)."
else
  echo "    WARN: seed failed or skipped — Lens ES|QL panels may show Unknown column [@timestamp] until data exists." >&2
fi
echo "==> [3/3] Publishing to Kibana (Dashboards API; saved-objects import fallback)..."
python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-dashboards
echo "==> Done. Open the Elastic Serverless tab → Dashboards — look for titles ending in '(Grafana import draft)'."
