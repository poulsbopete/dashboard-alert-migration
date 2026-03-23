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
exec python3 "$ROOT/tools/seed_workshop_telemetry.py" "$@"
