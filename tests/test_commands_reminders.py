"""Tests for Apple Reminders command helpers."""

import json
import subprocess
from datetime import date
from types import SimpleNamespace

from click.testing import CliRunner

from nudge.apple import reminders
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


def test_reminders_sync_completed_falls_back_to_current_default_list_when_setting_missing(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {}},
    )
    monkeypatch.setattr(
        "nudge.commands.reminders.sync_completed_for_date",
        lambda target_date, reminder_list, apply_changes: calls.append(
            (target_date.isoformat(), reminder_list, apply_changes)
        )
        or {
            "schema_version": "nudge.cli.v1",
            "ok": True,
            "dry_run": not apply_changes,
            "date": target_date.isoformat(),
            "list": reminder_list,
        },
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert calls == [("2026-04-27", "Tasks", False)]


def test_reminders_sync_completed_dry_run_lists_completed_candidates(monkeypatch):
    actions = [
        {
            "id": "weight",
            "type": "reminder",
            "summary": "[Nudge Liver W1] 晨起称重 + 睡眠记录 2026-04-27",
            "scheduled_at": "2026-04-27 06:40",
            "status": "created",
        },
        {
            "id": "standing",
            "type": "reminder",
            "summary": "[Nudge Liver W1] 站立 / 走动 10 分钟 2026-04-27 11:00",
            "scheduled_at": "2026-04-27 11:00",
            "status": "created",
        },
        {
            "id": "training",
            "type": "calendar_event",
            "summary": "[Nudge Liver W1] 抗阻 A 轻量",
            "scheduled_at": "2026-04-27 18:30",
            "status": "created",
        },
    ]

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}},
    )
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr(
        "nudge.commands.reminders.query_due_on_date",
        lambda **kwargs: (
            True,
            [
                {
                    "name": "[Nudge Liver W1] 站立 / 走动 10 分钟 2026-04-27 11:00",
                    "due_time": "11:00",
                    "list": "日常",
                }
            ],
        ),
    )
    monkeypatch.setattr("nudge.commands.reminders.query_completed_on_date", lambda **kwargs: (True, []), raising=False)
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not update SQLite")),
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["date"] == "2026-04-27"
    assert payload["list"] == "日常"
    assert payload["checked"] == 2
    assert payload["open"] == 1
    assert payload["updated"] == 0
    assert payload["candidates"] == []
    assert payload["human_needed"] == [
        {
            "id": "weight",
            "summary": "[Nudge Liver W1] 晨起称重 + 睡眠记录 2026-04-27",
            "scheduled_at": "2026-04-27 06:40",
            "reason": "missing_from_incomplete_without_completion_date",
            "followup_commands": [
                "nudge log done --id weight",
                "nudge log skipped --id weight",
                "nudge log partial --id weight",
            ],
            "list": "日常",
        }
    ]
    assert payload["auto_apply_policy"] == "requires_apple_completion_date"


def test_parse_due_today_rows_includes_completed_at_when_present():
    assert reminders._parse_due_today_rows("睡觉\t23:30\t日常\t2026-04-27 22:47\t2026-04-27 23:30\n") == [
        {
            "name": "睡觉",
            "due_time": "23:30",
            "list": "日常",
            "completed_at": "2026-04-27 22:47",
            "due_at": "2026-04-27 23:30",
        }
    ]


def test_parse_due_today_rows_omits_empty_completed_at():
    assert reminders._parse_due_today_rows("睡觉\t23:30\t日常\t\n") == [
        {
            "name": "睡觉",
            "due_time": "23:30",
            "list": "日常",
        }
    ]


