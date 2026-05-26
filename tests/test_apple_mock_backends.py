"""Tests for in-memory Apple backend examples."""

from __future__ import annotations

from nudge.apple.mock_backends import build_mock_apple_backends
from nudge.commands.agent import apply_agent_request


PUBLIC_CONFIG = {
    "general": {
        "default_calendar": "Personal",
        "default_reminder_list": "Tasks",
        "default_notes_folder": "Nudge",
    },
    "apple": {
        "calendar": {"backend": "native"},
        "reminders": {"backend": "native"},
        "notes": {"backend": "native"},
        "clock": {"backend": "shortcuts", "shortcut_name": "Nudge Create Alarm"},
    },
}


def test_mock_apple_backends_capture_agent_writes_without_apple_apps(monkeypatch, tmp_path):
    backends, store = build_mock_apple_backends()
    monkeypatch.setattr("nudge.commands.agent.resolve_apple_backends", lambda config: backends)
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.commands.agent.STATE_DIR", tmp_path)
    monkeypatch.setattr(
        "nudge.commands.agent.CONFIRMATION_SECRET_PATH",
        tmp_path / "agent_confirm_secret",
    )

    payload, exit_code = apply_agent_request(
        request={
            "request_id": "mock-backend-example",
            "source": "test",
            "actions": [
                {
                    "type": "calendar_event.create",
                    "summary": "Mock project sync",
                    "start": "2026-05-27 10:00",
                    "end": "2026-05-27 11:00",
                },
                {
                    "type": "reminder.create",
                    "name": "Mock follow-up",
                    "due_date": "2026-05-27 17:00",
                    "body": "Check notes",
                },
                {
                    "type": "note.create",
                    "title": "Mock note",
                    "body": "Local-only test note",
                },
                {
                    "type": "alarm.create",
                    "time": "07:30",
                    "label": "Mock wake-up",
                },
            ],
        },
        config=PUBLIC_CONFIG,
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert [action["status"] for action in payload["actions"]] == ["succeeded"] * 4
    assert payload["actions"][0]["external_id"] == "mock-calendar:1"
    assert payload["actions"][1]["external_id"] == "mock-reminder:1"
    assert payload["actions"][2]["external_id"] == "mock-note:1"
    assert payload["actions"][3]["external_id"] == "mock-alarm:1"
    assert store.events[0]["summary"] == "Mock project sync"
    assert store.reminders[0]["name"] == "Mock follow-up"
    assert store.notes[0]["title"] == "Mock note"
    assert store.alarms[0]["label"] == "Mock wake-up"
