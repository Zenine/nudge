#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${NUDGE_PYTHON:-}"
if [[ -z "$PYTHON_BIN" && -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

if ! "$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit(1)
PY
then
  echo "ERROR: Nudge public verification requires Python 3.12+." >&2
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
run bin/nudge mcp --help >/dev/null

echo
echo "== Documentation audit =="
run bin/nudge docs audit --json >/dev/null

echo
echo "Nudge public verification passed"
