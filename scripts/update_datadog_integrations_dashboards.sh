#!/usr/bin/env bash
# Vendor curated Datadog integration dashboards from DataDog/integrations-core (BSD-3-Clause).
# Usage (repo root): ./scripts/update_datadog_integrations_dashboards.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/assets/datadog/integrations-core"
BASE="${INTEGRATIONS_CORE_RAW:-https://raw.githubusercontent.com/DataDog/integrations-core/master}"

# integration_path_on_github -> local filename
declare -a PAIRS=(
  "postgres/assets/dashboards/postgresql_dashboard.json|postgresql_dashboard.json"
  "nginx/assets/dashboards/NGINX-Overview_dashboard.json|nginx-overview_dashboard.json"
  "docker_daemon/assets/dashboards/docker_dashboard.json|docker_dashboard.json"
  "mysql/assets/dashboards/overview.json|mysql-overview.json"
  "apache/assets/dashboards/apache_dashboard.json|apache_dashboard.json"
  "redisdb/assets/dashboards/overview.json|redisdb-overview.json"
  "kubernetes/assets/dashboards/kubernetes_pods.json|kubernetes-pods.json"
  "rabbitmq/assets/dashboards/rabbitmq_dashboard.json|rabbitmq_dashboard.json"
)

mkdir -p "${OUT}"
_ok=0
_fail=0
for pair in "${PAIRS[@]}"; do
  src="${pair%%|*}"
  dest="${pair##*|}"
  url="${BASE}/${src}"
  echo "==> ${dest} <- ${url}"
  if curl -fsSL "${url}" -o "${OUT}/${dest}"; then
    _ok=$((_ok + 1))
  else
    echo "WARN: failed to fetch ${url}" >&2
    _fail=$((_fail + 1))
  fi
done

echo "OK: fetched ${_ok} dashboards to ${OUT} (${_fail} failures)."
if [ "${_fail}" -gt 0 ]; then
  exit 1
fi