def test_query_completed_on_date_invokes_completed_mode_and_parses_completed_at(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return SimpleNamespace(returncode=0, stdout="睡觉\t23:30\t日常\t2026-04-27 22:47\n", stderr="")

    monkeypatch.setattr(reminders.subprocess, "run", fake_run)

    ok, result = reminders.query_completed_on_date("日常", date(2026, 4, 27), timeout=7)

    assert ok is True
    assert result == [
        {
            "name": "睡觉",
            "due_time": "23:30",
            "list": "日常",
            "completed_at": "2026-04-27 22:47",
        }
    ]
    assert captured["cmd"][-3:] == ["日常", "2026-04-27", "completed"]
    assert captured["timeout"] == 7


def test_query_completed_on_date_reports_timeout(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(reminders.subprocess, "run", fake_run)

    assert reminders.query_completed_on_date("日常", date(2026, 4, 27)) == (
        False,
        "EventKit completed-reminders query timed out",
    )


def test_reminders_backfill_ids_dry_run_lists_unique_candidates(monkeypatch):
    actions = [
        {
            "id": "legacy-1",
            "type": "reminder",
            "summary": "买菜",
            "scheduled_at": "2026-05-09 09:00",
            "status": "created",
            "external_id": None,
        },
        {
            "id": "has-id",
            "type": "reminder",
            "summary": "喝水",
            "scheduled_at": "2026-05-09 10:00",
            "status": "created",
            "external_id": "nudge://reminder/existing",
        },
    ]

    monkeypatch.setattr("nudge.commands.reminders.load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr(
        "nudge.commands.reminders.query_due_on_date",
        lambda list_name, target_date: (True, [{"name": "买菜", "due_time": "09:00", "list": list_name}]),
    )
    monkeypatch.setattr("nudge.commands.reminders.make_reminder_external_id", lambda: "nudge://reminder/new-id")
    monkeypatch.setattr(
        "nudge.commands.reminders.set_reminder_external_id",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not write Apple Reminders")),
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "backfill-ids", "--from", "2026-05-09", "--to", "2026-05-10", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["checked"] == 1
    assert payload["would_update"] == 1
    assert payload["updated"] == 0
    assert payload["candidates"][0]["id"] == "legacy-1"
    assert payload["candidates"][0]["external_id"] == "nudge://reminder/new-id"
    assert payload["missing"] == []
    assert payload["ambiguous"] == []


def test_reminders_backfill_ids_apply_writes_apple_and_sqlite(monkeypatch):
    actions = [
        {
            "id": "legacy-1",
            "type": "reminder",
            "summary": "买菜",
            "scheduled_at": "2026-05-09 09:00",
            "status": "created",
            "external_id": None,
        }
    ]
    apple_calls = []
    sqlite_calls = []

    monkeypatch.setattr("nudge.commands.reminders.load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr(
        "nudge.commands.reminders.query_due_on_date",
        lambda list_name, target_date: (True, [{"name": "买菜", "due_time": "09:00", "list": list_name}]),
    )
    monkeypatch.setattr("nudge.commands.reminders.make_reminder_external_id", lambda: "nudge://reminder/new-id")
    monkeypatch.setattr(
        "nudge.commands.reminders.set_reminder_external_id",
        lambda name, list_name, due_date, external_id: apple_calls.append((name, list_name, due_date, external_id)) or (True, "matched=1 changed=1"),
    )
    monkeypatch.setattr(
        "nudge.commands.reminders.update_action_external_id",
        lambda action_id, external_id: sqlite_calls.append((action_id, external_id)),
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "backfill-ids", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is False
    assert payload["updated"] == 1
    assert apple_calls == [("买菜", "日常", "2026-05-09 09:00", "nudge://reminder/new-id")]
    assert sqlite_calls == [("legacy-1", "nudge://reminder/new-id")]


def test_reminders_backfill_ids_reports_missing_and_ambiguous(monkeypatch):
    actions = [
        {
            "id": "missing",
            "type": "reminder",
            "summary": "不存在",
            "scheduled_at": "2026-05-09 09:00",
            "status": "created",
            "external_id": None,
        },
        {
            "id": "ambiguous",
            "type": "reminder",
            "summary": "买菜",
            "scheduled_at": "2026-05-09 10:00",
            "status": "created",
            "external_id": None,
        },
    ]

    def fake_due(list_name, target_date):
        return True, [
            {"name": "买菜", "due_time": "10:00", "list": list_name},
            {"name": "买菜", "due_time": "10:00", "list": list_name},
        ]

    monkeypatch.setattr("nudge.commands.reminders.load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", fake_due)

    result = CliRunner().invoke(
        cli,
        ["reminders", "backfill-ids", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["would_update"] == 0
    assert [item["id"] for item in payload["missing"]] == ["missing"]
    assert [item["id"] for item in payload["ambiguous"]] == ["ambiguous"]


def test_reminders_backfill_ids_checks_next_day_completed_for_late_completion(monkeypatch):
    actions = [
        {
            "id": "late-done",
            "type": "reminder",
            "summary": "关机",
            "scheduled_at": "2026-05-25 22:00",
            "status": "done",
            "external_id": None,
        }
    ]
    completed_calls = []

    monkeypatch.setattr("nudge.commands.reminders.load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", lambda list_name, target_date: (True, []))

    def fake_completed(list_name, target_date):
        completed_calls.append(target_date.isoformat())
        if target_date.isoformat() == "2026-05-26":
            return True, [{
                "name": "关机",
                "due_time": "22:00",
                "list": list_name,
                "completed_at": "2026-05-26 08:29",
                "due_at": "2026-05-25 22:00",
            }]
        return True, []

    monkeypatch.setattr("nudge.commands.reminders.query_completed_on_date", fake_completed)
    monkeypatch.setattr("nudge.commands.reminders.make_reminder_external_id", lambda: "nudge://reminder/late")

    result = CliRunner().invoke(
        cli,
        ["reminders", "backfill-ids", "--from", "2026-05-25", "--to", "2026-05-26", "--include-completed", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert completed_calls == ["2026-05-25", "2026-05-26"]
    assert payload["would_update"] == 1
    assert payload["candidates"][0]["id"] == "late-done"
    assert payload["missing"] == []


def test_reminders_backfill_ids_rejects_same_time_different_due_date(monkeypatch):
    actions = [
        {
            "id": "target",
            "type": "reminder",
            "summary": "关机",
            "scheduled_at": "2026-05-26 22:00",
            "status": "created",
            "external_id": None,
        }
    ]

    monkeypatch.setattr("nudge.commands.reminders.load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", lambda list_name, target_date: (True, []))
    monkeypatch.setattr(
        "nudge.commands.reminders.query_completed_on_date",
        lambda list_name, target_date: (True, [{
            "name": "关机",
            "due_time": "22:00",
            "due_at": "2026-05-25 22:00",
            "list": list_name,
            "completed_at": "2026-05-26 08:29",
        }]),
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "backfill-ids", "--from", "2026-05-26", "--to", "2026-05-27", "--include-completed", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["would_update"] == 0
    assert [item["id"] for item in payload["missing"]] == ["target"]


def test_reminders_backfill_ids_configures_state_for_custom_config(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}, "state": {"dir": "/tmp/custom"}},
    )
    monkeypatch.setattr("nudge.commands.reminders.configure_state", lambda config: calls.append(config))
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: [])

    result = CliRunner().invoke(
        cli,
        ["reminders", "backfill-ids", "--config", "config.toml", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert calls == [{"general": {"default_reminder_list": "日常"}, "state": {"dir": "/tmp/custom"}}]


def test_reminders_reconcile_missing_dry_run_lists_missing_without_writes(monkeypatch):
    actions = [
        {
            "id": "open",
            "type": "reminder",
            "summary": "买菜",
            "scheduled_at": "2026-05-09 09:00",
            "status": "created",
            "external_id": "nudge://reminder/open",
        },
        {
            "id": "missing",
            "type": "reminder",
            "summary": "课程提醒",
            "scheduled_at": "2026-05-09 10:00",
            "status": "pending",
            "external_id": None,
        },
        {
            "id": "done",
            "type": "reminder",
            "summary": "喝水",
            "scheduled_at": "2026-05-10 11:00",
            "status": "created",
            "external_id": "nudge://reminder/done",
        },
        {
            "id": "ignored-done",
            "type": "reminder",
            "summary": "已完成",
            "scheduled_at": "2026-05-09 12:00",
            "status": "done",
        },
    ]
    due_calls = []
    completed_calls = []

    monkeypatch.setattr("nudge.commands.reminders.load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)

    def fake_due(list_name, target_date):
        due_calls.append((list_name, target_date.isoformat()))
        if target_date.isoformat() == "2026-05-09":
            return True, [{"name": "买菜", "due_time": "09:00", "due_at": "2026-05-09 09:00", "list": list_name}]
        return True, []

    def fake_completed(list_name, target_date):
        completed_calls.append((list_name, target_date.isoformat()))
        if target_date.isoformat() == "2026-05-10":
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
    assert completed_calls == [("日常", "2026-05-09"), ("日常", "2026-05-10")]


def test_reminders_sync_completed_apply_marks_candidates_done(monkeypatch):
    actions = [
        {
            "id": "weight",
            "type": "reminder",
            "summary": "[Nudge Liver W1] 晨起称重 + 睡眠记录 2026-04-27",
            "scheduled_at": "2026-04-27 06:40",
            "status": "created",
        }
    ]
    updates = []

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}},
    )
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr(
        "nudge.commands.reminders.query_due_on_date",
        lambda **kwargs: (True, []),
    )
    monkeypatch.setattr("nudge.commands.reminders.query_completed_on_date", lambda **kwargs: (True, []), raising=False)
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda action_id, feedback=None, completed_at=None: updates.append((action_id, feedback, completed_at)),
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is False
    assert payload["updated"] == 0
    assert payload["candidates"] == []
    assert payload["human_needed"][0]["id"] == "weight"
    assert payload["human_needed"][0]["reason"] == "missing_from_incomplete_without_completion_date"
    assert updates == []


def test_reminders_sync_completed_apply_uses_apple_completed_at(monkeypatch):
    actions = [
        {
            "id": "weight",
            "type": "reminder",
            "summary": "[Nudge Liver W1] 晨起称重 + 睡眠记录 2026-04-27",
            "scheduled_at": "2026-04-27 06:40",
            "status": "created",
        }
    ]
    updates = []

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}},
    )
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", lambda **kwargs: (True, []))
    def fake_completed_query(**kwargs):
        if kwargs["target_date"] == date(2026, 4, 27):
            return (
                True,
                [
                    {
                        "name": "[Nudge Liver W1] 晨起称重 + 睡眠记录 2026-04-27",
                        "due_time": "06:40",
                        "list": "日常",
                        "completed_at": "2026-04-27 06:43",
                        "due_at": "2026-04-27 06:40",
                    }
                ],
            )
        return True, []

    monkeypatch.setattr(
        "nudge.commands.reminders.query_completed_on_date",
        fake_completed_query,
        raising=False,
    )
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda action_id, feedback=None, completed_at=None: updates.append((action_id, feedback, completed_at)),
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["candidates"][0]["completed_at"] == "2026-04-27 06:43"
    assert updates[0][0] == "weight"
    assert updates[0][2] == "2026-04-27 06:43"
    feedback = updates[0][1]
    assert feedback["source_type"] == "objective"
    assert feedback["note"] == "Apple Reminders completionDate 已同步回 Nudge。"
    assert feedback["reminder_list"] == "日常"
    assert feedback["sync_date"] == "2026-04-27"
    assert "synced_at" in feedback
    assert feedback["apple_completed_at"] == "2026-04-27 06:43"


def test_reminders_sync_completed_apply_warns_when_completed_query_fails(monkeypatch):
    actions = [
        {
            "id": "weight",
            "type": "reminder",
            "summary": "[Nudge Liver W1] 晨起称重 + 睡眠记录 2026-04-27",
            "scheduled_at": "2026-04-27 06:40",
            "status": "created",
        }
    ]
    updates = []

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}},
    )
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", lambda **kwargs: (True, []))
    monkeypatch.setattr(
        "nudge.commands.reminders.query_completed_on_date",
        lambda **kwargs: (False, "EventKit completed-reminders query timed out"),
        raising=False,
    )
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda action_id, feedback=None, completed_at=None: updates.append((action_id, feedback, completed_at)) or [],
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["updated"] == 0
    assert payload["candidates"] == []
    assert payload["human_needed"][0]["id"] == "weight"
    assert payload["human_needed"][0]["reason"] == "completed_query_failed"
    assert payload["warnings"] == [
        {
            "code": "REMINDERS_COMPLETED_QUERY_FAILED",
            "message": "EventKit completed-reminders query timed out",
            "list": "日常",
        }
    ]
    assert updates == []


