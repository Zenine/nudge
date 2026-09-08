"""缺少状态目录配置时的 CLI 启动行为回归测试。

背景：`scripts/verify.sh` 与 CI 都会预先 export `NUDGE_STATE_DIR`，
因此“既无 `NUDGE_STATE_DIR` 也无 config.toml”这条路径是测试盲区。
这里用 subprocess 显式清掉相关环境变量，覆盖新用户 clone / pipx 安装后的首跑场景。
"""

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINT = PROJECT_ROOT / "nudge.py"


def _run_without_state_config(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    """在既无 NUDGE_STATE_DIR 也无任何可发现 config.toml 的环境里运行 CLI。"""
    env = dict(os.environ)
    env.pop("NUDGE_STATE_DIR", None)
    env.pop("NUDGE_TEST_STATE_DIR", None)
    env.pop("NUDGE_TEST_PARENT_STATE_DIR", None)
    # 指向不存在的 config，覆盖 NUDGE_CONFIG / 源码树 config.toml / XDG 三条发现路径。
    env["NUDGE_CONFIG"] = str(tmp_path / "missing" / "config.toml")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    existing_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{PROJECT_ROOT}{os.pathsep}{existing_path}" if existing_path else str(PROJECT_ROOT)
    )
    return subprocess.run(
        [sys.executable, str(ENTRY_POINT), *args],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_help_without_state_dir_config_exits_zero(tmp_path):
    result = _run_without_state_config(tmp_path, "--help")

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "RuntimeError" not in result.stderr
    assert "Usage:" in result.stdout


def test_docs_audit_without_state_dir_config_exits_zero(tmp_path):
    result = _run_without_state_config(tmp_path, "docs", "audit", "--json")

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "RuntimeError" not in result.stderr


def test_state_backed_command_without_state_dir_reports_click_exception(tmp_path):
    result = _run_without_state_config(tmp_path, "failures", "--json")

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    combined = result.stdout + result.stderr
    # 仍然 fail-closed，且保留 config.py 的三条修复指引。
    assert "Error:" in combined
    assert "NUDGE_STATE_DIR" in combined
    assert "[state].dir" in combined
    assert "--config" in combined
