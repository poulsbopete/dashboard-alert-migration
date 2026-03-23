#!/usr/bin/env bash
# Push this repo to GitHub and publish the Instruqt track (run from repo root after git commit).
# Usage: ./scripts/push_git_and_instruqt.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> git push"
git push origin HEAD

echo "==> instruqt track validate + push"
instruqt track validate
instruqt track push

echo "OK: Git + Instruqt updated."