def test_matching_completed_rejects_completed_at_outside_reasonable_window():
    from nudge.commands.reminders import _matching_completed

    action = {
        "id": "sleep",
        "type": "reminder",
        "summary": "23:30 睡觉",
        "scheduled_at": "2026-04-27 23:30",
    }

    assert _matching_completed(
        action,
        [
            {
                "name": "23:30 睡觉",
                "due_time": "23:30",
                "completed_at": "2026-04-28 23:30",
            }
        ],
    ) is None


def test_matching_completed_rejects_sleep_completed_much_too_early():
    from nudge.commands.reminders import _matching_completed

    action = {
        "id": "sleep",
        "type": "reminder",
        "summary": "23:30 睡觉",
        "scheduled_at": "2026-04-27 23:30",
    }

    assert _matching_completed(
        action,
        [
            {
                "name": "23:30 睡觉",
                "due_time": "23:30",
                "completed_at": "2026-04-27 12:00",
            }
        ],
    ) is None


def test_matching_completed_rejects_invalid_completed_at():
    from nudge.commands.reminders import _matching_completed

    action = {
        "id": "weight",
        "type": "reminder",
        "summary": "称重",
        "scheduled_at": "2026-04-27 06:40",
    }

    assert _matching_completed(
        action,
        [
            {
                "name": "称重",
                "due_time": "06:40",
                "completed_at": "not-a-date",
            }
        ],
    ) is None


