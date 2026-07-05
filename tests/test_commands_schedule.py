"""Tests for schedule free-slot filtering and booking flow."""

import json
from datetime import date, datetime

import pytest
from click.testing import CliRunner

import nudge.state as state
from nudge.apple.adapters import WriteResult
from nudge.cli import cli
from nudge.commands.schedule import find_free_slots, parse_duration_minutes


PUBLIC_CONFIG = {
    "general": {"default_calendar": "Personal"},
    "user": {"schedule": {"work_hours": ["09:00", "17:00"]}},
    "calendars": {"personal": "Personal"},
    "apple": {"calendar": {"backend": "native"}},
}


@pytest.fixture(autouse=True)
def isolate_state(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")


def test_parse_duration_minutes_from_request_text():
    assert parse_duration_minutes("找2小时深度工作时间") == 120
    assert parse_duration_minutes("安排 90 分钟 项目同步") == 90
    assert parse_duration_minutes("need 1.5h focus") == 90
    assert parse_duration_minutes(None) == 30


def test_find_free_slots_filters_by_min_duration_and_skips_past_days():
    events = [
        {"start": "2026-07-06 10:00", "end": "2026-07-06 11:00"},
        {"start": "2026-07-06 12:00", "end": "2026-07-06 13:30"},
        {"start": "2026-07-07 09:30", "end": "2026-07-07 16:30"},
    ]

    slots = find_free_slots(
        events,
        week_start=date(2026, 7, 6),
        today=date(2026, 7, 6),
        work_start="09:00",
        work_end="17:00",
        min_duration=90,
    )

    assert [slot["date"] + " " + slot["start"] + "-" + slot["end"] for slot in slots[:3]] == [
        "2026-07-06 13:30-17:00",
        "2026-07-08 09:00-17:00",
        "2026-07-09 09:00-17:00",
    ]
    assert all(slot["duration"] >= 90 for slot in slots)


def test_schedule_json_filters_slots(monkeypatch):
    _patch_schedule_io(monkeypatch, [
        {"start": "2026-07-06 10:00", "end": "2026-07-06 11:00"},
        {"start": "2026-07-06 12:00", "end": "2026-07-06 13:30"},
    ])

    result = CliRunner().invoke(cli, ["schedule", "找2小时深度工作时间", "--json"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["min_duration"] == 120
    assert payload["slots"][0]["start"] == "13:30"
    assert all(slot["duration"] >= 120 for slot in payload["slots"])


def test_schedule_book_dry_run_requires_no_calendar_write(monkeypatch):
    writes = []
    _patch_schedule_io(monkeypatch, [], writes=writes)

    result = CliRunner().invoke(
        cli,
        [
            "schedule",
            "深度工作",
            "--duration",
            "120",
            "--book",
            "--slot",
            "1",
            "--title",
            "Deep Work",
            "--dry-run",
            "--json",
        ],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["booking"]["summary"] == "Deep Work"
    assert payload["booking"]["start"] == "2026-07-06 09:00"
    assert writes == []


def test_schedule_book_requires_explicit_slot(monkeypatch):
    _patch_schedule_io(monkeypatch, [])

    result = CliRunner().invoke(
        cli,
        ["schedule", "深度工作", "--duration", "120", "--book", "--yes"],
        prog_name="nudge",
    )

    assert result.exit_code != 0
    assert "--book requires --slot" in result.output


def test_schedule_book_writes_calendar_and_logs_action(monkeypatch):
    writes = []
    _patch_schedule_io(monkeypatch, [], writes=writes)

    result = CliRunner().invoke(
        cli,
        [
            "schedule",
            "深度工作",
            "--duration",
            "120",
            "--book",
            "--slot",
            "1",
            "--title",
            "Deep Work",
            "--yes",
            "--json",
        ],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is False
    assert payload["booking"]["external_id"] == "calendar::event-1"
    assert writes == [
        {
            "summary": "Deep Work",
            "start": datetime(2026, 7, 6, 9, 0),
            "end": datetime(2026, 7, 6, 11, 0),
            "calendar_name": "Personal",
            "location": None,
            "notes": "Scheduled from nudge schedule request: 深度工作",
        }
    ]
    actions = state.get_actions()
    assert len(actions) == 1
    assert actions[0]["summary"] == "Deep Work"
    assert actions[0]["scheduled_at"] == "2026-07-06 09:00"


def _patch_schedule_io(monkeypatch, events, writes=None):
    writes = writes if writes is not None else []
    monkeypatch.setattr("nudge.cli.load_config", lambda: PUBLIC_CONFIG)
    monkeypatch.setattr("nudge.commands.schedule.load_config", lambda path=None: PUBLIC_CONFIG)
    monkeypatch.setattr("nudge.commands.schedule.get_week_events", lambda calendar_names=None: events)
    monkeypatch.setattr("nudge.commands.schedule.date", FixedDate)

    class FakeCalendarBackend:
        def create_event(self, **kwargs):
            writes.append(kwargs)
            return WriteResult(ok=True, message="created", external_id="calendar::event-1")

    class FakeBackends:
        calendar = FakeCalendarBackend()

    monkeypatch.setattr("nudge.commands.schedule.resolve_apple_backends", lambda config: FakeBackends())


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 7, 6)
