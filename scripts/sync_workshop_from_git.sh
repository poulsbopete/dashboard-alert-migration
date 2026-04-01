#!/usr/bin/env bash
# Refresh /root/workshop from origin (shallow Instruqt clones miss new scripts until you pull).
# Usage: cd /root/workshop && source ~/.bashrc && ./scripts/sync_workshop_from_git.sh
set -euo pipefail
ROOT="$(readlink -f /root/workshop 2>/dev/null || echo /root/workshop)"
cd "$ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: $ROOT is not a git repo. Re-provision the sandbox or push the latest track." >&2
  exit 1
fi

REF="${WORKSHOP_GIT_REF:-main}"
echo "Updating from origin ($REF)..."
git fetch --depth 1 origin "$REF" 2>/dev/null || git fetch origin "$REF"
git reset --hard "origin/$REF"

# If mig-to-kbn is a submodule, pull its commit after the parent reset (shallow-friendly).
if [ -f .gitmodules ] && git config -f .gitmodules --get submodule.mig-to-kbn.path >/dev/null 2>&1; then
  echo "Updating submodule mig-to-kbn..."
  git submodule update --init --recursive --depth 1 2>/dev/null || git submodule update --init --recursive
fi

chmod +x scripts/*.sh 2>/dev/null || true
echo "OK: $(git log -1 --oneline)"
echo "Next: ./scripts/check_workshop_otel_pipeline.sh  OR  ./scripts/start_workshop_otel.sh"
if [ -d mig-to-kbn/.git ] && [ ! -f .gitmodules ]; then
  echo "      Standalone mig-to-kbn clone: ./scripts/update_mig_to_kbn.sh && sudo bash scripts/install_workshop_mig_to_kbn.sh"
fi
