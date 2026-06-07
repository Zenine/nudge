"""Tests for sleep reminder cascade helpers."""

from __future__ import annotations

import json

import pytest

import nudge.state as state
from nudge.sleep_reminders import (
    SLEEP_AFTER_SKIP_STATUS,
    is_sleep_terminal_action,
    later_sleep_reminders_after,
)


@pytest.fixture(autouse=True)
def isolated_state_db(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")
    monkeypatch.setattr(state, "_migrated", False)


def test_sleep_terminal_detection_excludes_preparation_and_sleep_logs():
    assert is_sleep_terminal_action({"type": "reminder", "summary": "关机睡觉"})
    assert not is_sleep_terminal_action({"type": "reminder", "summary": "睡前洗漱"})
    assert not is_sleep_terminal_action({"type": "reminder", "summary": "睡眠记录"})
    assert not is_sleep_terminal_action({"type": "note", "summary": "关机睡觉"})


def test_later_sleep_reminders_after_returns_pending_same_night_candidates_only():
    completed = {
        "id": "done",
        "type": "reminder",
        "summary": "关机睡觉",
        "scheduled_at": "2026-06-07 23:00",
        "completed_at": "2026-06-07 23:05",
        "status": "done",
    }
    actions = [
        completed,
        {
            "id": "later",
            "type": "reminder",
            "summary": "别熬夜",
            "scheduled_at": "2026-06-07 23:30",
            "status": "pending",
        },
        {
            "id": "log",
            "type": "reminder",
            "summary": "睡眠记录",
            "scheduled_at": "2026-06-08 07:30",
            "status": "pending",
        },
        {
            "id": "done-later",
            "type": "reminder",
            "summary": "该睡觉",
            "scheduled_at": "2026-06-08 00:30",
            "status": "done",
        },
    ]

    assert [action["id"] for action in later_sleep_reminders_after(completed, actions)] == ["later"]


def test_complete_sleep_action_cascades_later_sleep_reminders_to_neutral_skip():
    terminal_id = state.log_action(
        "reminder",
        "关机睡觉",
        scheduled_at="2026-06-07 23:00",
        status="pending",
    )
    later_id = state.log_action(
        "reminder",
        "别熬夜",
        scheduled_at="2026-06-07 23:30",
        status="pending",
    )
    log_id = state.log_action(
        "reminder",
        "睡眠记录",
        scheduled_at="2026-06-08 07:30",
        status="pending",
    )

    skipped = state.complete_action(terminal_id, completed_at="2026-06-07 23:05")

    assert [action["id"] for action in skipped] == [later_id]
    later = state.get_action(later_id)
    sleep_log = state.get_action(log_id)
    assert later["status"] == SLEEP_AFTER_SKIP_STATUS
    assert sleep_log["status"] == "pending"
    feedback = json.loads(later["feedback"])
    assert feedback["source"] == "nudge sleep auto-skip"
    assert feedback["completed_sleep_action_id"] == terminal_id
