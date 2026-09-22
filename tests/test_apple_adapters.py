"""Tests for configurable Apple adapter backends."""

from datetime import datetime

import pytest

from nudge.apple.adapters import (
    AppleBackends,
    DisabledClockBackend,
    NativeCalendarBackend,
    NativeNotesBackend,
    NativeRemindersBackend,
    ShortcutsClockBackend,
    UnsupportedAppleBackendError,
    get_calendar_backend,
    get_clock_backend,
    get_notes_backend,
    get_reminders_backend,
    resolve_apple_backends,
)
from nudge.config import get_apple_backend_config


def test_apple_backend_config_defaults_preserve_current_runtime():
    assert get_apple_backend_config({}, "calendar", "native") == {"backend": "native"}
    assert get_apple_backend_config({}, "reminders", "native") == {"backend": "native"}
    assert get_apple_backend_config({}, "clock", "shortcuts") == {"backend": "shortcuts"}


def test_apple_backend_config_reads_service_override_and_shortcut_name():
    config = {
        "apple": {
            "clock": {
                "backend": "shortcuts",
                "shortcut_name": "Nudge Test Alarm",
            }
        }
    }

    assert get_apple_backend_config(config, "clock", "shortcuts") == {
        "backend": "shortcuts",
        "shortcut_name": "Nudge Test Alarm",
    }


def test_resolve_apple_backends_uses_native_and_shortcuts_by_default():
    backends = resolve_apple_backends({})

    assert isinstance(backends, AppleBackends)
    assert isinstance(backends.calendar, NativeCalendarBackend)
    assert isinstance(backends.reminders, NativeRemindersBackend)
    assert isinstance(backends.notes, NativeNotesBackend)
    assert isinstance(backends.clock, ShortcutsClockBackend)
    assert backends.calendar.name == "native"
    assert backends.reminders.name == "native"
    assert backends.notes.name == "native"
    assert backends.clock.name == "shortcuts"


def test_clock_backend_uses_configured_shortcut_name(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "nudge.apple.adapters.check_clock_shortcut",
        lambda shortcut_name: calls.append(("check", shortcut_name)) or (True, f"Shortcut found: {shortcut_name}"),
    )
    monkeypatch.setattr(
        "nudge.apple.adapters.create_alarm",
        lambda time, label, shortcut_name: calls.append(("create", time, label, shortcut_name)) or (True, f"Clock::{shortcut_name}::{time}::{label}"),
    )

    backend = get_clock_backend({"apple": {"clock": {"shortcut_name": "Nudge Test Alarm"}}})

    assert backend.shortcut_name == "Nudge Test Alarm"
    assert backend.check() == (True, "Shortcut found: Nudge Test Alarm")
    result = backend.create_alarm(time="07:00", label="晨起称重")
    assert result.ok is True
    assert result.external_id == "Clock::Nudge Test Alarm::07:00::晨起称重"
    assert calls == [
        ("check", "Nudge Test Alarm"),
        ("create", "07:00", "晨起称重", "Nudge Test Alarm"),
    ]



def test_clock_backend_can_be_explicitly_disabled():
    backend = get_clock_backend({"apple": {"clock": {"backend": "disabled"}}})

    assert isinstance(backend, DisabledClockBackend)
    assert backend.name == "disabled"
    assert backend.check() == (True, "Clock alarm creation disabled by config")
    result = backend.create_alarm(time="07:00", label="晨起称重")
    assert result.ok is False
    assert result.message == "Clock alarm creation is disabled by config"
    assert result.external_id is None

def test_native_calendar_backend_wraps_create_and_sets_external_id(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: calls.append(kwargs) or (True, "uid-123"),
    )
    backend = get_calendar_backend({})
    start = datetime(2026, 4, 26, 14, 0)
    end = datetime(2026, 4, 26, 15, 0)

    result = backend.create_event(
        summary="项目会",
        start=start,
        end=end,
        calendar_name="Family",
        location=None,
        notes="带资料",
    )

    assert result.ok is True
    assert result.message == "uid-123"
    assert result.external_id == "Family::uid-123"
    assert calls == [
        {
            "summary": "项目会",
            "start": start,
            "end": end,
            "calendar_name": "Family",
            "location": None,
            "notes": "带资料",
        }
    ]


def test_native_reminders_backend_generates_stable_external_id(monkeypatch):
    calls = []
    due = datetime(2026, 4, 26, 18, 0)
    monkeypatch.setattr(
        "nudge.apple.adapters.make_reminder_external_id",
        lambda: "nudge://reminder/test-id",
    )

    monkeypatch.setattr(
        "nudge.apple.adapters.create_reminder",
        lambda **kwargs: calls.append(kwargs) or (True, "reminder-object"),
    )
    backend = get_reminders_backend({})

    result = backend.create_reminder(
        name="买菜",
        due_date=due,
        list_name="日常",
        body=None,
        priority=0,
        remind_date=None,
    )

    assert result.ok is True
    assert result.message == "reminder-object"
    assert result.external_id == "nudge://reminder/test-id"
    assert calls == [
        {
            "name": "买菜",
            "due_date": due,
            "list_name": "日常",
            "body": None,
            "priority": 0,
            "remind_date": due,
            "notify": True,
            "external_id": "nudge://reminder/test-id",
        }
    ]


def test_native_reminders_backend_can_disable_notification(monkeypatch):
    calls = []
    due = datetime(2026, 4, 26, 18, 0)
    monkeypatch.setattr(
        "nudge.apple.adapters.make_reminder_external_id",
        lambda: "nudge://reminder/test-id",
    )
    monkeypatch.setattr(
        "nudge.apple.adapters.create_reminder",
        lambda **kwargs: calls.append(kwargs) or (True, "reminder-object"),
    )
    backend = get_reminders_backend({})

    result = backend.create_reminder(
        name="仅作截止记录",
        due_date=due,
        list_name="日常",
        remind_date=None,
        notify=False,
    )

    assert result.ok is True
    assert calls[0]["remind_date"] is None
    assert calls[0]["notify"] is False


def test_native_notes_backend_wraps_create_without_external_id(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "nudge.apple.adapters.create_note",
        lambda **kwargs: calls.append(kwargs) or (True, "计划标题"),
    )
    backend = get_notes_backend({})

    result = backend.create_note(
        title="计划标题",
        body="计划正文",
        folder_name="Nudge",
    )

    assert result.ok is True
    assert result.message == "计划标题"
    assert result.external_id is None
    assert calls == [
        {
            "title": "计划标题",
            "body": "计划正文",
            "folder_name": "Nudge",
        }
    ]


@pytest.mark.parametrize(
    ("factory", "config", "service", "backend"),
    [
        (get_calendar_backend, {"apple": {"calendar": {"backend": "ical"}}}, "calendar", "ical"),
        (get_reminders_backend, {"apple": {"reminders": {"backend": "rem"}}}, "reminders", "rem"),
        (get_notes_backend, {"apple": {"notes": {"backend": "mcp"}}}, "notes", "mcp"),
        (get_clock_backend, {"apple": {"clock": {"backend": "native"}}}, "clock", "native"),
    ],
)
def test_unsupported_backend_fails_explicitly(factory, config, service, backend):
    with pytest.raises(UnsupportedAppleBackendError) as excinfo:
        factory(config)

    message = str(excinfo.value)
    assert service in message
    assert backend in message
    assert "当前已实现" in message
