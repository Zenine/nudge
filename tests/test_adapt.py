"""Regression coverage for Calendar adaptation state consistency."""

import json

import pytest

from nudge.adapt import apply_adaptation_plan
from nudge.state import get_action, get_actions, log_action


@pytest.fixture(autouse=True)
def isolate_state(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")


def _calendar_action(summary: str = "Deep work", external_id: str = "Personal::event-1") -> str:
    return log_action(
        action_type="calendar_event",
        summary=summary,
        scheduled_at="2026-06-08 09:00",
        external_id=external_id,
        status="created",
    )


def _safe_update_item(action_id: str, external_id: str = "Personal::event-1") -> dict:
    return {
        "safe": True,
        "operation": "update",
        "type": "move",
        "reason": "schedule conflict",
        "action_id": action_id,
        "external_id": external_id,
        "summary": "Deep work moved",
        "start": "2026-06-08 10:00",
        "end": "2026-06-08 11:00",
    }


def _safe_split_item(action_id: str, external_id: str = "Personal::event-1") -> dict:
    return {
        "safe": True,
        "operation": "split",
        "type": "split",
        "reason": "too large",
        "action_id": action_id,
        "external_id": external_id,
        "calendar_name": "Personal",
        "parts": [
            {"summary": "Deep work A", "start": "2026-06-08 09:00", "end": "2026-06-08 09:30"},
            {"summary": "Deep work B", "start": "2026-06-08 10:00", "end": "2026-06-08 10:30"},
            {"summary": "Deep work C", "start": "2026-06-08 11:00", "end": "2026-06-08 11:30"},
        ],
    }


def test_update_success_marks_original_without_duplicate_external_id_log(monkeypatch):
    action_id = _calendar_action()
    update_calls = []
    monkeypatch.setattr(
        "nudge.adapt.update_event_by_uid",
        lambda *args, **kwargs: update_calls.append((args, kwargs)) or (True, "updated event-1"),
    )

    results = apply_adaptation_plan([_safe_update_item(action_id)])

    assert results == [{"ok": True, "action_id": action_id, "operation": "update", "message": "updated event-1"}]
    assert len(update_calls) == 1
    actions = get_actions()
    assert len(actions) == 1
    assert actions[0]["id"] == action_id
    assert actions[0]["external_id"] == "Personal::event-1"
    assert actions[0]["status"] == "adapted"
    feedback = json.loads(actions[0]["feedback"])
    assert feedback["source"] == "review weekly --adapt"
    assert feedback["type"] == "move"
    assert feedback["external_id"] == "Personal::event-1"
    assert feedback["adapted_to"]["summary"] == "Deep work moved"


def test_split_success_logs_only_new_calendar_parts_without_duplicate_original_external_id(monkeypatch):
    action_id = _calendar_action()
    monkeypatch.setattr("nudge.adapt.update_event_by_uid", lambda *args, **kwargs: (True, "updated event-1"))
    created_messages = iter(["event-2", "event-3"])
    create_calls = []

    def fake_create_calendar_event(**kwargs):
        create_calls.append(kwargs)
        return True, next(created_messages)

    monkeypatch.setattr("nudge.adapt.create_calendar_event", fake_create_calendar_event)

    results = apply_adaptation_plan([_safe_split_item(action_id)])

    assert results == [{"ok": True, "action_id": action_id, "operation": "split", "message": "split into 3 parts"}]
    assert [call["summary"] for call in create_calls] == ["Deep work B", "Deep work C"]
    original = get_action(action_id)
    assert original["status"] == "adapted"
    feedback = json.loads(original["feedback"])
    assert feedback["type"] == "split"
    assert feedback["parts"][0]["external_id"] == "Personal::event-1"
    actions_by_external_id = {action["external_id"]: action for action in get_actions()}
    assert actions_by_external_id["Personal::event-2"]["status"] == "created"
    assert actions_by_external_id["Personal::event-3"]["status"] == "created"
    assert sum(1 for action in get_actions() if action["external_id"] == "Personal::event-1") == 1


def test_split_partial_create_failure_records_external_mutation_risk(monkeypatch):
    action_id = _calendar_action()
    monkeypatch.setattr("nudge.adapt.update_event_by_uid", lambda *args, **kwargs: (True, "updated event-1"))

    def fake_create_calendar_event(**kwargs):
        if kwargs["summary"] == "Deep work C":
            return False, "Calendar create failed"
        return True, "event-2"

    monkeypatch.setattr("nudge.adapt.create_calendar_event", fake_create_calendar_event)

    results = apply_adaptation_plan([_safe_split_item(action_id)])

    assert results == [{
        "ok": False,
        "action_id": action_id,
        "operation": "split",
        "message": "partial Calendar mutation: Calendar create failed",
    }]
    original = get_action(action_id)
    assert original["status"] == "blocked"
    feedback = json.loads(original["feedback"])
    assert feedback["source"] == "review weekly --adapt"
    assert feedback["type"] == "split"
    assert feedback["partial_external_mutation"] is True
    assert feedback["mutated_external_ids"] == ["Personal::event-1", "Personal::event-2"]
    assert feedback["failed_part"]["summary"] == "Deep work C"
