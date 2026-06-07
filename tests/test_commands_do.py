import json
from dataclasses import dataclass, field
from datetime import datetime

from click.testing import CliRunner

from nudge.apple.adapters import AppleBackends, WriteResult
from nudge.brain import PARSE_SYSTEM
from nudge.cli import cli
from nudge.config import get_family_aliases, get_family_members, get_family_routing
from nudge.commands.do import _action_schema_problems, _rewrite_family_group_actions, format_action


@dataclass
class FakeNotesBackend:
    calls: list[dict] = field(default_factory=list)

    def list_folders(self):
        return True, ["Project Notes"]

    def create_note(self, *, title: str, body: str, folder_name: str = "Notes"):
        self.calls.append({"title": title, "body": body, "folder_name": folder_name})
        return WriteResult(ok=True, message=title, external_id=None)


class UnusedCalendarBackend:
    name = "fake"

    def list_calendars(self):
        return True, []

    def create_event(self, **kwargs):
        raise AssertionError("Calendar backend should not be called")


class UnusedRemindersBackend:
    name = "fake"

    def list_lists(self):
        return True, []

    def probe_read(self, list_name=None):
        return True, "ok"

    def create_reminder(self, **kwargs):
        raise AssertionError("Reminders backend should not be called")


class UnusedClockBackend:
    name = "fake"
    shortcut_name = "Fake Alarm"

    def check(self):
        return True, "ok"

    def create_alarm(self, **kwargs):
        raise AssertionError("Clock backend should not be called")


@dataclass
class RecordingCalendarBackend(UnusedCalendarBackend):
    calls: list[dict] = field(default_factory=list)
    ok: bool = True

    def create_event(self, **kwargs):
        self.calls.append(kwargs)
        return WriteResult(ok=self.ok, message="event-id", external_id="cal-1" if self.ok else None)


@dataclass
class RecordingRemindersBackend(UnusedRemindersBackend):
    calls: list[dict] = field(default_factory=list)
    ok: bool = True

    def create_reminder(self, **kwargs):
        self.calls.append(kwargs)
        return WriteResult(ok=self.ok, message="reminder-id", external_id="rem-1" if self.ok else None)


@dataclass
class RecordingClockBackend(UnusedClockBackend):
    calls: list[dict] = field(default_factory=list)
    ok: bool = True

    def create_alarm(self, **kwargs):
        self.calls.append(kwargs)
        return WriteResult(ok=self.ok, message="alarm-id", external_id="alarm-1" if self.ok else None)


def _fake_backends(notes_backend: FakeNotesBackend) -> AppleBackends:
    return AppleBackends(
        calendar=UnusedCalendarBackend(),
        reminders=UnusedRemindersBackend(),
        notes=notes_backend,
        clock=UnusedClockBackend(),
    )


def _note_action() -> dict:
    return {
        "type": "note",
        "title": "项目复盘",
        "body": "整理今天的决策和后续行动。",
    }


def _fake_config() -> dict:
    return {"general": {"default_notes_folder": "Project Notes"}}


def _config_with_defaults() -> dict:
    return {
        "general": {
            "default_calendar": "Personal",
            "default_reminder_list": "Tasks",
            "default_notes_folder": "Project Notes",
        },
        "family": {
            "ming": {
                "display_name": "小明",
                "aliases": ["小明"],
                "calendar": "Ming Calendar",
                "reminder_list": "Ming Tasks",
            },
            "hong": {
                "display_name": "小红",
                "aliases": ["小红"],
                "calendar": "Hong Calendar",
                "reminder_list": "Hong Tasks",
            },
            "routing": {
                "display": {"title_prefix": True, "body_assignee_note": True},
                "rules": [{"id": "everyone", "keywords": ["全家"], "assignees": "all"}],
            },
        },
    }


def test_parse_system_documents_note_action_schema():
    assert '"type": "note"' in PARSE_SYSTEM
    assert '"title": "Note title"' in PARSE_SYSTEM
    assert '"body": "Note body"' in PARSE_SYSTEM
    assert "Only return valid JSON array" in PARSE_SYSTEM


def test_format_action_shows_note_title_and_notes_folder():
    rendered = format_action(
        _note_action(),
        1,
        alias_map={},
        defaults={"default_notes_folder": "Project Notes"},
    )

    assert "[NOTE]" in rendered
    assert '"项目复盘"' in rendered
    assert "Folder: Project Notes" in rendered