def test_sync_completed_reports_ambiguous_completed_match(monkeypatch):
    actions = [
        {
            "id": "weight",
            "type": "reminder",
            "summary": "称重",
            "scheduled_at": "2026-04-27 06:40",
            "status": "created",
        }
    ]

    def fake_completed_query(**kwargs):
        if kwargs["target_date"] == date(2026, 4, 27):
            return (
                True,
                [
                    {"name": "称重", "due_time": "06:40", "completed_at": "2026-04-27 06:41", "due_at": "2026-04-27 06:40"},
                    {"name": "称重", "due_time": "06:40", "completed_at": "2026-04-27 06:42", "due_at": "2026-04-27 06:40"},
                ],
            )
        return True, []

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}},
    )
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", lambda **kwargs: (True, []))
    monkeypatch.setattr("nudge.commands.reminders.query_completed_on_date", fake_completed_query, raising=False)
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ambiguous match must not update SQLite")),
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["updated"] == 0
    assert payload["candidates"] == []
    assert payload["human_needed"][0]["id"] == "weight"
    assert payload["human_needed"][0]["reason"] == "ambiguous_completed_match"


def test_sync_completed_requires_completed_match_due_at(monkeypatch):
    actions = [
        {
            "id": "weight",
            "type": "reminder",
            "summary": "称重",
            "scheduled_at": "2026-04-27 06:40",
            "status": "created",
        }
    ]

    def fake_completed_query(**kwargs):
        if kwargs["target_date"] == date(2026, 4, 27):
            return True, [{"name": "称重", "due_time": "06:40", "completed_at": "2026-04-27 06:41"}]
        return True, []

    monkeypatch.setattr("nudge.commands.reminders.load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", lambda **kwargs: (True, []))
    monkeypatch.setattr("nudge.commands.reminders.query_completed_on_date", fake_completed_query, raising=False)
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("missing due_at must not update SQLite")),
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["updated"] == 0
    assert payload["candidates"] == []
    assert payload["human_needed"][0]["reason"] == "missing_due_at"


