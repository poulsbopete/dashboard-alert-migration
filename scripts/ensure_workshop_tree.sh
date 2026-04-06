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
  echo "    Run migrate from that directory (same shell as cd): cd /root/workshop && bash $MIG" >&2
  exit 0
fi

echo "Workshop tree incomplete — cloning ${URL} (${REF}) into ${TARGET} ..." >&2
export DEBIAN_FRONTEND=noninteractive
_a=1
while [ "$_a" -le 24 ]; do
  if apt-get update -y && apt-get install -y --no-install-recommends git ca-certificates curl; then
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
rm -rf "${TARGET}" /opt/_workshop_unpack_learner
TARBALL="${WORKSHOP_GIT_TARBALL_URL:-}"
if [[ -z "$TARBALL" ]] && [[ "$URL" == *"github.com"* ]]; then
  _ghpath="${URL#*github.com/}"
  _ghpath="${_ghpath#*:}"
  _ghpath="${_ghpath%.git}"
  _or="$(printf '%s\n' "$_ghpath" | cut -d/ -f1-2)"
  [[ -n "$_or" ]] && [[ "$_or" == *"/"* ]] && TARBALL="https://github.com/${_or}/archive/refs/heads/${REF}.tar.gz"
fi
[[ -z "$TARBALL" ]] && TARBALL="https://github.com/poulsbopete/dashboard-alert-migration/archive/refs/heads/${REF}.tar.gz"

set +e
GIT_TERMINAL_PROMPT=0 git clone --depth 1 --branch "${REF}" "${URL}" "${TARGET}"
_ec=$?
if [[ $_ec -ne 0 ]]; then
  rm -rf "${TARGET}"
  GIT_TERMINAL_PROMPT=0 git clone --depth 1 "${URL}" "${TARGET}"
  _ec=$?
fi
if [[ $_ec -ne 0 ]] || [[ ! -f "${TARGET}/${MIG}" ]]; then
  echo "WARN: git failed or tree incomplete; trying tarball ${TARBALL} ..." >&2
  rm -rf "${TARGET}"
  mkdir -p /opt/_workshop_unpack_learner
  if curl -fsSL "$TARBALL" | tar -xz -C /opt/_workshop_unpack_learner; then
    _d="$(find /opt/_workshop_unpack_learner -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)"
    [[ -n "$_d" ]] && mv "$_d" "${TARGET}"
  fi
  rm -rf /opt/_workshop_unpack_learner
fi
set -euo pipefail

ln -sfn "${TARGET}" /root/workshop
chmod +x /root/workshop/scripts/*.sh 2>/dev/null || true
if [[ ! -f "/root/workshop/$MIG" ]]; then
  echo "ERROR: workshop repair did not produce /root/workshop/$MIG (git + tarball failed?)" >&2
  exit 1
fi
echo "OK: repaired /root/workshop → ${TARGET}" >&2
