#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

run() {
  echo "+ $*"
  "$@"
}

echo "== Nudge public verification =="

if [[ -d tests ]]; then
  run python3 -m pytest tests/ -q
else
  echo "+ python3 -m pytest tests/ -q (skipped: public export has no tests directory yet)"
fi

echo
echo "== CLI smoke checks =="
run bin/nudge --help >/dev/null
run bin/nudge do --help >/dev/null
run bin/nudge doctor --help >/dev/null
run bin/nudge daemon --help >/dev/null
run bin/nudge mcp --help >/dev/null

echo
echo "Nudge public verification passed"
