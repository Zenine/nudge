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
import importlib.util
import sys

if sys.version_info < (3, 12):
    raise SystemExit("Nudge packaging checks require Python 3.12+.")
if importlib.util.find_spec("build") is None:
    raise SystemExit(
        "Python package 'build' is not installed. Install it in your local "
        "development environment, then rerun scripts/check_package.sh. "
        "This script does not install dependencies or use the network."
    )
PY
then
  exit 1
fi

rm -rf dist build *.egg-info

echo "== Build wheel and sdist without network/upload =="
"$PYTHON_BIN" -m build --no-isolation --sdist --wheel --outdir dist

echo

echo "== Inspect package artifacts =="
"$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

root = Path.cwd()
dist = root / "dist"
wheels = sorted(dist.glob("nudge_ai_life_coach-*.whl"))
sdists = sorted(dist.glob("nudge_ai_life_coach-*.tar.gz"))

if len(wheels) != 1:
    raise SystemExit(f"Expected exactly one wheel, found {len(wheels)}: {wheels}")
if len(sdists) != 1:
    raise SystemExit(f"Expected exactly one sdist, found {len(sdists)}: {sdists}")

required = {
    "nudge/apple/eventkit_calendar_events.swift",
    "nudge/apple/eventkit_reminders_due_today.swift",
    "nudge/apple/eventkit_reminders_mutate.swift",
    "nudge/skills/builtins/deep-learning-sprint-4w.yaml",
    "nudge/skills/builtins/deep-work-weekly-rhythm.yaml",
    "nudge/skills/builtins/strength-basics-12w.yaml",
}

forbidden_prefixes = (
    "tests/",
    ".nudge/",
    "dist/",
    "build/",
)
forbidden_suffixes = (
    ".pyc",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".zip",  # Apple Health export archives or other local snapshots
)
forbidden_names = {
    "config.toml",
    ".env",
}
forbidden_fragments = (
    "Health export",
    "export.xml",
    "apple_health_export",
)


def wheel_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as zf:
        return set(zf.namelist())


def sdist_names(path: Path) -> set[str]:
    with tarfile.open(path, "r:gz") as tf:
        names = set()
        for member in tf.getmembers():
            parts = Path(member.name).parts
            normalized = "/".join(parts[1:]) if len(parts) > 1 else member.name
            if normalized:
                names.add(normalized)
        return names


def check_artifact(label: str, names: set[str]) -> None:
    missing = sorted(required - names)
    if missing:
        raise SystemExit(f"{label} is missing required package data: {missing}")

    forbidden = []
    for name in sorted(names):
        basename = Path(name).name
        if name.startswith(forbidden_prefixes):
            forbidden.append(name)
        elif name.endswith(forbidden_suffixes):
            forbidden.append(name)
        elif basename in forbidden_names:
            forbidden.append(name)
        elif any(fragment in name for fragment in forbidden_fragments):
            forbidden.append(name)
    if forbidden:
        raise SystemExit(
            f"{label} contains files that must not ship in public packages "
            f"(tests, private config, local DB, or Health export data): {forbidden}"
        )

    print(f"{label}: {len(names)} files inspected")


check_artifact("wheel", wheel_names(wheels[0]))
check_artifact("sdist", sdist_names(sdists[0]))
print("Package contents look public-safe")
PY
