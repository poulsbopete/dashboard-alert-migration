#!/usr/bin/env bash
# Pull the latest elastic/mig-to-kbn into this workshop (developer laptop or CI).
# Supports: git submodule, vendored tree (no nested .git; re-clone + rsync), or standalone git clone under mig-to-kbn/.
#
# Usage (repo root):
#   ./scripts/update_mig_to_kbn.sh              # update sources only
#   ./scripts/update_mig_to_kbn.sh --reinstall   # update + reinstall /opt/mig-to-kbn-venv (needs root on VM)
#
# Env:
#   MIG_TO_KBN_DIR     default: <repo>/mig-to-kbn
#   MIG_TO_KBN_REMOTE  default: origin
#   MIG_TO_KBN_REF     default: main (branch or tag after fetch; must exist on remote)
#   MIG_TO_KBN_GIT_URL optional: override clone URL for vendored refresh (default: https://github.com/elastic/mig-to-kbn.git)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MIG="${MIG_TO_KBN_DIR:-${ROOT}/mig-to-kbn}"
REMOTE="${MIG_TO_KBN_REMOTE:-origin}"
REF="${MIG_TO_KBN_REF:-main}"
REINSTALL=0
for a in "$@"; do
  case "$a" in
    --reinstall) REINSTALL=1 ;;
    -h|--help)
      grep '^#' "$0" | grep -v '^#!/' | sed 's/^# //' | sed 's/^#//'
      exit 0
      ;;
  esac
done

_git_in_mig() {
  git -C "$MIG" "$@"
}

_is_submodule() {
  [ -f "${ROOT}/.gitmodules" ] && git config -f "${ROOT}/.gitmodules" --get submodule.mig-to-kbn.path >/dev/null 2>&1
}

update_via_submodule() {
  if ! _is_submodule; then
    return 1
  fi
  echo "==> mig-to-kbn: git submodule (init + update to recorded commit)"
  git submodule update --init --recursive --depth 1 2>/dev/null || git submodule update --init --recursive
  echo "==> mig-to-kbn: fetch ${REMOTE} and checkout ${REF}"
  _git_in_mig fetch --depth 1 "$REMOTE" "$REF" 2>/dev/null || _git_in_mig fetch "$REMOTE" "$REF"
  if _git_in_mig show-ref --verify --quiet "refs/remotes/${REMOTE}/${REF}"; then
    _git_in_mig checkout -B "$REF" "${REMOTE}/${REF}"
  else
    _git_in_mig checkout "$REF"
  fi
  echo "    Tip: to move the parent repo to this submodule commit: git add mig-to-kbn && git commit -m 'Bump mig-to-kbn'"
  return 0
}

# Vendored copy in git (no mig-to-kbn/.git): replace contents from upstream shallow clone.
update_via_vendored_tree() {
  if [ ! -f "${MIG}/pyproject.toml" ] || [ -e "${MIG}/.git" ]; then
    return 1
  fi
  _url="${MIG_TO_KBN_GIT_URL:-https://github.com/elastic/mig-to-kbn.git}"
  echo "==> mig-to-kbn: refresh vendored directory from ${_url} (${REF})"
  TDIR="$(mktemp -d)"
  UP="${TDIR}/upstream"
  if ! git clone --depth 1 --branch "$REF" "$_url" "$UP" 2>/dev/null; then
    git clone --depth 1 "$_url" "$UP"
    git -C "$UP" checkout "$REF" 2>/dev/null || true
  fi
  rsync -a --delete --exclude='.git' "${UP}/" "${MIG}/"
  rm -rf "${TDIR}"
  return 0
}

update_via_standalone_clone() {
  if [ ! -d "$MIG" ]; then
    echo "ERROR: ${MIG} not found." >&2
    echo "  One-time setup (pick one):" >&2
    echo "    gh repo clone elastic/mig-to-kbn ${MIG}" >&2
    echo "    git submodule add git@github.com:elastic/mig-to-kbn.git mig-to-kbn   # then commit .gitmodules" >&2
    exit 1
  fi
  if [ ! -d "$MIG/.git" ]; then
    echo "ERROR: ${MIG} is not a git clone (no .git). Use vendored mig-to-kbn/ or run this script to refresh a vendored tree." >&2
    exit 1
  fi
  echo "==> mig-to-kbn: pull ${REMOTE}/${REF} (standalone clone)"
  _git_in_mig fetch --depth 1 "$REMOTE" "$REF" 2>/dev/null || _git_in_mig fetch "$REMOTE"
  if _git_in_mig show-ref --verify --quiet "refs/remotes/${REMOTE}/${REF}"; then
    _git_in_mig checkout -B "$REF" "${REMOTE}/${REF}"
  else
    _git_in_mig checkout "$REF"
  fi
  return 0
}

if update_via_submodule; then
  :
elif update_via_vendored_tree; then
  :
else
  update_via_standalone_clone
fi

if [ -d "${MIG}/.git" ]; then
  echo "==> mig-to-kbn now at: $(_git_in_mig log -1 --oneline)"
else
  echo "==> mig-to-kbn vendored tree updated (commit mig-to-kbn/ in the parent repo)."
fi

if [ "$REINSTALL" = "1" ]; then
  echo "==> Reinstalling Python venv (install_workshop_mig_to_kbn.sh)..."
  bash "${ROOT}/scripts/install_workshop_mig_to_kbn.sh"
fi

echo "OK: Next: git add mig-to-kbn && git commit, then ./scripts/push_git_and_instruqt.sh"
echo "     On Instruqt VM after sync: source ~/.bashrc && sudo bash scripts/install_workshop_mig_to_kbn.sh   # if you have mig-to-kbn in the tree"
