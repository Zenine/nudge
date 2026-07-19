"""Multi-list Reminder completion sync contracts."""

import json
from datetime import date

from click.testing import CliRunner

from nudge.commands import daily
from nudge.commands import reminders
from nudge.commands.doctor import _configured_reminder_lists
from nudge.reminder_lists import resolve_sync_lists


def test_resolve_sync_lists_uses_config_and_deduplicates() -> None:
    config = {
        "general": {"default_reminder_list": "Tasks"},
        "reminders": {
            "sync_lists": ["Tasks", "Health", "GPT", "Health"],
        },
    }

    assert resolve_sync_lists((), config) == ["Tasks", "Health", "GPT"]
    assert resolve_sync_lists(("GPT", "Tasks", "GPT"), config) == ["GPT", "Tasks"]


def test_doctor_flattens_sync_lists_with_named_reminder_routes() -> None:
    config = {
        "general": {"default_reminder_list": "Tasks"},
        "reminders": {
            "workout": "Fitness",
            "sync_lists": ["Tasks", "Health", "GPT", "Health"],
        },
        "family": {
            "child": {"reminder_list": "Family"},
        },
    }

    assert _configured_reminder_lists(config) == [
        "Family",
        "Fitness",
        "GPT",
        "Health",
        "Tasks",
    ]


