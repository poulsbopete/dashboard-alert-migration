#!/usr/bin/env bash
# Push this repo to GitHub and publish the Instruqt track (run from repo root after git commit).
# Usage: ./scripts/push_git_and_instruqt.sh
#
# After pulling new mig-to-kbn sources, run ./scripts/update_mig_to_kbn.sh (and commit submodule if used),
# optionally ./scripts/update_mig_to_kbn.sh --reinstall, then commit workshop changes and run this script.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> git push"
git push origin HEAD

echo "==> instruqt track validate + push"
instruqt track validate
instruqt track push

echo "OK: Git + Instruqt updated."
