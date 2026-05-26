"""Regression tests for `nudge do` parsing and validation contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass

from click.testing import CliRunner

import nudge.brain as brain
import nudge.commands.do as do
from nudge.apple.adapters import AppleBackends, WriteResult
from nudge.cli import cli
from nudge.config import FAMILY_GROUP_PERSON
from nudge.json_contract import CLI_SCHEMA_VERSION


PUBLIC_CONFIG = {
    "general": {"default_calendar": "Personal", "default_reminder_list": "Tasks"},
    "apple": {
        "calendar": {"backend": "native"},
        "reminders": {"backend": "native"},
        "notes": {"backend": "native"},
        "clock": {"backend": "shortcuts", "shortcut_name": "Nudge Create Alarm"},
    },
}


FAMILY_CONFIG = {
    **PUBLIC_CONFIG,
    "family": {
        "alice": {
            "display_name": "Alice",
            "aliases": ["Alice"],
            "calendar": "Alice Calendar",
            "reminder_list": "Alice Tasks",
        },
        "bob": {
            "display_name": "Bob",
            "aliases": ["Bob"],
            "calendar": "Bob Calendar",
            "reminder_list": "Bob Tasks",
        },
        "routing": {
            "default": "all",
            "display": {"title_prefix": True, "body_assignee_note": True},
        },
    },
}


@dataclass
class FakeCalendarBackend:
    writes: list[dict]
    name: str = "fake-calendar"

    def create_event(self, **kwargs) -> WriteResult:
        self.writes.append(kwargs)
        return WriteResult(ok=True, message="created", external_id=f"calendar:{len(self.writes)}")


@dataclass
class FakeRemindersBackend:
    writes: list[dict]
    name: str = "fake-reminders"

    def create_reminder(self, **kwargs) -> WriteResult:
        self.writes.append(kwargs)
        return WriteResult(ok=True, message="created", external_id=f"reminder:{len(self.writes)}")


@dataclass
class FakeClockBackend:
    writes: list[dict]
    shortcut_name: str = "Fake Alarm Shortcut"
    name: str = "fake-clock"

    def create_alarm(self, **kwargs) -> WriteResult:
        self.writes.append(kwargs)
        return WriteResult(ok=True, message="created", external_id=f"alarm:{len(self.writes)}")


@dataclass
class FakeNotesBackend:
    writes: list[dict]
    name: str = "fake-notes"

    def create_note(self, **kwargs) -> WriteResult:
        self.writes.append(kwargs)
        return WriteResult(ok=True, message="created", external_id=f"note:{len(self.writes)}")


def test_do_json_reports_bad_llm_json_without_real_llm_or_apple(monkeypatch):
    writes = _patch_do_boundaries(monkeypatch)
    calls = []

    def fake_llm_call(system, text, task=None):
        calls.append({"system": system, "text": text, "task": task})
        return "{not valid json"

    monkeypatch.setattr(brain, "_call", fake_llm_call)

    result = CliRunner().invoke(
        cli,
        ["do", "--dry-run", "--json", "明天提醒我检查护照"],
        prog_name="nudge",
    )

    payload = json.loads(result.output)
    assert result.exit_code == 1
    assert payload["schema_version"] == CLI_SCHEMA_VERSION
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "LLM_INVALID_JSON"
    assert len(calls) == 2
    assert writes == {"calendar": [], "reminders": [], "clock": [], "notes": []}


def test_do_json_rejects_missing_required_fields_before_apple_writes(monkeypatch):
    writes = _patch_do_boundaries(monkeypatch)
    monkeypatch.setattr(
        do,
        "parse_actions",
        lambda text, aliases: [
            {
                "type": "calendar_event",
                "summary": "Project sync",
                "start": "2026-05-22 14:00",
            }
        ],
    )

    result = CliRunner().invoke(
        cli,
        ["do", "--dry-run", "--json", "schedule project sync"],
        prog_name="nudge",
    )

    payload = json.loads(result.output)
    assert result.exit_code == 1
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "LLM_ACTION_SCHEMA_INVALID"
    assert "missing fields: end" in payload["errors"][0]["detail"]
    assert writes == {"calendar": [], "reminders": [], "clock": [], "notes": []}


def test_do_json_rejects_calendar_end_before_start_before_apple_writes(monkeypatch):
    writes = _patch_do_boundaries(monkeypatch)
    monkeypatch.setattr(
        do,
        "parse_actions",
        lambda text, aliases: [
            {
                "type": "calendar_event",
                "summary": "Backwards event",
                "start": "2026-05-22 15:00",
                "end": "2026-05-22 14:00",
            }
        ],
    )

    result = CliRunner().invoke(
        cli,
        ["do", "--dry-run", "--json", "schedule backwards event"],
        prog_name="nudge",
    )

    payload = json.loads(result.output)
    assert result.exit_code == 1
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "LLM_ACTION_SCHEMA_INVALID"
    assert "end time must be after start time" in payload["errors"][0]["detail"]
    assert writes == {"calendar": [], "reminders": [], "clock": [], "notes": []}


def test_do_json_expands_family_group_reminder_without_real_llm_or_apple(monkeypatch):
    writes = _patch_do_boundaries(monkeypatch, config=FAMILY_CONFIG)
    seen_aliases = []

    def fake_parse_actions(text, aliases):
        seen_aliases.extend(aliases)
        return [
            {
                "type": "reminder",
                "name": "带水杯",
                "due_date": "2026-05-22 08:00",
                "person": FAMILY_GROUP_PERSON,
                "body": "出门前检查",
                "priority": 0,
            }
        ]

    monkeypatch.setattr(do, "parse_actions", fake_parse_actions)
    monkeypatch.setattr(
        do,
        "suggest_family_routing",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not call routing LLM")),
    )

    result = CliRunner().invoke(
        cli,
        ["do", "--dry-run", "--json", "提醒全家带水杯"],
        prog_name="nudge",
    )

    payload = json.loads(result.output)
    actions = payload["actions"]
    assert result.exit_code == 0
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["total"] == 2
    assert {action["person"] for action in actions} == {"Alice", "Bob"}
    assert {action["summary"] for action in actions} == {"Alice：带水杯", "Bob：带水杯"}
    assert {action["target"]["name"] for action in actions} == {"Alice Tasks", "Bob Tasks"}
    assert all(action["routing"]["source"] == "default" for action in actions)
    assert all(action["routing"]["assignees"] == ["all"] for action in actions)
    assert "家庭组" in seen_aliases
    assert writes == {"calendar": [], "reminders": [], "clock": [], "notes": []}


def _patch_do_boundaries(monkeypatch, config=None) -> dict[str, list[dict]]:
    writes = {"calendar": [], "reminders": [], "clock": [], "notes": []}
    backends = AppleBackends(
        calendar=FakeCalendarBackend(writes["calendar"]),
        reminders=FakeRemindersBackend(writes["reminders"]),
        clock=FakeClockBackend(writes["clock"]),
        notes=FakeNotesBackend(writes["notes"]),
    )
    monkeypatch.setattr(do, "load_config", lambda p=None: config or PUBLIC_CONFIG)
    monkeypatch.setattr(do, "resolve_apple_backends", lambda loaded_config: backends)
    return writes