def test_sync_completed_rejects_completed_match_with_different_due_at(monkeypatch):
    actions = [
        {
            "id": "weight",
            "type": "reminder",
            "summary": "称重",
            "scheduled_at": "2026-04-27 06:40",
            "status": "created",
        }
    ]

    def fake_completed_query(**kwargs):
        if kwargs["target_date"] == date(2026, 4, 27):
            return True, [
                {
                    "name": "称重",
                    "due_time": "06:40",
                    "completed_at": "2026-04-27 06:41",
                    "due_at": "2026-04-26 06:40",
                }
            ]
        return True, []

    monkeypatch.setattr("nudge.commands.reminders.load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", lambda **kwargs: (True, []))
    monkeypatch.setattr("nudge.commands.reminders.query_completed_on_date", fake_completed_query, raising=False)
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("different due_at must not update SQLite")),
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["updated"] == 0
    assert payload["candidates"] == []
    assert payload["human_needed"][0]["reason"] == "missing_from_incomplete_without_completion_date"


def test_reminders_sync_completed_apply_uses_next_day_completed_at_for_cross_midnight_sleep(monkeypatch):
    actions = [
        {
            "id": "sleep",
            "type": "reminder",
            "summary": "23:30 睡觉",
            "scheduled_at": "2026-04-27 23:30",
            "status": "created",
        }
    ]
    completed_queries = []
    updates = []

    def fake_completed_query(**kwargs):
        completed_queries.append(kwargs["target_date"])
        if kwargs["target_date"] == date(2026, 4, 28):
            return (
                True,
                [
                    {
                        "name": "23:30 睡觉",
                        "due_time": "23:30",
                        "list": "日常",
                        "completed_at": "2026-04-28 00:10",
                        "due_at": "2026-04-27 23:30",
                    }
                ],
            )
        return True, []

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}},
    )
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", lambda **kwargs: (True, []))
    monkeypatch.setattr("nudge.commands.reminders.query_completed_on_date", fake_completed_query, raising=False)
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda action_id, feedback=None, completed_at=None: updates.append((action_id, feedback, completed_at)) or [],
    )
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_reminders_batch",
        lambda requests, list_name: {request["id"]: (True, "done") for request in requests},
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert completed_queries == [date(2026, 4, 27), date(2026, 4, 28)]
    assert payload["candidates"][0]["completed_at"] == "2026-04-28 00:10"
    assert updates[0][0] == "sleep"
    assert updates[0][2] == "2026-04-28 00:10"
    feedback = updates[0][1]
    assert feedback["event_type"] == "sleep_start"
    assert feedback["event_at"] == "2026-04-28 00:10"


