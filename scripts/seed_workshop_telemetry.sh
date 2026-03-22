#!/usr/bin/env bash
# Re-seed synthetic logs + metrics (same as track bootstrap). Idempotent in the sense
# that it adds more documents each run; safe for demos.
set -euo pipefail
cd /root/workshop
# shellcheck disable=SC1090
source ~/.bashrc
exec python3 /root/workshop/tools/seed_workshop_telemetry.py "$@"
