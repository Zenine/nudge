"""Safety tests for AppleScript reminder mutation fallbacks."""

import json
import subprocess
from datetime import date
from types import SimpleNamespace

import pytest

from nudge.apple import reminders


def _disable_eventkit(monkeypatch):
    monkeypatch.setattr(
        reminders,
        "_run_eventkit_mutation",
        lambda *args, **kwargs: (False, "EventKit unavailable"),
    )


def test_query_all_due_on_date_reads_completed_and_incomplete_reminders(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps([
                {
                    "name": "Finished task",
                    "due_time": "09:00",
                    "list": "Tasks",
                    "completed_at": "2026-07-18 10:15",
                    "due_date": "2026-07-18 09:00",
                },
                {
                    "name": "Open task",
                    "due_time": "11:30",
                    "list": "Tasks",
                    "completed_at": None,
                    "due_date": "2026-07-18 11:30",
                },
            ]),
            stderr="",
        )

    monkeypatch.setattr(reminders.subprocess, "run", fake_run)

    ok, rows = reminders.query_all_due_on_date("Tasks", date(2026, 7, 18))

    assert ok is True
    assert calls == [
        {
            "cmd": [
                "/usr/bin/swift",
                str(reminders.EVENTKIT_DUE_TODAY_SCRIPT),
                "Tasks",
                "2026-07-18",
                "all-due",
            ],
            "capture_output": True,
            "text": True,
            "timeout": reminders.DEFAULT_READ_TIMEOUT,
        }
    ]
    assert rows == [
        {
            "name": "Finished task",
            "due_time": "09:00",
            "list": "Tasks",
            "completed_at": "2026-07-18 10:15",
            "due_at": "2026-07-18 09:00",
        },
        {
            "name": "Open task",
            "due_time": "11:30",
            "list": "Tasks",
            "due_at": "2026-07-18 11:30",
        },
    ]


def test_query_all_due_on_date_preserves_structured_text_losslessly(monkeypatch) -> None:
    name = "  Keep\tthis\nline  "
    list_name = "  项目\t列表\n第二行  "
    monkeypatch.setattr(
        reminders.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{
                "name": name,
                "due_time": "09:07",
                "list": list_name,
                "completed_at": None,
                "due_date": "2026-07-18 09:07",
            }], ensure_ascii=False),
            stderr="",
        ),
    )

    ok, rows = reminders.query_all_due_on_date(list_name, date(2026, 7, 18))

    assert ok is True
    assert rows == [{
        "name": name,
        "due_time": "09:07",
        "list": list_name,
        "due_at": "2026-07-18 09:07",
    }]


def test_query_all_due_on_date_rejects_valid_data_mixed_with_malformed_output(monkeypatch) -> None:
    valid = json.dumps({
        "name": "Duplicate",
        "due_time": "09:00",
        "list": "Tasks",
        "completed_at": None,
        "due_date": "2026-07-18 09:00",
    })
    monkeypatch.setattr(
        reminders.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"[{valid}, malformed-row]",
            stderr="",
        ),
    )

    ok, error = reminders.query_all_due_on_date("Tasks", date(2026, 7, 18))

    assert ok is False
    assert error == "Invalid EventKit all-due output"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": 7, "due_time": "09:00", "list": "Tasks", "completed_at": None, "due_date": "2026-07-18 09:00"},
        {"name": "Task", "due_time": None, "list": "Tasks", "completed_at": None, "due_date": "2026-07-18 09:00"},
        {"name": "Task", "due_time": "09:00", "list": ["Tasks"], "completed_at": None, "due_date": "2026-07-18 09:00"},
        {"name": "Task", "due_time": "09:00", "list": "Tasks", "completed_at": False, "due_date": "2026-07-18 09:00"},
        {"name": "Task", "due_time": "09:00", "list": "Tasks", "completed_at": None, "due_date": 20260718},
    ],
)
def test_query_all_due_on_date_rejects_missing_or_invalid_fields(monkeypatch, payload) -> None:
    monkeypatch.setattr(
        reminders.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps([payload]),
            stderr="",
        ),
    )

    assert reminders.query_all_due_on_date("Tasks", date(2026, 7, 18)) == (
        False,
        "Invalid EventKit all-due output",
    )


def test_original_eventkit_modes_keep_tab_separated_output_compatibility(monkeypatch) -> None:
    monkeypatch.setattr(
        reminders.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="Original task\t08:30\tTasks\t\t2026-07-18 08:30\n",
            stderr="",
        ),
    )

    ok, rows = reminders.query_due_today_eventkit("Tasks")

    assert ok is True
    assert rows == [{
        "name": "Original task",
        "due_time": "08:30",
        "list": "Tasks",
        "due_at": "2026-07-18 08:30",
    }]


def test_query_all_due_on_date_rejects_non_date_values() -> None:
    class DateLike:
        def strftime(self, _format: str) -> str:
            return "2026-07-18"

    assert reminders.query_all_due_on_date("Tasks", DateLike()) == (
        False,
        "target_date must be a date or datetime",
    )


