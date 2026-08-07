from datetime import date, datetime

from nudge.commands.daily import _sync_docs_audit
from nudge.commands.reminders import _completed_candidates
from nudge.failures import build_failure_visibility_report


def _reminder_action(**overrides):
    action = {
        "id": "reminder-1",
        "type": "reminder",
        "summary": "核对提醒",
        "scheduled_at": "2026-07-15 09:00",
        "status": "created",
    }
    action.update(overrides)
    return action


def test_missing_apple_reminder_does_not_become_done_candidate():
    candidates, open_count = _completed_candidates(
        [_reminder_action()],
        incomplete=[],
        completed=[],
    )

    assert candidates == []
    assert open_count == 0


def test_completed_apple_reminder_is_still_a_done_candidate():
    completed = [{
        "name": "核对提醒",
        "due_time": "09:00",
        "due_at": "2026-07-15 09:00",
        "completed_at": "2026-07-15 10:00",
    }]

    candidates, open_count = _completed_candidates(
        [_reminder_action()],
        incomplete=[],
        completed=completed,
    )

    assert candidates == [{
        "id": "reminder-1",
        "summary": "核对提醒",
        "scheduled_at": "2026-07-15 09:00",
        "completed_at": "2026-07-15 10:00",
    }]
    assert open_count == 0


def test_elapsed_calendar_event_is_not_reported_as_pending_task_failure():
    report = build_failure_visibility_report(
        [
            _reminder_action(),
            {
                "id": "event-1",
                "type": "calendar_event",
                "summary": "已经过去的会议",
                "scheduled_at": "2026-07-15 09:00",
                "status": "created",
            },
        ],
        now=datetime(2026, 7, 16, 12, 0),
        overdue_hours=24,
    )

    assert report["summary"]["pending_overdue"] == 1
    assert [item["id"] for item in report["pending_overdue"]] == ["reminder-1"]


def test_docs_audit_reuses_open_maintenance_action_from_an_earlier_date(monkeypatch):
    old_action = {
        "id": "maintenance-1",
        "type": "maintenance",
        "summary": "[Nudge Docs] 本周文档需要维护",
        "scheduled_at": "2026-04-30 09:00",
        "status": "created",
    }
    created = []

    monkeypatch.setattr(
        "nudge.commands.daily.audit_docs",
        lambda _root: {"summary": {"errors": 0, "warnings": 1}},
    )

    def fake_get_actions(**filters):
        return [] if filters else [old_action]

    monkeypatch.setattr("nudge.commands.daily.get_actions", fake_get_actions)
    monkeypatch.setattr(
        "nudge.commands.daily.log_action",
        lambda **kwargs: created.append(kwargs) or "new-maintenance",
    )

    payload = _sync_docs_audit(target_date=date(2026, 7, 16), apply_changes=True)

    assert payload["existing_action_id"] == "maintenance-1"
    assert created == []
