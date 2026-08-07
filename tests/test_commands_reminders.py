"""Tests for Apple Reminders command helpers."""

import json
from datetime import date

from click.testing import CliRunner

from nudge.cli import cli


def test_reminders_reconcile_missing_classifies_pending_actions_read_only(monkeypatch):
    actions = [
        {
            "id": "open",
            "type": "reminder",
            "summary": "买菜",
            "scheduled_at": "2026-05-09 09:00",
            "status": "created",
        },
        {
            "id": "done",
            "type": "reminder",
            "summary": "喝水",
            "scheduled_at": "2026-05-10 11:00",
            "status": "pending",
            "external_id": "reminders://done",
        },
        {
            "id": "missing",
            "type": "reminder",
            "summary": "跆拳道",
            "scheduled_at": "2026-05-10 18:00",
            "status": "created",
        },
        {
            "id": "ignored",
            "type": "calendar_event",
            "summary": "会议",
            "scheduled_at": "2026-05-10 12:00",
            "status": "created",
        },
    ]
    due_calls = []
    completed_calls = []

    monkeypatch.setattr("nudge.commands.reminders.load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)

    def fake_due(list_name, target_date):
        due_calls.append((list_name, target_date.isoformat()))
        if target_date == date(2026, 5, 9):
            return True, [{"name": "买菜", "due_time": "09:00", "due_at": "2026-05-09 09:00", "list": list_name}]
        return True, []

    def fake_completed(list_name, target_date):
        completed_calls.append((list_name, target_date.isoformat()))
        if target_date == date(2026, 5, 10):
            return True, [{"name": "喝水", "due_time": "11:00", "due_at": "2026-05-10 11:00", "completed_at": "2026-05-10 11:05", "list": list_name}]
        return True, []

    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", fake_due)
    monkeypatch.setattr("nudge.commands.reminders.query_completed_on_date", fake_completed)
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("reconcile must be read-only")),
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "reconcile-missing", "--from", "2026-05-09", "--to", "2026-05-11", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["checked"] == 3
    assert payload["summary"] == {"still_open": 1, "completed": 1, "missing": 1, "query_errors": 0}
    assert [item["id"] for item in payload["still_open"]] == ["open"]
    assert [item["id"] for item in payload["completed"]] == ["done"]
    assert [item["id"] for item in payload["missing"]] == ["missing"]
    assert due_calls == [("日常", "2026-05-09"), ("日常", "2026-05-10")]
    assert completed_calls == [("日常", "2026-05-10")]
