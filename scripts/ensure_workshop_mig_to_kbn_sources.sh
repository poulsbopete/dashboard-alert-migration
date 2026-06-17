#!/usr/bin/env bash
# Ensure mig-to-kbn/ (observability-migration-platform) sources exist under the workshop root.
# Idempotent: no-op when pyproject.toml is already present.
#
# Env:
#   WORKSHOP_MIG_TO_KBN_GIT_URL  default: https://github.com/elastic/observability-migration-platform.git
#   WORKSHOP_MIG_TO_KBN_GIT_REF   default: main
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIG="${MIG_TO_KBN_DIR:-${ROOT}/mig-to-kbn}"
URL="${WORKSHOP_MIG_TO_KBN_GIT_URL:-https://github.com/elastic/observability-migration-platform.git}"
REF="${WORKSHOP_MIG_TO_KBN_GIT_REF:-main}"

if [ -f "${MIG}/pyproject.toml" ]; then
  exit 0
fi

if [ -d "${ROOT}/.git" ]; then
  echo "==> mig-to-kbn missing: trying git submodule update --init (parent .git only)..."
  git -C "${ROOT}" submodule update --init --depth 1 mig-to-kbn 2>/dev/null \
    || git -C "${ROOT}" submodule update --init mig-to-kbn 2>/dev/null \
    || true
fi

if [ -f "${MIG}/pyproject.toml" ]; then
  exit 0
fi

echo "==> mig-to-kbn missing: cloning ${URL} (${REF}) into ${MIG} ..."
rm -rf "${MIG}"
if [ -n "${REF}" ]; then
  if GIT_TERMINAL_PROMPT=0 git clone --depth 1 --branch "${REF}" "${URL}" "${MIG}" 2>/dev/null; then
    :
  elif GIT_TERMINAL_PROMPT=0 git clone --depth 1 "${URL}" "${MIG}"; then
    git -C "${MIG}" checkout "${REF}" 2>/dev/null || true
  else
    echo "ERROR: failed to clone observability-migration-platform from ${URL}" >&2
    exit 1
  fi
else
  GIT_TERMINAL_PROMPT=0 git clone --depth 1 "${URL}" "${MIG}" || {
    echo "ERROR: failed to clone observability-migration-platform from ${URL}" >&2
    exit 1
  }
fi

if [ ! -f "${MIG}/pyproject.toml" ]; then
  echo "ERROR: clone succeeded but ${MIG}/pyproject.toml is missing (wrong ref or repo layout)." >&2
  exit 1
fi

echo "OK: mig-to-kbn sources at ${MIG} ($(git -C "${MIG}" log -1 --oneline 2>/dev/null || echo unknown))"
