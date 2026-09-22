"""Tests for `nudge daemon` commands."""

import json
import os
import subprocess

import pytest
from click.testing import CliRunner

from nudge.cli import cli


def run_daemon_command(args, home_dir, **kwargs):
    env = dict(os.environ)
    env["HOME"] = str(home_dir)
    return CliRunner().invoke(cli, args, prog_name="nudge", env=env, **kwargs)


def _patch_agent_request_success(monkeypatch, base_payload=None):
    def _stub(request, config):
        del config
        return ({
            "ok": True,
            "request_id": request.get("request_id"),
            "source": request.get("source"),
            "dry_run": False,
            "actions": base_payload or [],
        }, 0)

    monkeypatch.setattr("nudge.commands.daemon.apply_agent_request", _stub)


@pytest.fixture(autouse=True)
def isolate_state_db(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")


def test_daemon_enqueue_and_queue_command_is_listable(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.commands.daemon.load_config", lambda: {"llm": {"provider": "qwen"}})

    request = {
        "request_id": "req-cli",
        "source": "planner-unit",
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "测试会议",
                "start": "2026-04-27 09:00",
                "end": "2026-04-27 10:00",
            }
        ],
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")

    result = run_daemon_command(["daemon", "enqueue", "--type", "agent.apply", "--file", str(request_path), "--json"], tmp_path)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["request_id"] == "req-cli"

    queue_output = run_daemon_command(["daemon", "queue", "--status", "queued", "--json"], tmp_path)
    assert queue_output.exit_code == 0
    queue_payload = json.loads(queue_output.output)
    assert queue_payload["count"] == 1
    assert queue_payload["items"][0]["request_id"] == "req-cli"


def test_daemon_run_executes_queued_agent_apply(monkeypatch, tmp_path):
    from nudge.state import enqueue_agent_command, get_daemon_runtime_status

    monkeypatch.setattr("nudge.commands.daemon.load_config", lambda: {"llm": {"provider": "qwen"}})
    _patch_agent_request_success(monkeypatch, base_payload=[{"ok": True}])

    req_id = enqueue_agent_command(
        payload={"request_id": "req-run", "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id="req-run",
    )
    result = run_daemon_command(["daemon", "run", "--once", "--verbose"], tmp_path)
    assert result.exit_code == 0, result.output
    assert req_id == "req-run"
    assert f"processing {req_id}" in result.output

    status = get_daemon_runtime_status()
    assert status["succeeded"] == 1
    assert status["failed"] == 0
    assert status["last_run_request_id"] == req_id


def test_daemon_run_config_path_is_used_for_agent_apply(monkeypatch, tmp_path):
    from nudge.state import configure_state, enqueue_agent_command, get_daemon_runtime_status

    config_path = tmp_path / "custom.toml"
    configured_state_dir = tmp_path / "configured-state"
    config = {"llm": {"provider": "qwen"}, "state": {"dir": str(configured_state_dir)}, "marker": "custom"}
    load_config_calls = []
    applied_configs = []

    configure_state(config)
    req_id = enqueue_agent_command(
        payload={"request_id": "req-run-config", "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id="req-run-config",
    )

    def _fake_load_config(path=None):
        load_config_calls.append(path)
        assert path == str(config_path)
        return config

    def _stub(request, config):
        applied_configs.append(config)
        return ({
            "ok": True,
            "request_id": request.get("request_id"),
            "source": request.get("source"),
            "dry_run": False,
            "actions": [],
        }, 0)

    monkeypatch.setattr("nudge.cli.load_config", lambda: config)
    monkeypatch.setattr("nudge.commands.daemon.load_config", _fake_load_config)
    monkeypatch.setattr("nudge.commands.daemon.apply_agent_request", _stub)

    result = run_daemon_command(["daemon", "run", "--config", str(config_path), "--once"], tmp_path)

    assert result.exit_code == 0, result.output
    assert req_id == "req-run-config"
    assert load_config_calls == [str(config_path)]
    assert applied_configs == [config]
    status = get_daemon_runtime_status()
    assert status["succeeded"] == 1


def test_daemon_run_once_processes_single_item(monkeypatch, tmp_path):
    from nudge.state import enqueue_agent_command, list_queued_commands

    monkeypatch.setattr("nudge.commands.daemon.load_config", lambda: {"llm": {"provider": "qwen"}})
    _patch_agent_request_success(monkeypatch, base_payload=[{"ok": True}])

    first_id = "req-run-once-1"
    second_id = "req-run-once-2"
    enqueue_agent_command(
        payload={"request_id": first_id, "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id=first_id,
    )
    enqueue_agent_command(
        payload={"request_id": second_id, "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id=second_id,
    )

    result = run_daemon_command(["daemon", "run", "--once", "--verbose"], tmp_path)
    assert result.exit_code == 0, result.output
    assert first_id in result.output
    assert second_id not in result.output

    queued = list_queued_commands(status="queued")
    assert len(queued) == 1
    assert queued[0]["request_id"] == second_id


def test_daemon_run_marks_command_failed_when_engine_raises_and_continues(monkeypatch, tmp_path):
    from nudge.state import enqueue_agent_command, get_daemon_runtime_status, list_queued_commands

    monkeypatch.setattr("nudge.commands.daemon.load_config", lambda: {"llm": {"provider": "qwen"}})
    calls = []

    def _stub(request, config):
        del config
        calls.append(request["request_id"])
        if request["request_id"] == "req-raises":
            raise RuntimeError("boom from agent engine")
        return ({
            "ok": True,
            "request_id": request.get("request_id"),
            "source": request.get("source"),
            "dry_run": False,
            "actions": [],
        }, 0)

    monkeypatch.setattr("nudge.commands.daemon.apply_agent_request", _stub)
    enqueue_agent_command(
        payload={"request_id": "req-raises", "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id="req-raises",
    )
    enqueue_agent_command(
        payload={"request_id": "req-after-raises", "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id="req-after-raises",
    )

    result = run_daemon_command(["daemon", "run", "--max-empty-cycles", "1", "--verbose"], tmp_path)

    assert result.exit_code == 0, result.output
    assert calls == ["req-raises", "req-after-raises"]
    assert "req-raises: failed" in result.output
    assert "req-after-raises: succeeded" in result.output
    failed = list_queued_commands(status="failed")
    assert [row["request_id"] for row in failed] == ["req-raises"]
    assert "boom from agent engine" in failed[0]["last_error"]
    status = get_daemon_runtime_status()
    assert status["failed"] == 1
    assert status["succeeded"] == 1


def test_daemon_recover_command_requeues_stale_running_command(monkeypatch, tmp_path):
    from nudge.state import _get_conn, claim_next_queued_command, enqueue_agent_command, list_queued_commands

    monkeypatch.setattr("nudge.commands.daemon.load_config", lambda: {"llm": {"provider": "qwen"}})
    enqueue_agent_command(
        payload={"request_id": "req-stale", "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id="req-stale",
    )
    assert claim_next_queued_command()["request_id"] == "req-stale"

    conn = _get_conn()
    conn.execute(
        "UPDATE command_queue SET started_at = '2026-04-27 09:00:00' WHERE request_id = 'req-stale'"
    )
    conn.commit()
    conn.close()

    result = run_daemon_command(
        ["daemon", "recover", "--stale-minutes", "10", "--max-attempts", "3", "--json"],
        tmp_path,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["requeued_count"] == 1
    assert payload["dead_lettered_count"] == 0
    assert payload["requeued"][0]["request_id"] == "req-stale"

    queued = list_queued_commands(status="queued")
    assert [row["request_id"] for row in queued] == ["req-stale"]


def test_daemon_run_auto_recovers_stale_running_command_before_processing(monkeypatch, tmp_path):
    from nudge.state import _get_conn, claim_next_queued_command, enqueue_agent_command, list_queued_commands

    monkeypatch.setattr("nudge.commands.daemon.load_config", lambda: {"llm": {"provider": "qwen"}})
    _patch_agent_request_success(monkeypatch, base_payload=[{"ok": True}])
    enqueue_agent_command(
        payload={"request_id": "req-auto-recover", "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id="req-auto-recover",
    )
    assert claim_next_queued_command()["request_id"] == "req-auto-recover"
    enqueue_agent_command(
        payload={"request_id": "req-next", "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id="req-next",
    )

    conn = _get_conn()
    conn.execute(
        """
        UPDATE command_queue
        SET started_at = '2026-04-27 09:00:00'
        WHERE request_id = 'req-auto-recover'
        """
    )
    conn.commit()
    conn.close()

    result = run_daemon_command(
        ["daemon", "run", "--once", "--recover-stale-minutes", "10", "--max-attempts", "3", "--verbose"],
        tmp_path,
    )

    assert result.exit_code == 0, result.output
    assert "recovered stale commands: requeued=1 dead_lettered=0" in result.output
    assert "processing req-auto-recover" in result.output
    assert "req-auto-recover: succeeded" in result.output

    queued = list_queued_commands(status="queued")
    assert [row["request_id"] for row in queued] == ["req-next"]


def test_daemon_recover_command_moves_exhausted_stale_command_to_dead_letter(monkeypatch, tmp_path):
    from nudge.state import _get_conn, claim_next_queued_command, enqueue_agent_command, list_queued_commands

    monkeypatch.setattr("nudge.commands.daemon.load_config", lambda: {"llm": {"provider": "qwen"}})
    enqueue_agent_command(
        payload={"request_id": "req-dead", "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id="req-dead",
    )
    assert claim_next_queued_command()["request_id"] == "req-dead"

    conn = _get_conn()
    conn.execute(
        """
        UPDATE command_queue
        SET started_at = '2026-04-27 09:00:00',
            attempts = 3
        WHERE request_id = 'req-dead'
        """
    )
    conn.commit()
    conn.close()

    result = run_daemon_command(
        ["daemon", "recover", "--stale-minutes", "10", "--max-attempts", "3", "--json"],
        tmp_path,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["requeued_count"] == 0
    assert payload["dead_lettered_count"] == 1
    assert payload["dead_lettered"][0]["request_id"] == "req-dead"

    dead_letters = list_queued_commands(status="dead_letter")
    assert [row["request_id"] for row in dead_letters] == ["req-dead"]


def test_daemon_retry_command_requeues_dead_letter(monkeypatch, tmp_path):
    from nudge.state import _get_conn, enqueue_agent_command, list_queued_commands

    monkeypatch.setattr("nudge.commands.daemon.load_config", lambda: {"llm": {"provider": "qwen"}})
    enqueue_agent_command(
        payload={"request_id": "req-retry", "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id="req-retry",
    )
    conn = _get_conn()
    conn.execute(
        """
        UPDATE command_queue
        SET status = 'dead_letter',
            attempts = 3,
            started_at = '2026-04-27 09:00:00',
            finished_at = '2026-04-27 09:30:00',
            last_error = 'too many stale attempts',
            last_exit_code = 1
        WHERE request_id = 'req-retry'
        """
    )
    conn.commit()
    conn.close()

    result = run_daemon_command(["daemon", "retry", "--request-id", "req-retry", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["item"]["request_id"] == "req-retry"
    assert payload["item"]["status"] == "queued"
    assert payload["item"]["attempts"] == 0

    queued = list_queued_commands(status="queued")
    assert [row["request_id"] for row in queued] == ["req-retry"]


def test_daemon_status_reports_dead_letter_count(monkeypatch, tmp_path):
    from nudge.state import _get_conn, enqueue_agent_command

    monkeypatch.setattr("nudge.commands.daemon.load_config", lambda: {"llm": {"provider": "qwen"}})
    enqueue_agent_command(
        payload={"request_id": "req-status-dead", "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id="req-status-dead",
    )
    conn = _get_conn()
    conn.execute("UPDATE command_queue SET status = 'dead_letter' WHERE request_id = 'req-status-dead'")
    conn.commit()
    conn.close()

    result = run_daemon_command(["daemon", "status", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dead_letter"] == 1


def test_daemon_launchd_install_writes_plist_and_bootstraps(monkeypatch, tmp_path):
    calls = []

    def _fake_run(cmd, capture_output=True, text=True, check=False):
        del capture_output, text, check
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("nudge.commands.daemon.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nudge.commands.daemon.subprocess.run", _fake_run)
    monkeypatch.setattr("nudge.commands.daemon.os.getuid", lambda: 501)

    result = run_daemon_command(["daemon", "launchd", "install", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["action"] == "install"
    assert payload["label"] == "com.nudge.agent"
    assert payload["plist_exists"] is True

    plist_path = tmp_path / "Library" / "LaunchAgents" / "com.nudge.agent.plist"
    plist_text = plist_path.read_text(encoding="utf-8")
    assert "<string>daemon</string>" in plist_text
    assert "<string>run</string>" in plist_text
    assert "NUDGE_DAEMON_STALE_MINUTES" in plist_text
    assert "NUDGE_DAEMON_MAX_ATTEMPTS" in plist_text
    assert "NUDGE_DAEMON_MAX_QUEUE_DEPTH" in plist_text

    assert ["launchctl", "bootout", "gui/501/com.nudge.agent"] in calls
    assert ["launchctl", "bootstrap", "gui/501", str(plist_path)] in calls


def test_daemon_launchd_install_writes_config_path_into_plist(monkeypatch, tmp_path):
    calls = []
    config_path = tmp_path / "custom.toml"

    def _fake_run(cmd, capture_output=True, text=True, check=False):
        del capture_output, text, check
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("nudge.commands.daemon.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nudge.commands.daemon.subprocess.run", _fake_run)
    monkeypatch.setattr("nudge.commands.daemon.os.getuid", lambda: 501)

    result = run_daemon_command(
        ["daemon", "launchd", "install", "--config", str(config_path), "--json"],
        tmp_path,
    )

    assert result.exit_code == 0, result.output
    plist_path = tmp_path / "Library" / "LaunchAgents" / "com.nudge.agent.plist"
    plist_text = plist_path.read_text(encoding="utf-8")
    assert "<string>--config</string>" in plist_text
    assert f"<string>{config_path}</string>" in plist_text
    assert ["launchctl", "bootstrap", "gui/501", str(plist_path)] in calls


def test_daemon_launchd_status_reports_loaded_json(monkeypatch, tmp_path):
    def _fake_run(cmd, capture_output=True, text=True, check=False):
        del capture_output, text, check
        if cmd[:2] == ["launchctl", "print"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="state = running", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("nudge.commands.daemon.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nudge.commands.daemon.subprocess.run", _fake_run)
    monkeypatch.setattr("nudge.commands.daemon.os.getuid", lambda: 501)

    plist_dir = tmp_path / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True)
    (plist_dir / "com.nudge.agent.plist").write_text("<plist />", encoding="utf-8")

    result = run_daemon_command(["daemon", "launchd", "status", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["launchd"]["supported"] is True
    assert payload["launchd"]["loaded"] is True
    assert payload["launchd"]["plist_exists"] is True
    assert payload["launchd"]["state_hint"] == "running"


def test_daemon_launchd_stop_unloads_without_deleting_plist(monkeypatch, tmp_path):
    calls = []

    def _fake_run(cmd, capture_output=True, text=True, check=False):
        del capture_output, text, check
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("nudge.commands.daemon.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nudge.commands.daemon.subprocess.run", _fake_run)
    monkeypatch.setattr("nudge.commands.daemon.os.getuid", lambda: 501)

    plist_dir = tmp_path / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True)
    plist_path = plist_dir / "com.nudge.agent.plist"
    plist_path.write_text("<plist />", encoding="utf-8")

    result = run_daemon_command(["daemon", "launchd", "stop", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["action"] == "stop"
    assert plist_path.exists()
    assert ["launchctl", "bootout", "gui/501/com.nudge.agent"] in calls


def test_daemon_health_reports_launchd_and_queue_issues(monkeypatch, tmp_path):
    from nudge.state import _get_conn, claim_next_queued_command, enqueue_agent_command

    def _fake_run(cmd, capture_output=True, text=True, check=False):
        del capture_output, text, check
        if cmd[:2] == ["launchctl", "print"]:
            return subprocess.CompletedProcess(cmd, 3, stdout="", stderr="not loaded")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("nudge.commands.daemon.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nudge.commands.daemon.subprocess.run", _fake_run)
    monkeypatch.setattr("nudge.commands.daemon.os.getuid", lambda: 501)

    enqueue_agent_command(
        payload={"request_id": "req-stale-health", "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id="req-stale-health",
    )
    assert claim_next_queued_command()["request_id"] == "req-stale-health"
    enqueue_agent_command(
        payload={"request_id": "req-dead-health", "source": "planner-unit", "actions": []},
        request_type="agent.apply",
        source="planner-unit",
        request_id="req-dead-health",
    )
    conn = _get_conn()
    conn.execute(
        """
        UPDATE command_queue
        SET started_at = '2026-04-27 09:00:00'
        WHERE request_id = 'req-stale-health'
        """
    )
    conn.execute("UPDATE command_queue SET status = 'dead_letter' WHERE request_id = 'req-dead-health'")
    conn.commit()
    conn.close()

    result = run_daemon_command(["daemon", "health", "--stale-minutes", "10", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["status"] == "fail"
    assert payload["queue"]["dead_letter"] == 1
    assert payload["stale_running"]["count"] == 1
    assert payload["launchd"]["loaded"] is False
    assert {issue["code"] for issue in payload["issues"]} == {
        "LAUNCHD_PLIST_MISSING",
        "LAUNCHD_NOT_LOADED",
        "STALE_RUNNING_COMMANDS",
        "DEAD_LETTER_COMMANDS",
    }
    policy_by_code = {policy["code"]: policy for policy in payload["alert_policy"]}
    assert policy_by_code["LAUNCHD_NOT_LOADED"]["touch"] == "briefing+notification"
    assert policy_by_code["STALE_RUNNING_COMMANDS"]["operator_action"] == "recover"
    assert policy_by_code["DEAD_LETTER_COMMANDS"]["touch"] == "briefing+notification"
    assert policy_by_code["DEAD_LETTER_COMMANDS"]["escalation"] == "manual_review_required"


def test_daemon_health_notify_sends_notification_for_issues(monkeypatch, tmp_path):
    notifications = []

    def _fake_run(cmd, capture_output=True, text=True, check=False):
        del capture_output, text, check
        if cmd[:2] == ["launchctl", "print"]:
            return subprocess.CompletedProcess(cmd, 3, stdout="", stderr="not loaded")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def _fake_notify(title, message, subtitle=None, sound="default"):
        notifications.append({
            "title": title,
            "message": message,
            "subtitle": subtitle,
            "sound": sound,
        })
        return True, ""

    monkeypatch.setattr("nudge.commands.daemon.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nudge.commands.daemon.subprocess.run", _fake_run)
    monkeypatch.setattr("nudge.commands.daemon.os.getuid", lambda: 501)
    monkeypatch.setattr("nudge.commands.daemon.notify", _fake_notify)

    result = run_daemon_command(["daemon", "health", "--notify", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["notification"]["sent"] is True
    assert len(notifications) == 1
    assert notifications[0]["title"] == "Nudge daemon 告警"
    assert notifications[0]["subtitle"] == "warn"
    assert "LAUNCHD_PLIST_MISSING" in notifications[0]["message"]
    assert "nudge daemon health" in notifications[0]["message"]


def test_daemon_health_ok_when_launchd_loaded_and_queue_clean(monkeypatch, tmp_path):
    def _fake_run(cmd, capture_output=True, text=True, check=False):
        del capture_output, text, check
        if cmd[:2] == ["launchctl", "print"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="state = running", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("nudge.commands.daemon.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nudge.commands.daemon.subprocess.run", _fake_run)
    monkeypatch.setattr("nudge.commands.daemon.os.getuid", lambda: 501)

    plist_dir = tmp_path / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True)
    (plist_dir / "com.nudge.agent.plist").write_text("<plist />", encoding="utf-8")

    result = run_daemon_command(["daemon", "health", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["issues"] == []
    assert payload["launchd"]["loaded"] is True


def test_daemon_health_notify_is_quiet_when_healthy(monkeypatch, tmp_path):
    notifications = []

    def _fake_run(cmd, capture_output=True, text=True, check=False):
        del capture_output, text, check
        if cmd[:2] == ["launchctl", "print"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="state = running", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("nudge.commands.daemon.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nudge.commands.daemon.subprocess.run", _fake_run)
    monkeypatch.setattr("nudge.commands.daemon.os.getuid", lambda: 501)
    monkeypatch.setattr(
        "nudge.commands.daemon.notify",
        lambda title, message, subtitle=None, sound="default": notifications.append((title, message)) or (True, ""),
    )

    plist_dir = tmp_path / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True)
    (plist_dir / "com.nudge.agent.plist").write_text("<plist />", encoding="utf-8")

    result = run_daemon_command(["daemon", "health", "--notify", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["notification"]["sent"] is False
    assert notifications == []
