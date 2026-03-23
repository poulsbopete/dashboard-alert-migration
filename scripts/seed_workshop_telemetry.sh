#!/usr/bin/env bash
# Legacy bulk index (not default; bootstrap uses OTLP unless WORKSHOP_ALLOW_BULK_SEED=1). Idempotent in the sense
# that it adds more documents each run; safe for demos.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [ -f /root/.bashrc ]; then
  # shellcheck disable=SC1090
  source /root/.bashrc
fi

PY="${WORKSHOP_PYTHON:-}"
if [ -z "$PY" ] && [ -x /opt/workshop-venv/bin/python3 ]; then
  PY=/opt/workshop-venv/bin/python3
fi
if [ -z "$PY" ]; then
  PY=python3
fi

SEED_PY="$ROOT/tools/seed_workshop_telemetry.py"
if ! grep -q -- "metrics-time-series" "$SEED_PY" 2>/dev/null; then
  echo "ERROR: $SEED_PY is missing newer CLI flags (e.g. --metrics-time-series)." >&2
  echo "Refresh the workshop repo:  cd /root/workshop && ./scripts/sync_workshop_from_git.sh" >&2
  exit 1
fi

exec "$PY" "$SEED_PY" "$@"
