"""Tests for local CLI installation entrypoints."""

import os
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_nudge_console_script():
    """Editable installs should expose a global `nudge` command."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert data["project"]["requires-python"] == ">=3.12"
    assert data["project"]["scripts"]["nudge"] == "nudge.cli:main"
    assert set(data["project"]["dependencies"]) >= {"anthropic", "click", "openai"}
    assert data["tool"]["setuptools"]["package-data"]["nudge.apple"] == [
        "eventkit_calendar_events.swift",
        "eventkit_reminders_due_today.swift",
        "eventkit_reminders_mutate.swift",
    ]


def test_fixed_path_wrapper_runs_cli_help():
    """Other projects should be able to call ./bin/nudge by absolute path."""
    wrapper = ROOT / "bin" / "nudge"

    assert wrapper.exists()
    assert os.access(wrapper, os.X_OK)

    result = subprocess.run(
        [str(wrapper), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "Nudge" in result.stdout
    assert "briefing" in result.stdout


def test_fixed_path_wrapper_do_help_runs_from_arbitrary_cwd(tmp_path):
    """External projects should be able to call the fixed path from any cwd."""
    wrapper = ROOT / "bin" / "nudge"

    result = subprocess.run(
        [str(wrapper), "do", "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "Usage: nudge do [OPTIONS]" in result.stdout
    assert "--json" in result.stdout


def test_symlinked_wrapper_resolves_repo_root(tmp_path):
    """The global ~/.local/bin/nudge symlink should still find this repository."""
    wrapper = ROOT / "bin" / "nudge"
    symlink = tmp_path / "nudge"
    symlink.symlink_to(wrapper)

    result = subprocess.run(
        [str(symlink), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "Nudge" in result.stdout
    assert "briefing" in result.stdout


def test_fixed_path_wrapper_prefers_project_virtualenv():
    """普通用户不应需要把依赖安装到系统 Python。

    解释器解析已抽到 scripts/lib/python_env.sh，由 bin/nudge 与 scripts/verify.sh 共用，
    因此这里只断言 wrapper 确实走共享解析器且不自己静默回落。
    """
    content = (ROOT / "bin" / "nudge").read_text()

    assert 'source "$ROOT/scripts/lib/python_env.sh"' in content
    assert 'PYTHON_BIN="$(nudge_resolve_python "$ROOT")" || exit 1' in content
    assert 'exec "$PYTHON_BIN" "$ROOT/nudge.py" "$@"' in content
    assert 'exec python3 "$ROOT/nudge.py" "$@"' not in content


def _resolve_python(tmp_root: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """在临时 ROOT 下调用共享解析器，返回进程结果。"""
    lib = ROOT / "scripts" / "lib" / "python_env.sh"
    script = f'source "{lib}"\nnudge_resolve_python "{tmp_root}"\n'
    env = dict(os.environ)
    env.pop("NUDGE_PYTHON", None)
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env, timeout=30
    )


def test_python_resolver_prefers_explicit_nudge_python(tmp_path):
    result = _resolve_python(tmp_path, {"NUDGE_PYTHON": "/opt/custom/python3.12"})

    assert result.returncode == 0
    assert result.stdout.strip() == "/opt/custom/python3.12"


def test_python_resolver_uses_project_venv_when_executable(tmp_path):
    venv_py = tmp_path / ".venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("#!/bin/sh\n")
    venv_py.chmod(0o755)

    result = _resolve_python(tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == str(venv_py)


def test_python_resolver_falls_back_to_system_python_without_venv(tmp_path):
    """完全没有 .venv 是贡献者自管环境的正常用法，应回落而不是报错。"""
    result = _resolve_python(tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == "python3"


def test_python_resolver_fails_loudly_on_dangling_venv_symlink(tmp_path):
    """.venv 存在但解释器悬空时必须显式报错，不得静默回落到系统 python3。

    成因：2026-09 审阅发现 .venv/bin/python 曾长期悬空，verify.sh 静默降级到系统
    解释器，测试照样全绿——绿灯测的不是约定环境。
    """
    venv_py = tmp_path / ".venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.symlink_to(tmp_path / "does-not-exist" / "python3.12")

    result = _resolve_python(tmp_path)

    assert result.returncode != 0
    assert result.stdout.strip() != "python3"
    assert "悬空软链接" in result.stderr


def test_python_resolver_fails_loudly_when_venv_python_not_executable(tmp_path):
    venv_py = tmp_path / ".venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("#!/bin/sh\n")
    venv_py.chmod(0o644)

    result = _resolve_python(tmp_path)

    assert result.returncode != 0
    assert "没有可执行权限" in result.stderr


def test_install_script_installs_editable_package():
    """The helper script should install a PATH-friendly symlink."""
    script = ROOT / "scripts" / "install_cli.sh"

    assert script.exists()
    assert os.access(script, os.X_OK)

    content = script.read_text()
    assert "$HOME/.local/bin" in content
    assert "ln -sfn \"$ROOT/bin/nudge\" \"$TARGET\"" in content
    assert "nudge --help" in content


def test_bootstrap_mac_uses_project_virtualenv_not_system_pip():
    """一键安装应自动管理 .venv，避免触发 Homebrew PEP 668 错误。"""
    script = (ROOT / "scripts" / "bootstrap_mac.sh").read_text()

    assert 'VENV_DIR="$ROOT/.venv"' in script
    assert '"${PY_BIN}" -m venv "$VENV_DIR"' in script
    assert '"$VENV_PY" -m ensurepip --upgrade' in script
    assert '"$VENV_PY" -m pip install -r requirements.txt' in script
    assert '"${PY_BIN}" -m pip install -r requirements.txt' not in script


def test_bootstrap_mac_guards_against_rosetta_python_on_apple_silicon():
    """Apple Silicon 安装不能默默用 x86_64 Python 建虚拟环境。"""
    script = (ROOT / "scripts" / "bootstrap_mac.sh").read_text()

    assert 'APPLE_SILICON_PYTHON="/opt/homebrew/bin/python3"' in script
    assert 'python_arch()' in script
    assert 'platform.machine()' in script
    assert 'if [[ "$system_arch" == "arm64" && "$python_arch" != "arm64" && "$python_arch" != "arm64e" ]]; then' in script
    assert 'NUDGE_BOOTSTRAP_PYTHON' in script


def test_bootstrap_mac_rebuilds_rosetta_virtualenv():
    """已有 .venv 如果来自 Rosetta，应备份并重建。"""
    script = (ROOT / "scripts" / "bootstrap_mac.sh").read_text()

    assert 'ensure_native_virtualenv()' in script
    assert '现有 .venv 使用的是 ${venv_arch}' in script
    assert 'mv "$VENV_DIR" "$backup_dir"' in script


def test_bootstrap_launchd_installs_daily_sync_job():
    """launchd bootstrap 应安装 daily sync，让 docs audit 进入自动维护闭环。"""
    script = (ROOT / "scripts" / "bootstrap_launchd.sh").read_text()

    assert 'DAILY_SYNC_LABEL="com.nudge.daily-sync"' in script
    assert "render_daily_sync_plist" in script
    assert "<string>daily</string>" in script
    assert "<string>sync</string>" in script
    assert "<string>--apply</string>" in script
    assert "<string>--json</string>" in script
    assert 'check_label "$DAILY_SYNC_LABEL"' in script


def test_bootstrap_launchd_long_help_prints_usage():
    """`--help` 不应静默退出。"""
    script = ROOT / "scripts" / "bootstrap_launchd.sh"

    result = subprocess.run(
        [str(script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "daily-sync" in result.stdout