def test_reminders_sync_completed_apply_marks_sleep_start_event(monkeypatch):
    actions = [
        {
            "id": "sleep",
            "type": "reminder",
            "summary": "22:30 睡觉",
            "scheduled_at": "2026-04-27 22:30",
            "status": "created",
        }
    ]
    updates = []

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}},
    )
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", lambda **kwargs: (True, []))
    def fake_completed_query(**kwargs):
        if kwargs["target_date"] == date(2026, 4, 27):
            return (
                True,
                [
                    {
                        "name": "22:30 睡觉",
                        "due_time": "22:30",
                        "list": "日常",
                        "completed_at": "2026-04-27 22:47",
                        "due_at": "2026-04-27 22:30",
                    }
                ],
            )
        return True, []

    monkeypatch.setattr(
        "nudge.commands.reminders.query_completed_on_date",
        fake_completed_query,
        raising=False,
    )
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda action_id, feedback=None, completed_at=None: updates.append((action_id, feedback, completed_at)) or [],
    )
    monkeypatch.setattr("nudge.commands.reminders.complete_reminder", lambda name, list_name, due_date=None: (True, "done"))

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    feedback = updates[0][1]
    assert updates[0][2] == "2026-04-27 22:47"
    assert feedback["event_type"] == "sleep_start"
    assert feedback["event_at"] == "2026-04-27 22:47"


