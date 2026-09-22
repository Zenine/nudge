"""Tests for nudge failures command."""

import json
import os

from click.testing import CliRunner

from nudge.cli import cli
from nudge.state import log_action, update_action_status


def run_cli(args, home_dir):
    env = dict(os.environ)
    env["HOME"] = str(home_dir)
    return CliRunner().invoke(cli, args, prog_name="nudge", env=env)


def test_failures_command_outputs_text_report(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.commands.failures.datetime", _FixedDateTime)
    log_action(action_type="reminder", summary="补记录早餐", scheduled_at="2026-04-27 08:00", status="pending")

    result = run_cli(["failures", "--overdue-hours", "24"], tmp_path)

    assert result.exit_code == 0, result.output
    assert "失败/阻塞可见性" in result.output
    assert "overdue=1" in result.output
    assert "补记录早餐" in result.output
    assert "nudge log done" in result.output


def test_failures_command_outputs_json_payload(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.commands.failures.datetime", _FixedDateTime)
    action_id = log_action(action_type="calendar_event", summary="等医生回复", scheduled_at="2026-04-27 09:00")
    update_action_status(action_id, "blocked", feedback={"reason": "waiting_on_other"})

    result = run_cli(["failures", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["report"]["summary"]["blocked_open"] == 1
    assert payload["report"]["summary"]["missing_next_action"] == 1
    assert payload["report"]["blocked_open"][0]["id"] == action_id


class _FixedDateTime:
    @classmethod
    def now(cls):
        from datetime import datetime

        return datetime(2026, 4, 28, 12, 0)


def test_failures_notify_sends_local_notification_when_issues_exist(monkeypatch, tmp_path):
    notifications = []

    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.commands.failures.datetime", _FixedDateTime)
    monkeypatch.setattr(
        "nudge.commands.failures.notify",
        lambda title, message, subtitle=None, sound="default": notifications.append({
            "title": title,
            "message": message,
            "subtitle": subtitle,
            "sound": sound,
        }) or (True, ""),
    )
    log_action(action_type="reminder", summary="补记录早餐", scheduled_at="2026-04-27 08:00", status="pending")

    result = run_cli(["failures", "--notify", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["notification"]["sent"] is True
    assert len(notifications) == 1
    assert notifications[0]["title"] == "Nudge 失败/阻塞待跟进"
    assert notifications[0]["subtitle"] == "overdue=1 blocked=0"
    assert "补记录早餐" in notifications[0]["message"]
    assert "nudge failures" in notifications[0]["message"]


def test_failures_notify_fires_for_due_soon_only(monkeypatch, tmp_path):
    notifications = []

    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.commands.failures.datetime", _FixedDateTime)
    monkeypatch.setattr(
        "nudge.commands.failures.notify",
        lambda title, message, subtitle=None, sound="default": notifications.append({
            "title": title, "message": message, "subtitle": subtitle,
        }) or (True, ""),
    )
    # Only an upcoming pending action (30 min ahead), no overdue/blocked.
    log_action(action_type="calendar_event", summary="12:30 吃药", scheduled_at="2026-04-28 12:30", status="pending")

    result = run_cli(["failures", "--due-soon-minutes", "60", "--notify", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["report"]["summary"]["due_soon"] == 1
    # Previously this would be no_issues; due-soon now triggers a proactive nudge.
    assert payload["notification"]["sent"] is True
    assert len(notifications) == 1
    assert "12:30 吃药" in notifications[0]["message"]


def test_failures_notify_is_quiet_when_no_issues(monkeypatch, tmp_path):
    notifications = []

    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.commands.failures.datetime", _FixedDateTime)
    monkeypatch.setattr(
        "nudge.commands.failures.notify",
        lambda title, message, subtitle=None, sound="default": notifications.append((title, message)) or (True, ""),
    )

    result = run_cli(["failures", "--notify", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["notification"] == {"sent": False, "reason": "no_issues"}
    assert notifications == []