def test_query_all_due_on_date_returns_stable_process_errors(monkeypatch) -> None:
    def missing_swift(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(reminders.subprocess, "run", missing_swift)
    assert reminders.query_all_due_on_date("Tasks", date(2026, 7, 18)) == (
        False,
        "swift executable not found",
    )

    def timed_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="swift", timeout=7)

    monkeypatch.setattr(reminders.subprocess, "run", timed_out)
    assert reminders.query_all_due_on_date("Tasks", date(2026, 7, 18), timeout=7) == (
        False,
        "EventKit all-due reminder query timed out",
    )

    monkeypatch.setattr(
        reminders.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=2, stdout="", stderr="access denied\n"),
    )
    assert reminders.query_all_due_on_date("Tasks", date(2026, 7, 18)) == (
        False,
        "access denied",
    )


def test_eventkit_all_due_mode_is_read_only_and_preserves_existing_predicates() -> None:
    source = reminders.EVENTKIT_DUE_TODAY_SCRIPT.read_text()

    assert 'requestedMode != "all-due"' in source
    assert "expected incomplete, completed, or all-due" in source
    assert 'requestedMode == "completed"' in source
    assert "predicateForCompletedReminders(" in source
    assert 'requestedMode == "all-due"' in source
    assert "predicateForReminders(in: calendars)" in source
    assert "predicateForIncompleteReminders(" in source
    assert "guard let dueDate else" in source
    assert "dueDate < start || dueDate > end" in source
    assert "reminder.dueDateComponents?.date" in source
    assert "reminder.completionDate" in source
    assert "eventkit_reminders_mutate" not in source
    assert "store.save(" not in source
    assert "store.remove(" not in source


def test_eventkit_all_due_mode_uses_lossless_json_transport() -> None:
    source = reminders.EVENTKIT_DUE_TODAY_SCRIPT.read_text()

    assert "JSONEncoder()" in source
    assert 'requestedMode == "all-due" ? (reminder.title ?? "") : sanitize' in source
    assert 'requestedMode == "all-due" ? reminder.calendar.title : sanitize' in source


def test_eventkit_lists_flag_does_not_shadow_a_reminder_list_name() -> None:
    source = reminders.EVENTKIT_DUE_TODAY_SCRIPT.read_text()

    assert 'let listOnly = args.count == 1 && args[0] == "--lists"' in source


def test_complete_fallback_does_not_bulk_complete_every_same_title(monkeypatch) -> None:
    _disable_eventkit(monkeypatch)
    scripts: list[str] = []

    def fake_run_applescript(script: str, timeout: int = 30) -> tuple[bool, str]:
        scripts.append(script)
        return True, "done"

    monkeypatch.setattr(reminders, "run_applescript", fake_run_applescript)

    reminders.complete_reminder("Drink water", "Nudge", prefer_eventkit=False)

    script = scripts[0]
    assert 'every reminder whose name is "Drink water" and completed is false' not in script
    assert "count of matchingReminders" in script
    assert "item 1 of matchingReminders" in script


def test_complete_fallback_uses_due_date_when_available(monkeypatch) -> None:
    _disable_eventkit(monkeypatch)
    scripts: list[str] = []

    def fake_run_applescript(script: str, timeout: int = 30) -> tuple[bool, str]:
        scripts.append(script)
        return True, "done"

    monkeypatch.setattr(reminders, "run_applescript", fake_run_applescript)

    reminders.complete_reminder(
        "Drink water",
        "Nudge",
        prefer_eventkit=False,
        due_date="2026-07-05 09:30",
    )

    script = scripts[0]
    assert "set targetDueDate to current date" in script
    assert "due date of r = targetDueDate" in script
    assert "set completed of (item 1 of matchingReminders) to true" in script


def test_complete_fallback_fails_when_same_title_is_ambiguous(monkeypatch) -> None:
    _disable_eventkit(monkeypatch)
    scripts: list[str] = []

    def fake_run_applescript(script: str, timeout: int = 30) -> tuple[bool, str]:
        scripts.append(script)
        if "count of matchingReminders" in script and "ambiguous reminder title" in script:
            return False, "ambiguous reminder title: Drink water matched 2 reminders; refusing bulk completion"
        return True, "done"

    monkeypatch.setattr(reminders, "run_applescript", fake_run_applescript)

    ok, message = reminders.complete_reminder("Drink water", "Nudge", prefer_eventkit=False)

    assert ok is False
    assert "ambiguous reminder title" in message
    assert "set completed of r to true" not in scripts[0]


def test_delete_fallback_allows_unique_title_without_bulk_delete(monkeypatch) -> None:
    _disable_eventkit(monkeypatch)
    scripts: list[str] = []

    def fake_run_applescript(script: str, timeout: int = 30) -> tuple[bool, str]:
        scripts.append(script)
        if "count of matchingReminders" in script:
            return True, "deleted"
        return False, "unsafe bulk delete script"

    monkeypatch.setattr(reminders, "run_applescript", fake_run_applescript)

    ok, message = reminders.delete_reminder("Drink water", "Nudge", prefer_eventkit=False)

    assert ok is True
    assert message == "deleted"
    assert "delete r" not in scripts[0]
    assert "delete (item 1 of matchingReminders)" in scripts[0]


