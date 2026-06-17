#!/usr/bin/env bash
# Ensure mig-to-kbn console scripts exist under MIG_TO_KBN_VENV (default /opt/mig-to-kbn-venv).
# If sources are present but the venv is missing or incomplete, runs install_workshop_mig_to_kbn.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="${1:-}"
case "$CLI" in
  grafana-migrate | datadog-migrate) ;;
  *)
    echo "usage: $0 grafana-migrate|datadog-migrate" >&2
    exit 2
    ;;
esac

MIG_VENV="${MIG_TO_KBN_VENV:-/opt/mig-to-kbn-venv}"
BIN="${MIG_VENV}/bin/${CLI}"

if [ -x "$BIN" ]; then
  exit 0
fi

if [ ! -f "${ROOT}/mig-to-kbn/pyproject.toml" ]; then
  if [ -x "${ROOT}/scripts/ensure_workshop_mig_to_kbn_sources.sh" ]; then
    bash "${ROOT}/scripts/ensure_workshop_mig_to_kbn_sources.sh" || true
  fi
fi

if [ ! -f "${ROOT}/mig-to-kbn/pyproject.toml" ]; then
  echo "ERROR: ${BIN} not found and mig-to-kbn is missing at ${ROOT}/mig-to-kbn." >&2
  echo "       Run: bash scripts/ensure_workshop_mig_to_kbn_sources.sh" >&2
  echo "       Default upstream: https://github.com/elastic/observability-migration-platform.git" >&2
  exit 1
fi

echo "==> ${CLI} missing under ${MIG_VENV}; running install_workshop_mig_to_kbn.sh ..." >&2
export MIG_TO_KBN_VENV="${MIG_VENV}"
bash "${ROOT}/scripts/install_workshop_mig_to_kbn.sh"

if [ ! -x "$BIN" ]; then
  echo "ERROR: ${BIN} still missing after install." >&2
  exit 1
fi