def test_reminders_sync_completed_apply_does_not_mark_sleep_start_event_without_completed_at(monkeypatch):
    actions = [
        {
            "id": "sleep",
            "type": "reminder",
            "summary": "22:30 睡觉",
            "scheduled_at": "2026-04-27 22:30",
            "status": "created",
        }
    ]
    updates = []

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}},
    )
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", lambda **kwargs: (True, []))
    def fake_completed_query(**kwargs):
        if kwargs["target_date"] == date(2026, 4, 27):
            return (
                True,
                [
                    {
                        "name": "22:30 睡觉",
                        "due_time": "22:30",
                        "list": "日常",
                        "due_at": "2026-04-27 22:30",
                    }
                ],
            )
        return True, []

    monkeypatch.setattr("nudge.commands.reminders.query_completed_on_date", fake_completed_query, raising=False)
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda action_id, feedback=None, completed_at=None: updates.append((action_id, feedback, completed_at)) or [],
    )
    monkeypatch.setattr("nudge.commands.reminders.complete_reminder", lambda name, list_name, due_date=None: (True, "done"))

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["updated"] == 0
    assert payload["candidates"] == []
    assert payload["human_needed"][0]["id"] == "sleep"
    assert payload["human_needed"][0]["reason"] == "missing_completed_at"
    assert updates == []


def test_reminders_sync_completed_apply_completes_later_sleep_reminders_in_apple(monkeypatch):
    actions = [
        {
            "id": "sleep",
            "type": "reminder",
            "summary": "22:30 睡觉",
            "scheduled_at": "2026-04-27 22:30",
            "status": "created",
        },
        {
            "id": "late",
            "type": "reminder",
            "summary": "不要熬夜",
            "scheduled_at": "2026-04-27 23:00",
            "status": "created",
        },
    ]
    completed_actions = []
    completed_reminders = []

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}},
    )
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr(
        "nudge.commands.reminders.query_due_on_date",
        lambda **kwargs: (
            True,
            [
                {
                    "name": "不要熬夜",
                    "due_time": "23:00",
                    "list": "日常",
                }
            ],
        ),
    )
    def fake_completed_query(**kwargs):
        if kwargs["target_date"] == date(2026, 4, 27):
            return (
                True,
                [
                    {
                        "name": "22:30 睡觉",
                        "due_time": "22:30",
                        "list": "日常",
                        "completed_at": "2026-04-27 22:47",
                        "due_at": "2026-04-27 22:30",
                    }
                ],
            )
        return True, []

    monkeypatch.setattr("nudge.commands.reminders.query_completed_on_date", fake_completed_query, raising=False)
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda action_id, feedback=None, completed_at=None: completed_actions.append((action_id, feedback, completed_at)) or [actions[1]],
    )
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_reminders_batch",
        lambda requests, list_name: completed_reminders.extend((request["titles"], list_name, request["due_date"]) for request in requests)
        or {request["id"]: (True, "done") for request in requests},
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert completed_actions[0][0] == "sleep"
    assert completed_reminders == [(["不要熬夜"], "日常", "2026-04-27 23:00")]
    assert payload["auto_skipped_after_sleep"] == [
        {
            "id": "late",
            "summary": "不要熬夜",
            "scheduled_at": "2026-04-27 23:00",
            "list": "日常",
            "apple_completed": True,
            "apple_message": "done",
        }
    ]


