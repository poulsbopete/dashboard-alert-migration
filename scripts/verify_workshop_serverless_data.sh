#!/usr/bin/env bash
# Probe Elastic Serverless for metrics the workshop dashboards expect (OTLP → metrics-*).
#
# On the Instruqt VM, credentials are usually already in ~/.bashrc:
#   cd /root/workshop && source ~/.bashrc
#
# On your laptop (Path B), paste the same exports from the VM:
#   grep -E '^export (ES_URL|ES_API_KEY|KIBANA_URL|KIBANA_API_KEY)=' ~/.bashrc
#
# Then run:
#   ./scripts/verify_workshop_serverless_data.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

for v in ES_URL ES_API_KEY; do
  if [ -z "${!v:-}" ]; then
    echo "ERROR: $v is not set. Run: source ~/.bashrc   (VM) or paste exports from VM." >&2
    exit 1
  fi
done

BASE="${ES_URL%/}"
HDR=(-H "Authorization: ApiKey ${ES_API_KEY}" -H "Content-Type: application/json")

_run_query() {
  local q="$1"
  curl -sS "${HDR[@]}" "$BASE/_query" -d "$(python3 -c "import json,sys; print(json.dumps({'query': sys.argv[1]}))" "$q")"
}

echo "==> 1) Recent metrics-* document volume (last 24h)"
_run_query 'FROM metrics-*
| WHERE @timestamp > NOW() - 24 hours
| STATS docs = COUNT(*)
| LIMIT 1' | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d, indent=2)[:2000])"

echo ""
echo "==> 2) Sample http_requests_total-style series (Prometheus metric name varies; probe common names)"
for name in http_requests_total http_server_request_count; do
  echo "--- fields starting with ${name} (if any) ---"
  _run_query "FROM metrics-*
| WHERE @timestamp > NOW() - 6 hours
| WHERE \"${name}\" IS NOT NULL
| STATS c = COUNT(*)
| LIMIT 1" | python3 -c "import sys,json; d=json.load(sys.stdin); cols=d.get('columns',[]); rows=d.get('values',[]); print('columns:', cols, 'row0:', rows[0] if rows else None)" 2>/dev/null || true
done

echo ""
echo "==> 3) Optional: pre-upload ES|QL validation (same signals as grafana-migrate --validate)"
echo "    WORKSHOP_MIG_ES_VALIDATE=1 ./scripts/migrate_grafana_dashboards_to_serverless.sh"

echo ""
echo "OK: If (1) shows docs > 0, OTLP metrics are landing. Native PROMQL on Serverless expects"
echo "    Elasticsearch column names (http.response.status_code, http.request.method, http.route, service.name)."
echo "    See scripts/generate_grafana_dashboards.py."