def test_do_dry_run_json_emits_note_action_without_notes_backend_or_log(monkeypatch):
    notes_backend = FakeNotesBackend()
    log_calls = []

    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda config_path=None: _fake_config())
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda message, aliases: [_note_action()])
    monkeypatch.setattr("nudge.commands.do.resolve_apple_backends", lambda config: _fake_backends(notes_backend))
    monkeypatch.setattr("nudge.commands.do.log_action", lambda **kwargs: log_calls.append(kwargs))

    result = CliRunner().invoke(
        cli,
        ["do", "--dry-run", "--json", "把今天项目复盘记到 Notes"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["actions"][0]["type"] == "note"
    assert payload["actions"][0]["summary"] == "项目复盘"
    assert payload["actions"][0]["target"] == {
        "kind": "Notes folder",
        "name": "Project Notes",
    }
    assert notes_backend.calls == []
    assert log_calls == []


def test_do_executes_note_backend_and_logs_title_summary(monkeypatch):
    notes_backend = FakeNotesBackend()
    log_calls = []

    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda config_path=None: _fake_config())
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda message, aliases: [_note_action()])
    monkeypatch.setattr("nudge.commands.do.resolve_apple_backends", lambda config: _fake_backends(notes_backend))
    monkeypatch.setattr("nudge.commands.do.log_action", lambda **kwargs: log_calls.append(kwargs))

    result = CliRunner().invoke(
        cli,
        ["do", "把今天项目复盘记到 Notes"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert notes_backend.calls == [
        {
            "title": "项目复盘",
            "body": "整理今天的决策和后续行动。",
            "folder_name": "Project Notes",
        }
    ]
    assert log_calls == [
        {
            "action_type": "note",
            "summary": "项目复盘",
            "scheduled_at": None,
            "external_id": None,
        }
    ]


def test_action_schema_problems_reports_missing_fields_and_bad_datetime():
    problems = _action_schema_problems(
        [
            {"type": "calendar_event", "summary": "无结束时间", "start": "2026-06-08 09:00"},
            {"type": "reminder", "name": "坏日期", "due_date": "2026/06/08 09:00"},
            {"type": "alarm", "time": "", "label": "起床"},
            {"type": "unknown"},
        ]
    )

    assert "action 1 calendar_event missing fields: end" in problems
    assert any("action 2 Invalid due date format" in problem for problem in problems)
    assert "action 3 alarm missing fields: time" in problems
    assert "action 4 has unsupported type: unknown" in problems


def test_action_schema_problems_rejects_calendar_end_before_start():
    problems = _action_schema_problems(
        [
            {
                "type": "calendar_event",
                "summary": "倒序会议",
                "start": "2026-06-08 10:00",
                "end": "2026-06-08 09:00",
            }
        ]
    )

    assert problems == ["action 1 end time must be after start time"]


def test_do_dry_run_json_covers_calendar_reminder_alarm_and_note(monkeypatch):
    notes_backend = FakeNotesBackend()
    clock_backend = RecordingClockBackend()
    actions = [
        {
            "type": "calendar_event",
            "summary": "项目同步",
            "start": "2026-06-08 09:00",
            "end": "2026-06-08 10:00",
        },
        {"type": "reminder", "name": "提交日报", "due_date": "2026-06-08 18:00"},
        {"type": "alarm", "time": "07:30", "label": "晨跑"},
        _note_action(),
    ]

    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda config_path=None: _config_with_defaults())
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda message, aliases: actions)
    monkeypatch.setattr(
        "nudge.commands.do.resolve_apple_backends",
        lambda config: AppleBackends(
            calendar=UnusedCalendarBackend(),
            reminders=UnusedRemindersBackend(),
            notes=notes_backend,
            clock=clock_backend,
        ),
    )

    result = CliRunner().invoke(
        cli,
        ["do", "--dry-run", "--json", "安排今天"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert [(item["type"], item["status"]) for item in payload["actions"]] == [
        ("calendar_event", "dry_run"),
        ("reminder", "dry_run"),
        ("alarm", "dry_run"),
        ("note", "dry_run"),
    ]
    assert [item["target"] for item in payload["actions"]] == [
        {"kind": "Calendar", "name": "Personal"},
        {"kind": "Reminder list", "name": "Tasks"},
        {"kind": "Clock alarm", "name": "Fake Alarm"},
        {"kind": "Notes folder", "name": "Project Notes"},
    ]
    assert notes_backend.calls == []
    assert clock_backend.calls == []


def test_do_json_validation_error_has_stable_machine_shape(monkeypatch):
    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda config_path=None: _config_with_defaults())
    monkeypatch.setattr(
        "nudge.commands.do.parse_actions",
        lambda message, aliases: [
            {
                "type": "calendar_event",
                "summary": "坏时间",
                "start": "2026-06-08 10:00",
                "end": "2026-06-08 09:00",
            }
        ],
    )
    monkeypatch.setattr("nudge.commands.do.resolve_apple_backends", lambda config: _fake_backends(FakeNotesBackend()))

    result = CliRunner().invoke(
        cli,
        ["do", "--dry-run", "--json", "安排坏时间"],
        prog_name="nudge",
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["dry_run"] is True
    assert payload["actions"] == []
    assert payload["failures"] == []
    assert payload["errors"][0]["code"] == "LLM_ACTION_SCHEMA_INVALID"
    assert "end time must be after start time" in payload["errors"][0]["detail"]


def test_do_json_partial_failure_reports_failed_item_without_recreating_successes(monkeypatch):
    calendar_backend = RecordingCalendarBackend(ok=True)
    reminders_backend = RecordingRemindersBackend(ok=False)
    log_calls = []
    actions = [
        {
            "type": "calendar_event",
            "summary": "项目同步",
            "start": "2026-06-08 09:00",
            "end": "2026-06-08 10:00",
        },
        {"type": "reminder", "name": "提交日报", "due_date": "2026-06-08 18:00"},
    ]

    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)
    monkeypatch.setattr("nudge.commands.do.load_config", lambda config_path=None: _config_with_defaults())
    monkeypatch.setattr("nudge.commands.do.parse_actions", lambda message, aliases: actions)
    monkeypatch.setattr(
        "nudge.commands.do.resolve_apple_backends",
        lambda config: AppleBackends(
            calendar=calendar_backend,
            reminders=reminders_backend,
            notes=FakeNotesBackend(),
            clock=RecordingClockBackend(),
        ),
    )
    monkeypatch.setattr("nudge.commands.do.log_action", lambda **kwargs: log_calls.append(kwargs))

    result = CliRunner().invoke(
        cli,
        ["do", "--json", "安排两件事"],
        prog_name="nudge",
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["succeeded"] == 1
    assert payload["actions"][0]["status"] == "succeeded"
    assert payload["actions"][0]["external_id"] == "cal-1"
    assert payload["actions"][1]["status"] == "failed"
    assert payload["failures"] == [
        {
            "index": 2,
            "summary": "提交日报",
            "error_code": "APPLE_WRITE_FAILED",
            "error": "Reminders 写入失败",
        }
    ]
    assert calendar_backend.calls[0]["start"] == datetime(2026, 6, 8, 9, 0)
    assert reminders_backend.calls[0]["due_date"] == datetime(2026, 6, 8, 18, 0)
    assert len(log_calls) == 1
    assert log_calls[0]["summary"] == "项目同步"


def test_family_group_calendar_event_rewrites_to_member_reminders():
    action = {
        "type": "calendar_event",
        "summary": "全家体检",
        "start": "2026-06-08 09:00",
        "end": "2026-06-08 10:00",
        "person": "全家",
        "location": "医院",
        "notes": "带证件",
    }
    config = _config_with_defaults()
    family_members = get_family_members(config)
    _, alias_map = get_family_aliases(config)

    rewritten = _rewrite_family_group_actions(
        [action],
        family_members,
        alias_map,
        get_family_routing(config),
        llm_router=None,
    )

    assert [item["type"] for item in rewritten] == ["reminder", "reminder", "reminder", "reminder"]
    assert {item["person"] for item in rewritten} == {"小明", "小红"}
    assert all(item["_family_group_alias"] == "全家" for item in rewritten)
    assert all(item["_family_routing"]["source"] == "keyword" for item in rewritten)
    assert any(item["name"] == "小明：全家体检（30 分钟后开始）" for item in rewritten)
    assert any(item["name"] == "小红：全家体检（现在开始）" for item in rewritten)
    assert any("地点：医院" in item["body"] and "负责人：" in item["body"] for item in rewritten)
