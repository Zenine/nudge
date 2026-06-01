#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

run() {
  echo "+ $*"
  "$@"
}

echo "== Nudge public verification =="

run python3 -m pytest tests/ -q

echo
echo "== Python compile checks =="
run python3 -m compileall -q nudge

echo
echo "== CLI smoke checks =="
run bin/nudge --help >/dev/null
run bin/nudge --config config.example.toml --help >/dev/null
run bin/nudge --config config.example.toml doctor --help >/dev/null
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
