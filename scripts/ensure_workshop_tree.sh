#!/usr/bin/env bash
# Repair /root/workshop when the track mount is incomplete (missing migration scripts).
# Idempotent. Safe to run as root on es3-api. Used by track setup (installed to /usr/local/bin)
# and optionally by migrate_grafana_dashboards_to_serverless.sh.
set -euo pipefail
MIG="scripts/migrate_grafana_dashboards_to_serverless.sh"
TARGET="/opt/instruqt-workshop-track"
URL="${WORKSHOP_GIT_URL:-https://github.com/poulsbopete/dashboard-alert-migration.git}"
REF="${WORKSHOP_GIT_REF:-main}"

if [[ -f "/root/workshop/$MIG" ]]; then
  echo "OK: /root/workshop already contains migration scripts."
  exit 0
fi

echo "Workshop tree incomplete — cloning ${URL} (${REF}) into ${TARGET} ..." >&2
export DEBIAN_FRONTEND=noninteractive
_a=1
while [ "$_a" -le 24 ]; do
  if apt-get update -y && apt-get install -y --no-install-recommends git ca-certificates; then
    break
  fi
  echo "WARN: apt-get failed (attempt $_a/24); waiting for dpkg lock..." >&2
  sleep 10
  _a=$((_a + 1))
done
if [ "$_a" -gt 24 ]; then
  echo "ERROR: apt-get failed after 24 attempts" >&2
  exit 1
fi
rm -rf "${TARGET}"
if ! git clone --depth 1 --branch "${REF}" "${URL}" "${TARGET}" 2>/dev/null; then
  git clone --depth 1 "${URL}" "${TARGET}"
fi
ln -sfn "${TARGET}" /root/workshop
chmod +x /root/workshop/scripts/*.sh 2>/dev/null || true
if [[ ! -f "/root/workshop/$MIG" ]]; then
  echo "ERROR: clone did not produce /root/workshop/$MIG" >&2
  exit 1
fi
echo "OK: repaired /root/workshop → ${TARGET}" >&2