def test_sync_completed_for_lists_keeps_list_results_separate(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []

    def fake_sync(*, target_date, reminder_list, apply_changes):
        calls.append((reminder_list, apply_changes))
        return {
            "ok": True,
            "dry_run": not apply_changes,
            "date": target_date.isoformat(),
            "list": reminder_list,
            "checked": 2,
            "open": 1,
            "candidates": [{"id": f"{reminder_list}-done"}],
            "updated": 1 if apply_changes else 0,
            "auto_skipped_after_sleep": (
                [{"id": "sleep-later", "list": "Sleep"}]
                if reminder_list == "Tasks"
                else []
            ),
            "warnings": [],
            "errors": [],
        }

    monkeypatch.setattr(reminders, "sync_completed_for_date", fake_sync)

    payload = reminders.sync_completed_for_lists(
        target_date=date(2026, 7, 18),
        reminder_lists=["Tasks", "Health"],
        apply_changes=False,
    )

    assert calls == [("Tasks", False), ("Health", False)]
    assert payload["ok"] is True
    assert payload["lists"] == ["Tasks", "Health"]
    assert payload["checked"] == 4
    assert payload["open"] == 2
    assert payload["candidates"] == [
        {"id": "Tasks-done", "list": "Tasks"},
        {"id": "Health-done", "list": "Health"},
    ]
    assert payload["auto_skipped_after_sleep"] == [
        {"id": "sleep-later", "list": "Sleep"},
    ]
    assert [item["list"] for item in payload["results"]] == ["Tasks", "Health"]


def test_sync_completed_cli_accepts_repeated_list_options(monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr(reminders, "load_config", lambda path: {})

    def fake_sync_lists(*, target_date, reminder_lists, apply_changes):
        captured.update({
            "target_date": target_date,
            "reminder_lists": reminder_lists,
            "apply_changes": apply_changes,
        })
        return {
            "ok": True,
            "dry_run": True,
            "date": target_date.isoformat(),
            "list": "",
            "lists": reminder_lists,
            "checked": 0,
            "open": 0,
            "candidates": [],
            "updated": 0,
            "auto_skipped_after_sleep": [],
            "warnings": [],
            "errors": [],
            "results": [],
        }

    monkeypatch.setattr(reminders, "sync_completed_for_lists", fake_sync_lists)

    result = CliRunner().invoke(
        reminders.reminders_command,
        [
            "sync-completed",
            "--date",
            "2026-07-18",
            "--list",
            "Tasks",
            "--list",
            "Health",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["reminder_lists"] == ["Tasks", "Health"]
    assert captured["apply_changes"] is False
    assert json.loads(result.output)["lists"] == ["Tasks", "Health"]


def test_daily_sync_runs_each_due_date_for_each_list(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(daily, "load_config", lambda path: {})
    monkeypatch.setattr(
        daily,
        "_reminder_sync_dates",
        lambda **kwargs: [date(2026, 7, 17), date(2026, 7, 18)],
    )

    def fake_sync(*, target_date, reminder_list, apply_changes):
        calls.append((target_date.isoformat(), reminder_list))
        return {
            "ok": True,
            "date": target_date.isoformat(),
            "list": reminder_list,
            "errors": [],
        }

    monkeypatch.setattr(daily, "sync_completed_for_date", fake_sync)
    monkeypatch.setattr(daily, "_sync_health", lambda **kwargs: {"ok": True, "errors": []})
    monkeypatch.setattr(daily, "_sync_docs_audit", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(
        daily,
        "_remaining_failures",
        lambda *args: {
            "summary": {
                "pending_overdue": 0,
                "blocked_open": 0,
                "missing_reason": 0,
                "missing_next_action": 0,
                "deferred_open": 0,
            },
            "pending_overdue": [],
            "blocked_open": [],
            "missing_reason": [],
            "missing_next_action": [],
            "deferred_open": [],
        },
    )

    result = CliRunner().invoke(
        daily.daily_command,
        [
            "sync",
            "--date",
            "2026-07-18",
            "--list",
            "Tasks",
            "--list",
            "Health",
            "--no-health",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        ("2026-07-17", "Tasks"),
        ("2026-07-17", "Health"),
        ("2026-07-18", "Tasks"),
        ("2026-07-18", "Health"),
    ]
    assert json.loads(result.output)["reminders"]["lists"] == ["Tasks", "Health"]


def test_reminder_actions_for_date_filters_known_target_list(monkeypatch) -> None:
    monkeypatch.setattr(
        reminders,
        "get_actions",
        lambda **kwargs: [
            {
                "id": "tasks-action",
                "type": "reminder",
                "summary": "同名提醒",
                "scheduled_at": "2026-07-18 09:00",
                "status": "pending",
                "reminder_list": "Tasks",
            },
            {
                "id": "health-action",
                "type": "reminder",
                "summary": "同名提醒",
                "scheduled_at": "2026-07-18 09:00",
                "status": "pending",
                "reminder_list": "Health",
            },
            {
                "id": "legacy-action",
                "type": "reminder",
                "summary": "旧提醒",
                "scheduled_at": "2026-07-18 10:00",
                "status": "pending",
                "reminder_list": None,
            },
        ],
    )

    actions = reminders._reminder_actions_for_date(
        date(2026, 7, 18),
        reminder_list="Health",
    )

    assert [item["id"] for item in actions] == ["health-action", "legacy-action"]


def test_legacy_backfill_skips_actions_owned_by_another_list(monkeypatch) -> None:
    monkeypatch.setattr(
        reminders,
        "get_actions",
        lambda **kwargs: [
            {
                "id": "tasks-action",
                "type": "reminder",
                "summary": "Tasks reminder",
                "scheduled_at": "2026-07-18 09:00",
                "status": "pending",
                "external_id": None,
                "reminder_list": "Tasks",
            },
            {
                "id": "health-action",
                "type": "reminder",
                "summary": "Health reminder",
                "scheduled_at": "2026-07-18 10:00",
                "status": "pending",
                "external_id": None,
                "reminder_list": "Health",
            },
            {
                "id": "legacy-action",
                "type": "reminder",
                "summary": "Legacy reminder",
                "scheduled_at": "2026-07-18 11:00",
                "status": "pending",
                "external_id": None,
                "reminder_list": None,
            },
        ],
    )

    actions = reminders._legacy_reminder_actions(
        from_date=None,
        to_date=None,
        limit=None,
        reminder_list="Health",
    )

    assert [item["id"] for item in actions] == ["health-action", "legacy-action"]


def test_sleep_auto_skip_uses_each_actions_persisted_list(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_complete(summary, scheduled_at, reminder_list):
        calls.append((summary, reminder_list))
        return True, "completed"

    monkeypatch.setattr(reminders, "_complete_reminder_by_possible_titles", fake_complete)

    results = reminders._complete_auto_skipped_sleep_reminders(
        [
            {
                "id": "sleep-reminder",
                "summary": "准备睡觉",
                "scheduled_at": "2026-07-18 23:00",
                "reminder_list": "Sleep",
            }
        ],
        "Tasks",
    )

    assert calls == [("准备睡觉", "Sleep")]
    assert results[0]["apple_completed"] is True