def test_auto_skipped_reminder_completion_passes_scheduled_at_as_due_date(monkeypatch) -> None:
    from nudge.commands import reminders as reminder_commands

    calls: list[dict] = []

    def fake_complete_reminder(name: str, list_name: str, **kwargs) -> tuple[bool, str]:
        calls.append({"name": name, "list_name": list_name, **kwargs})
        return True, "done"

    monkeypatch.setattr(reminder_commands, "complete_reminder", fake_complete_reminder)

    ok, message = reminder_commands._complete_reminder_by_possible_titles(
        "Wind down",
        "2026-07-05 21:30",
        "Nudge",
    )

    assert ok is True
    assert message == "done"
    assert calls[0]["due_date"] == "2026-07-05 21:30"


def test_sync_completed_never_infers_completion_from_list_absence() -> None:
    from nudge.commands import reminders as reminder_commands

    actions = [
        {
            "id": "target-list",
            "type": "reminder",
            "summary": "Target task",
            "scheduled_at": "2026-07-13 09:00",
            "reminder_list": "Focus",
        },
        {
            "id": "other-list",
            "type": "reminder",
            "summary": "Family task",
            "scheduled_at": "2026-07-13 09:00",
            "reminder_list": "Family",
        },
        {
            "id": "legacy-unknown-list",
            "type": "reminder",
            "summary": "Legacy task",
            "scheduled_at": "2026-07-13 10:00",
            "reminder_list": None,
        },
    ]

    candidates, open_count = reminder_commands._completed_candidates(
        actions,
        incomplete=[],
        completed=[],
    )

    assert open_count == 0
    assert candidates == []


def test_sync_completed_accepts_positive_match_for_moved_or_legacy_reminder() -> None:
    from nudge.commands import reminders as reminder_commands

    actions = [
        {
            "id": "moved",
            "type": "reminder",
            "summary": "Moved task",
            "scheduled_at": "2026-07-13 09:00",
            "reminder_list": "Old list",
        },
        {
            "id": "legacy",
            "type": "reminder",
            "summary": "Legacy task",
            "scheduled_at": "2026-07-13 10:00",
            "reminder_list": None,
        },
    ]
    completed = [
        {
            "name": "Moved task",
            "due_time": "09:00",
            "due_at": "2026-07-13 09:00",
            "completed_at": "2026-07-13 09:05",
        },
        {
            "name": "Legacy task",
            "due_time": "10:00",
            "due_at": "2026-07-13 10:00",
            "completed_at": "2026-07-13 10:05",
        },
    ]

    candidates, open_count = reminder_commands._completed_candidates(
        actions,
        incomplete=[],
        completed=completed,
    )

    assert open_count == 0
    assert [item["id"] for item in candidates] == ["moved", "legacy"]


def test_complete_falls_back_to_due_date_limited_applescript_when_eventkit_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        reminders,
        "_run_eventkit_mutation",
        lambda *args, **kwargs: (False, "swift unavailable"),
    )
    scripts: list[str] = []

    def fake_run_applescript(script: str, timeout: int = 30) -> tuple[bool, str]:
        scripts.append(script)
        return True, "done"

    monkeypatch.setattr(reminders, "run_applescript", fake_run_applescript)

    ok, message = reminders.complete_reminder(
        "Drink water",
        "Nudge",
        due_date="2026-07-05 09:30",
    )

    assert ok is True
    assert message == "done"
    assert "due date of r = targetDueDate" in scripts[0]


def test_update_reminder_notes_uses_precise_eventkit_match(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_mutation(operation, name, list_name, **kwargs):
        calls.append({
            "operation": operation,
            "name": name,
            "list_name": list_name,
            **kwargs,
        })
        return True, "matched=1 changed=1"

    monkeypatch.setattr(reminders, "_run_eventkit_mutation", fake_mutation)

    ok, message = reminders.update_reminder_notes(
        "[通勤 GPT] 周一05:50：简历事实补齐",
        "GPT 对话",
        "2026-07-20 05:50",
        "新的完整会话包正文",
    )

    assert ok is True
    assert message == "matched=1 changed=1"
    assert calls == [{
        "operation": "update-notes",
        "name": "[通勤 GPT] 周一05:50：简历事实补齐",
        "list_name": "GPT 对话",
        "timeout": 30,
        "due_date": "2026-07-20 05:50",
        "body": "新的完整会话包正文",
    }]


def test_eventkit_update_notes_replaces_body_but_preserves_nudge_id() -> None:
    source = reminders.EVENTKIT_MUTATE_SCRIPT.read_text()

    assert 'operation != "update-notes"' in source
    assert 'operation == "update-notes"' in source
    assert "reminder.notes = updatedNotes" in source
    assert 'line.hasPrefix("Nudge-ID: ")' in source
