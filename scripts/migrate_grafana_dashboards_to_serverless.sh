#!/usr/bin/env bash
# Path A (Instruqt Terminal): convert all Grafana exports → Elastic drafts → create dashboards in Kibana via API.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1090
[[ -f /root/.bashrc ]] && source /root/.bashrc

mkdir -p build/elastic-dashboards
echo "==> [1/2] Converting 20 Grafana exports to Elastic draft JSON..."
python3 tools/grafana_to_elastic.py assets/grafana/*.json --out-dir build/elastic-dashboards
n="$(find build/elastic-dashboards -maxdepth 1 -name '*-elastic-draft.json' | wc -l | tr -d ' ')"
echo "    Draft files: $n"
echo "==> [2/2] Publishing drafts to Kibana (Saved Objects API)..."
python3 tools/publish_grafana_drafts_kibana.py --drafts-dir build/elastic-dashboards
echo "==> Done. Open the Elastic Serverless tab → Dashboards — look for titles ending in '(Grafana import draft)'."
