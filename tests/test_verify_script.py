"""Public-safe tests for the project verification entrypoint."""

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify.sh"


def test_verify_script_resolves_python_312_before_running_checks():
    content = VERIFY.read_text(encoding="utf-8")

    assert "PYTHON_BIN=" in content
    assert "sys.version_info < (3, 12)" in content
    assert '"$PYTHON_BIN" -m pytest tests/ -q' in content
    assert '"$PYTHON_BIN" -m compileall -q nudge' in content
    assert "python3 -m pytest tests/ -q" not in content
    assert "python3 -m compileall -q nudge" not in content


def test_verify_script_reports_python_version_before_import_errors(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ $# -eq 0 ]]; then cat >/dev/null; exit 1; fi\n"
        "echo 'fake python should not run project code' >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env.pop("NUDGE_PYTHON", None)

    result = subprocess.run(
        [str(VERIFY)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 1
    assert "Nudge public verification requires Python 3.12+" in result.stderr
    assert "tomllib" not in result.stderr
