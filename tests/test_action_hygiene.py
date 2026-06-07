"""Tests for action normalization helpers."""

from __future__ import annotations

from nudge.action_hygiene import normalize_reminder_action, normalize_reminder_title


def test_normalize_reminder_title_strips_plain_due_date_suffix():
    assert normalize_reminder_title("提交日报 - 2026-06-07 18:00", "2026-06-07 18:00") == "提交日报"


def test_normalize_reminder_title_strips_parenthesized_due_date_suffix():
    assert normalize_reminder_title("提交日报（2026-06-07 18:00）", "2026-06-07 18:00") == "提交日报"


def test_normalize_reminder_action_copies_reminder_and_leaves_input_unchanged():
    action = {"type": "reminder", "name": "提交日报（2026-06-07）", "due_date": "2026-06-07 18:00"}

    normalized = normalize_reminder_action(action)

    assert normalized == {"type": "reminder", "name": "提交日报", "due_date": "2026-06-07 18:00"}
    assert action["name"] == "提交日报（2026-06-07）"


def test_normalize_reminder_action_returns_non_reminder_unchanged():
    action = {"type": "calendar_event", "summary": "项目同步"}

    assert normalize_reminder_action(action) is action
