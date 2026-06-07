"""Smoke tests for installed package surfaces and local entry wrappers."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_python(code: str, *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd or PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_local_wrappers_can_load_cli():
    code = """
import runpy
from pathlib import Path

root = Path.cwd()
bin_text = (root / "bin" / "nudge").read_text(encoding="utf-8")
assert 'nudge.py' in bin_text
module_globals = runpy.run_path(str(root / "nudge.py"), run_name="nudge_smoke")
assert module_globals["main"].__module__ == "nudge.cli"
"""

    result = _run_python(code)

    assert result.returncode == 0, result.stderr


def test_console_script_metadata_points_to_cli_main():
    entry_points = importlib.metadata.entry_points(group="console_scripts")
    local_entry_points = [ep for ep in entry_points if ep.name == "nudge" and ep.value == "nudge.cli:main"]

    pyproject_text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'nudge = "nudge.cli:main"' in pyproject_text
    assert local_entry_points or "nudge-ai-life-coach" not in {
        dist.metadata["Name"] for dist in importlib.metadata.distributions()
    }


def test_site_package_imports_new_modules_and_exposes_entry_point(tmp_path):
    site_packages = tmp_path / "site-packages"
    installed_package = site_packages / "nudge"
    work_dir = tmp_path / "work"
    dist_info = site_packages / "nudge_ai_life_coach-0.5.1.dist-info"

    shutil.copytree(PROJECT_ROOT / "nudge", installed_package, ignore=shutil.ignore_patterns("__pycache__"))
    work_dir.mkdir()
    dist_info.mkdir(parents=True)

    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_find = pyproject["tool"]["setuptools"]["packages"]["find"]
    script_target = pyproject["project"]["scripts"]["nudge"]
    version = pyproject["project"]["version"]

    assert "nudge*" in package_find["include"]
    assert "tests*" in package_find["exclude"]

    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: nudge-ai-life-coach\nVersion: {version}\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        f"[console_scripts]\nnudge = {script_target}\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(site_packages)
    code = """
import importlib
import importlib.metadata

for module_name in ("nudge.runtime", "nudge.version", "nudge.apple.tsv"):
    importlib.import_module(module_name)

dist = importlib.metadata.distribution("nudge-ai-life-coach")
matches = [ep for ep in dist.entry_points if ep.group == "console_scripts" and ep.name == "nudge"]
assert [ep.value for ep in matches] == ["nudge.cli:main"]
"""

    smoke = subprocess.run(
        [sys.executable, "-c", code],
        cwd=work_dir,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert smoke.returncode == 0, smoke.stderr
