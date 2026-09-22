"""Tests for Apple Clock integration through Shortcuts."""

import json
from types import SimpleNamespace

from nudge.apple.clock import DEFAULT_CREATE_ALARM_SHORTCUT, check_clock_shortcut, create_alarm


def test_check_clock_shortcut_reports_present(monkeypatch):
    def fake_run(cmd, text, capture_output, timeout):
        assert cmd == ["/usr/bin/shortcuts", "list"]
        return SimpleNamespace(returncode=0, stdout=f"Other\n{DEFAULT_CREATE_ALARM_SHORTCUT}\n", stderr="")

    monkeypatch.setattr("nudge.apple.clock.subprocess.run", fake_run)

    assert check_clock_shortcut() == (True, f"Shortcut found: {DEFAULT_CREATE_ALARM_SHORTCUT}")


def test_check_clock_shortcut_reports_missing(monkeypatch):
    def fake_run(cmd, text, capture_output, timeout):
        return SimpleNamespace(returncode=0, stdout="Other Shortcut\n", stderr="")

    monkeypatch.setattr("nudge.apple.clock.subprocess.run", fake_run)

    ok, message = check_clock_shortcut()

    assert ok is False
    assert DEFAULT_CREATE_ALARM_SHORTCUT in message


def test_create_alarm_runs_shortcut_with_json_payload(monkeypatch):
    calls = []

    def fake_run(cmd, text, capture_output, timeout):
        calls.append(cmd)
        payload = json.loads(open(cmd[-1], encoding="utf-8").read())
        assert payload == {
            "time": "07:00",
            "label": "晨起称重",
            "enabled": True,
        }
        return SimpleNamespace(returncode=0, stdout="created", stderr="")

    monkeypatch.setattr("nudge.apple.clock.subprocess.run", fake_run)

    ok, external_id = create_alarm("07:00", "晨起称重")

    assert ok is True
    assert external_id == f"Clock::{DEFAULT_CREATE_ALARM_SHORTCUT}::07:00::晨起称重"
    assert calls == [
        [
            "/usr/bin/shortcuts",
            "run",
            DEFAULT_CREATE_ALARM_SHORTCUT,
            "--input-path",
            calls[0][-1],
        ]
    ]


def test_create_alarm_rejects_invalid_time_without_running_shortcut(monkeypatch):
    monkeypatch.setattr(
        "nudge.apple.clock.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run shortcut")),
    )

    ok, message = create_alarm("明早", "晨起称重")

    assert ok is False
    assert "HH:MM" in message
