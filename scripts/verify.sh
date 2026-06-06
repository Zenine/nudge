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
run bin/nudge agent --help >/dev/null
run bin/nudge briefing --help >/dev/null
run bin/nudge daily --help >/dev/null
run bin/nudge daily sync --help >/dev/null
run bin/nudge daemon --help >/dev/null
run bin/nudge docs --help >/dev/null
run bin/nudge docs audit --help >/dev/null
run bin/nudge --config config.example.toml doctor --help >/dev/null
run bin/nudge do --help >/dev/null
run bin/nudge doctor --help >/dev/null
run bin/nudge health --help >/dev/null
run bin/nudge log --help >/dev/null
run bin/nudge mcp --help >/dev/null
run bin/nudge reminders --help >/dev/null
run bin/nudge review --help >/dev/null
run bin/nudge skills --help >/dev/null
run bin/nudge trainer --help >/dev/null

echo
echo "== i18n drift checks =="
run python3 scripts/check-i18n-drift.py

echo
echo "== VitePress docs build =="
(
  cd docs
  run npm run docs:build
)

echo
echo "== Documentation audit =="
run bin/nudge docs audit --json >/dev/null

echo
echo "Nudge public verification passed"
