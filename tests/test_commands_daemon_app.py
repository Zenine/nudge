"""Tests for daemon macOS graphical control app commands."""

import json
import os
import subprocess

from click.testing import CliRunner

from nudge.cli import cli


def run_daemon_command(args, home_dir, **kwargs):
    env = dict(os.environ)
    env["HOME"] = str(home_dir)
    return CliRunner().invoke(cli, args, prog_name="nudge", env=env, **kwargs)


def test_daemon_app_install_compiles_control_app_and_login_item(monkeypatch, tmp_path):
    calls = []

    def _fake_run(cmd, capture_output=True, text=True, check=False):
        del capture_output, text, check
        calls.append(cmd)
        if cmd[0] == "osacompile":
            app_path = cmd[cmd.index("-o") + 1]
            os.makedirs(app_path, exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("nudge.daemon_control_app.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nudge.daemon_control_app.subprocess.run", _fake_run)

    result = run_daemon_command(["daemon", "app", "install", "--login-item", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    app_path = tmp_path / "Applications" / "Nudge Daemon Health.app"
    script_path = tmp_path / ".nudge" / "Nudge Daemon Health.applescript"

    assert payload["ok"] is True
    assert payload["action"] == "install"
    assert payload["app_exists"] is True
    assert payload["login_item_requested"] is True
    assert app_path.exists()
    assert script_path.exists()

    script_text = script_path.read_text(encoding="utf-8")
    assert "daemon health" in script_text
    assert "daemon launchd restart" in script_text
    assert "com.nudge.agent.err.log" in script_text
    assert "sw_vers -productVersion" in script_text
    assert "sysctl -n hw.model" in script_text
    assert "uname -m" in script_text
    assert "系统：" in script_text
    assert "display dialog" in script_text

    assert any(call[:3] == ["osacompile", "-o", str(app_path)] for call in calls)
    assert any(call[0] == "osascript" and "make login item" in call[2] for call in calls)


def test_daemon_app_status_reports_app_and_login_item(monkeypatch, tmp_path):
    def _fake_run(cmd, capture_output=True, text=True, check=False):
        del capture_output, text, check
        if cmd[0] == "osascript":
            return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("nudge.daemon_control_app.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nudge.daemon_control_app.subprocess.run", _fake_run)

    app_path = tmp_path / "Applications" / "Nudge Daemon Health.app"
    app_path.mkdir(parents=True)

    result = run_daemon_command(["daemon", "app", "status", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["supported"] is True
    assert payload["app_exists"] is True
    assert payload["login_item_installed"] is True
    assert payload["app_path"] == str(app_path)


def test_daemon_app_open_uses_macos_open(monkeypatch, tmp_path):
    calls = []

    def _fake_run(cmd, capture_output=True, text=True, check=False):
        del capture_output, text, check
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("nudge.daemon_control_app.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nudge.daemon_control_app.subprocess.run", _fake_run)

    app_path = tmp_path / "Applications" / "Nudge Daemon Health.app"
    app_path.mkdir(parents=True)

    result = run_daemon_command(["daemon", "app", "open", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["action"] == "open"
    assert ["open", str(app_path)] in calls