def test_reminders_sync_completed_apply_backfills_existing_done_sleep_cascade(monkeypatch):
    actions = [
        {
            "id": "shutdown",
            "type": "reminder",
            "summary": "22:30 关机流程",
            "scheduled_at": "2026-04-29 22:30",
            "completed_at": "2026-04-29 22:34",
            "status": "done",
        },
        {
            "id": "prepare",
            "type": "reminder",
            "summary": "准备睡觉 2026-04-29 23:00",
            "scheduled_at": "2026-04-29 23:00",
            "status": "created",
        },
        {
            "id": "latest",
            "type": "reminder",
            "summary": "最晚上床 2026-04-29 23:30",
            "scheduled_at": "2026-04-29 23:30",
            "status": "created",
        },
    ]
    completed_reminders = []

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}},
    )
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr(
        "nudge.commands.reminders.query_due_on_date",
        lambda **kwargs: (
            True,
            [
                {"name": "准备睡觉 2026-04-29 23:00", "due_time": "23:00", "list": "日常"},
                {"name": "最晚上床 2026-04-29 23:30", "due_time": "23:30", "list": "日常"},
            ],
        ),
    )
    monkeypatch.setattr("nudge.commands.reminders.query_completed_on_date", lambda **kwargs: (True, []), raising=False)
    monkeypatch.setattr(
        "nudge.commands.reminders.skip_later_sleep_reminders_after_completion",
        lambda action_id: actions[1:] if action_id == "shutdown" else [],
    )
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no new completed candidates expected")),
    )
    monkeypatch.setattr(
        "nudge.commands.reminders.complete_reminders_batch",
        lambda requests, list_name: completed_reminders.extend((request["titles"], list_name, request["due_date"]) for request in requests)
        or {request["id"]: (True, "done") for request in requests},
    )

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-29", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["candidates"] == []
    assert payload["auto_skipped_after_sleep"] == [
        {
            "id": "prepare",
            "summary": "准备睡觉 2026-04-29 23:00",
            "scheduled_at": "2026-04-29 23:00",
            "list": "日常",
            "apple_completed": True,
            "apple_message": "done",
        },
        {
            "id": "latest",
            "summary": "最晚上床 2026-04-29 23:30",
            "scheduled_at": "2026-04-29 23:30",
            "list": "日常",
            "apple_completed": True,
            "apple_message": "done",
        },
    ]
    assert completed_reminders == [
        (["准备睡觉 2026-04-29 23:00", "准备睡觉"], "日常", "2026-04-29 23:00"),
        (["最晚上床 2026-04-29 23:30", "最晚上床"], "日常", "2026-04-29 23:30"),
    ]


def test_reminders_sync_completed_apply_does_not_mark_auto_skipped_later_sleep_done(monkeypatch):
    actions = [
        {
            "id": "sleep",
            "type": "reminder",
            "summary": "22:30 睡觉",
            "scheduled_at": "2026-04-27 22:30",
            "status": "created",
        },
        {
            "id": "late",
            "type": "reminder",
            "summary": "不要熬夜",
            "scheduled_at": "2026-04-27 23:00",
            "status": "created",
        },
    ]
    completed_actions = []

    def fake_complete_action(action_id, feedback=None, completed_at=None):
        completed_actions.append(action_id)
        if action_id == "sleep":
            return [actions[1]]
        raise AssertionError("auto-skipped later sleep reminder must not be marked done")

    monkeypatch.setattr(
        "nudge.commands.reminders.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}},
    )
    monkeypatch.setattr("nudge.commands.reminders.get_actions", lambda **kwargs: actions)
    monkeypatch.setattr("nudge.commands.reminders.query_due_on_date", lambda **kwargs: (True, []))

    def fake_completed_query(**kwargs):
        if kwargs["target_date"] == date(2026, 4, 27):
            return (
                True,
                [
                    {
                        "name": "22:30 睡觉",
                        "due_time": "22:30",
                        "list": "日常",
                        "completed_at": "2026-04-27 22:47",
                        "due_at": "2026-04-27 22:30",
                    }
                ],
            )
        return True, []

    monkeypatch.setattr("nudge.commands.reminders.query_completed_on_date", fake_completed_query, raising=False)
    monkeypatch.setattr("nudge.commands.reminders.complete_action", fake_complete_action)
    monkeypatch.setattr("nudge.commands.reminders.complete_reminder", lambda name, list_name, due_date=None: (True, "done"))

    result = CliRunner().invoke(
        cli,
        ["reminders", "sync-completed", "--date", "2026-04-27", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert completed_actions == ["sleep"]
    assert payload["updated"] == 1
