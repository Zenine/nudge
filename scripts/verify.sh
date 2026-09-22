#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERIFY_STATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nudge-verify.XXXXXX")"
cleanup_verify_state() {
  if [[ -n "${VERIFY_STATE_DIR:-}" && -d "$VERIFY_STATE_DIR" ]]; then
    rm -rf -- "$VERIFY_STATE_DIR"
  fi
}
trap cleanup_verify_state EXIT
export NUDGE_STATE_DIR="$VERIFY_STATE_DIR"

# shellcheck source=lib/python_env.sh
source "$ROOT/scripts/lib/python_env.sh"

PYTHON_BIN="$(nudge_resolve_python "$ROOT")" || exit 1

if ! "$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit(1)
PY
then
  echo "ERROR: Nudge verification requires Python 3.12+." >&2
  echo "Current interpreter: $PYTHON_BIN" >&2
  echo "Run scripts/bootstrap_mac.sh to create .venv, or set NUDGE_PYTHON=/path/to/python3.12." >&2
  exit 1
fi

run() {
  echo "+ $*"
  "$@"
}

echo "== Nudge public verification =="

run "$PYTHON_BIN" -m pytest tests/ -q

echo
echo "== Python compile checks =="
run "$PYTHON_BIN" -m compileall -q nudge

echo
echo "== CLI smoke checks =="
run bin/nudge --help >/dev/null
run bin/nudge do --help >/dev/null
run bin/nudge doctor --help >/dev/null
run bin/nudge daemon --help >/dev/null
run bin/nudge docs --help >/dev/null
run bin/nudge docs audit --help >/dev/null
run bin/nudge feedback interview --help >/dev/null
run bin/nudge reminders backfill-lists --help >/dev/null
run bin/nudge reminders reconcile-missing --help >/dev/null
run bin/nudge mcp --help >/dev/null
run bin/nudge do --json --help >/dev/null
run bin/nudge agent --help >/dev/null
run bin/nudge agent apply --help >/dev/null
run bin/nudge mcp serve --help >/dev/null
run bin/nudge daemon enqueue --help >/dev/null
run bin/nudge daemon queue --help >/dev/null
run bin/nudge daemon status --help >/dev/null
run bin/nudge daemon run --help >/dev/null
run bin/nudge daemon recover --help >/dev/null
run bin/nudge daemon retry --help >/dev/null
run bin/nudge daemon health --help >/dev/null
run bin/nudge daemon launchd --help >/dev/null
run bin/nudge daemon launchd install --help >/dev/null
run bin/nudge daemon launchd status --help >/dev/null
run bin/nudge daemon launchd start --help >/dev/null
run bin/nudge daemon launchd stop --help >/dev/null
run bin/nudge daemon launchd restart --help >/dev/null
run bin/nudge daemon launchd uninstall --help >/dev/null
run bin/nudge daemon app --help >/dev/null
run bin/nudge daemon app install --help >/dev/null
run bin/nudge daemon app status --help >/dev/null
run bin/nudge daemon app open --help >/dev/null
run bin/nudge daemon app uninstall --help >/dev/null
run bin/nudge reminders --help >/dev/null
run bin/nudge reminders sync-completed --help >/dev/null
run bin/nudge reminders backfill-ids --help >/dev/null
run bin/nudge daily --help >/dev/null
run bin/nudge daily sync --help >/dev/null
run bin/nudge db --help >/dev/null
run bin/nudge db backup --help >/dev/null
run bin/nudge db export --help >/dev/null
run bin/nudge db restore --help >/dev/null
run bin/nudge health --help >/dev/null
run bin/nudge health import --help >/dev/null
run bin/nudge health daily --help >/dev/null
run bin/nudge doctor --json --help >/dev/null
run bin/nudge dogfood --help >/dev/null
run bin/nudge dogfood weekly --help >/dev/null
run bin/nudge failures --help >/dev/null
run bin/nudge briefing --help >/dev/null
run bin/nudge review --help >/dev/null
run bin/nudge schedule --help >/dev/null
run bin/nudge habits --help >/dev/null
run bin/nudge log --help >/dev/null
run bin/nudge log parse --help >/dev/null
run bin/nudge check-in --help >/dev/null
run bin/nudge check-in parse --help >/dev/null
run bin/nudge trainer --help >/dev/null
run bin/nudge skills --help >/dev/null
run bin/nudge skills list >/dev/null
run bin/nudge skills show strength-basics-12w --json >/dev/null
run bin/nudge skills dry-run --help >/dev/null
run bin/nudge skills schedule --help >/dev/null
run bin/nudge profile --help >/dev/null
run bin/nudge feedback weekly-score --help >/dev/null

echo
echo "== Documentation audit =="
run bin/nudge docs audit --json >/dev/null

echo
echo "== Packaging checks =="
run scripts/check_package.sh

echo
echo "== Repository-local runtime state guard =="
for forbidden in \
  .nudge/nudge.db \
  .nudge/nudge.db-shm \
  .nudge/nudge.db-wal \
  nudge.db \
  nudge.db-shm \
  nudge.db-wal
do
  test ! -e "$forbidden"
done

echo
echo "Nudge public verification passed"
