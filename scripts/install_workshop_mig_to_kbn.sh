#!/usr/bin/env bash
# Install elastic/mig-to-kbn (obs-migrate) into a dedicated Python 3.12+ venv for Instruqt / workshop VMs.
# Requires: curl, ca-certificates. Uses Astral uv to provision Python and dependencies (includes kb-dashboard-cli via uvx at compile time).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIG_ROOT="${ROOT}/mig-to-kbn"
VENV="${MIG_TO_KBN_VENV:-/opt/mig-to-kbn-venv}"

if [ ! -f "${MIG_ROOT}/pyproject.toml" ]; then
  echo "ERROR: mig-to-kbn missing at ${MIG_ROOT}" >&2
  echo "       This workshop vendors mig-to-kbn in git. On your machine: ./scripts/update_mig_to_kbn.sh (uses gh when logged in)," >&2
  echo "       then commit and push mig-to-kbn/. Instruqt sandboxes do not clone elastic/mig-to-kbn by default." >&2
  exit 1
fi

export PATH="${HOME}/.local/bin:/root/.local/bin:${PATH}"

if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:/root/.local/bin:${PATH}"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv not on PATH after install (~/.local/bin or /root/.local/bin)." >&2
  exit 1
fi

echo "==> Creating venv ${VENV} (Python 3.12)..."
uv venv "${VENV}" --python 3.12

echo "==> pip install -e mig-to-kbn[all]..."
uv pip install -e "${MIG_ROOT}[all]" --python "${VENV}/bin/python"

if [ ! -x "${VENV}/bin/grafana-migrate" ] || [ ! -x "${VENV}/bin/datadog-migrate" ]; then
  echo "ERROR: expected console scripts missing under ${VENV}/bin" >&2
  exit 1
fi

echo "OK: ${VENV}/bin/grafana-migrate and datadog-migrate are ready."
