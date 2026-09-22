"""Tests for safe adaptation planning and application."""

from nudge.adapt import apply_adaptation_plan, build_adaptation_plan


def test_build_adaptation_plan_creates_safe_move_item_for_external_calendar_action():
    actions = [
        {
            "id": "a1",
            "type": "calendar_event",
            "summary": "阅读 30 分钟",
            "status": "created",
            "scheduled_at": "2026-04-27 21:00",
            "external_id": "event-uid-1",
        }
    ]
    suggestions = [
        {
            "type": "move",
            "title": "把阅读提前",
            "reason": "晚上容易跳过",
            "action_id": "a1",
            "start": "2026-04-27 08:00",
            "end": "2026-04-27 08:30",
        }
    ]

    plan = build_adaptation_plan(suggestions, actions)

    assert plan == [
        {
            "type": "move",
            "title": "把阅读提前",
            "reason": "晚上容易跳过",
            "operation": "update",
            "safe": True,
            "action_id": "a1",
            "external_id": "event-uid-1",
            "summary": "阅读 30 分钟",
            "start": "2026-04-27 08:00",
            "end": "2026-04-27 08:30",
            "problems": [],
        }
    ]


def test_build_adaptation_plan_marks_old_actions_without_external_id_unsafe():
    actions = [
        {
            "id": "old1",
            "type": "calendar_event",
            "summary": "阅读 30 分钟",
            "status": "created",
            "scheduled_at": "2026-04-27 21:00",
            "external_id": None,
        }
    ]
    suggestions = [{"type": "delete", "action_id": "old1", "title": "删除过量任务"}]

    plan = build_adaptation_plan(suggestions, actions)

    assert plan[0]["operation"] == "delete"
    assert plan[0]["safe"] is False
    assert "missing external_id" in plan[0]["problems"]


def test_build_adaptation_plan_supports_reduce_with_duration_minutes():
    actions = [
        {
            "id": "a1",
            "type": "calendar_event",
            "summary": "阅读 30 分钟",
            "status": "created",
            "scheduled_at": "2026-04-27 21:00",
            "external_id": "event-uid-1",
        }
    ]
    suggestions = [{"type": "reduce", "action_id": "a1", "duration_minutes": 10}]

    plan = build_adaptation_plan(suggestions, actions)

    assert plan[0]["safe"] is True
    assert plan[0]["operation"] == "update"
    assert plan[0]["start"] == "2026-04-27 21:00"
    assert plan[0]["end"] == "2026-04-27 21:10"


def test_build_adaptation_plan_marks_non_numeric_reduce_duration_unsafe():
    actions = [
        {
            "id": "a1",
            "type": "calendar_event",
            "summary": "阅读 30 分钟",
            "status": "created",
            "scheduled_at": "2026-04-27 21:00",
            "external_id": "event-uid-1",
        }
    ]
    suggestions = [{"type": "reduce", "action_id": "a1", "duration_minutes": "ten"}]

    plan = build_adaptation_plan(suggestions, actions)

    assert plan[0]["safe"] is False
    assert "invalid duration_minutes" in plan[0]["problems"]


def test_build_adaptation_plan_marks_increase_with_invalid_datetime_unsafe():
    suggestions = [
        {
            "type": "increase",
            "title": "新增坏时间",
            "start": "tomorrow",
            "end": "later",
            "calendar_name": "Family",
        }
    ]

    plan = build_adaptation_plan(suggestions, [])

    assert plan[0]["safe"] is False
    assert "invalid start/end datetime" in plan[0]["problems"]


def test_build_adaptation_plan_defaults_increase_calendar_to_personal():
    suggestions = [
        {
            "type": "increase",
            "title": "补一次阅读",
            "summary": "新增阅读",
            "start": "2026-04-27 08:00",
            "end": "2026-04-27 08:30",
        }
    ]

    plan = build_adaptation_plan(suggestions, [])

    assert plan[0]["safe"] is True
    assert plan[0]["operation"] == "create"
    assert plan[0]["calendar_name"] == "Personal"
    assert plan[0]["problems"] == []


def test_apply_adaptation_plan_updates_calendar_and_preserves_old_action_history(monkeypatch):
    calls = []
    logged = []

    monkeypatch.setattr(
        "nudge.adapt.update_event_by_uid",
        lambda uid, summary, start, end, timeout=30: calls.append(("update", uid, summary, start, end)) or (True, "updated"),
    )
    monkeypatch.setattr(
        "nudge.adapt.update_action_status",
        lambda action_id, status, feedback=None: calls.append(("status", action_id, status, feedback)),
    )
    monkeypatch.setattr(
        "nudge.adapt.log_action",
        lambda **kwargs: logged.append(kwargs) or "new-action",
    )

    result = apply_adaptation_plan([
        {
            "type": "move",
            "operation": "update",
            "safe": True,
            "action_id": "a1",
            "external_id": "event-uid-1",
            "summary": "阅读 30 分钟",
            "start": "2026-04-27 08:00",
            "end": "2026-04-27 08:30",
            "problems": [],
        }
    ])

    assert result == [{"ok": True, "action_id": "a1", "operation": "update", "message": "updated"}]
    assert calls[0] == ("update", "event-uid-1", "阅读 30 分钟", "2026-04-27 08:00", "2026-04-27 08:30")
    assert calls[1][0:3] == ("status", "a1", "adapted")
    assert logged == [
        {
            "action_type": "calendar_event",
            "summary": "阅读 30 分钟",
            "scheduled_at": "2026-04-27 08:00",
            "external_id": "event-uid-1",
            "status": "created",
        }
    ]


def test_build_adaptation_plan_supports_safe_split_parts():
    actions = [
        {
            "id": "a1",
            "type": "calendar_event",
            "summary": "阅读 60 分钟",
            "status": "created",
            "scheduled_at": "2026-04-27 21:00",
            "external_id": "event-uid-1",
        }
    ]
    suggestions = [
        {
            "type": "split",
            "title": "拆分阅读",
            "reason": "晚上 60 分钟太长",
            "action_id": "a1",
            "calendar_name": "Family",
            "parts": [
                {"summary": "阅读 15 分钟", "start": "2026-04-27 08:00", "end": "2026-04-27 08:15"},
                {"summary": "阅读 15 分钟", "start": "2026-04-27 21:00", "end": "2026-04-27 21:15"},
            ],
        }
    ]

    plan = build_adaptation_plan(suggestions, actions)

    assert plan == [
        {
            "type": "split",
            "title": "拆分阅读",
            "reason": "晚上 60 分钟太长",
            "operation": "split",
            "safe": True,
            "action_id": "a1",
            "external_id": "event-uid-1",
            "summary": "阅读 60 分钟",
            "calendar_name": "Family",
            "parts": [
                {"summary": "阅读 15 分钟", "start": "2026-04-27 08:00", "end": "2026-04-27 08:15"},
                {"summary": "阅读 15 分钟", "start": "2026-04-27 21:00", "end": "2026-04-27 21:15"},
            ],
            "problems": [],
        }
    ]


def test_build_adaptation_plan_infers_split_calendar_from_external_id():
    actions = [
        {
            "id": "a1",
            "type": "calendar_event",
            "summary": "阅读 60 分钟",
            "status": "created",
            "scheduled_at": "2026-04-27 21:00",
            "external_id": "Family::event-uid-1",
        }
    ]
    suggestions = [
        {
            "type": "split",
            "action_id": "a1",
            "parts": [
                {"summary": "阅读 20 分钟", "start": "2026-04-27 08:00", "end": "2026-04-27 08:20"},
                {"summary": "阅读 20 分钟", "start": "2026-04-27 21:00", "end": "2026-04-27 21:20"},
            ],
        }
    ]

    plan = build_adaptation_plan(suggestions, actions)

    assert plan[0]["safe"] is True
    assert plan[0]["calendar_name"] == "Family"
    assert plan[0]["problems"] == []


def test_apply_adaptation_plan_splits_calendar_event_and_logs_each_part(monkeypatch):
    calls = []
    logged = []

    monkeypatch.setattr(
        "nudge.adapt.update_event_by_uid",
        lambda uid, summary, start, end, timeout=30: calls.append(("update", uid, summary, start, end)) or (True, "updated-first"),
    )
    monkeypatch.setattr(
        "nudge.adapt.create_calendar_event",
        lambda summary, start, end, calendar_name, notes=None, timeout=30: calls.append(("create", summary, start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"), calendar_name, notes)) or (True, "new-uid-2"),
    )
    monkeypatch.setattr(
        "nudge.adapt.update_action_status",
        lambda action_id, status, feedback=None: calls.append(("status", action_id, status, feedback)),
    )
    monkeypatch.setattr("nudge.adapt.log_action", lambda **kwargs: logged.append(kwargs) or f"new-{len(logged)}")

    result = apply_adaptation_plan([
        {
            "type": "split",
            "operation": "split",
            "safe": True,
            "action_id": "a1",
            "external_id": "Family::event-uid-1",
            "calendar_name": "Family",
            "reason": "太长",
            "parts": [
                {"summary": "阅读 15 分钟", "start": "2026-04-27 08:00", "end": "2026-04-27 08:15"},
                {"summary": "阅读 15 分钟", "start": "2026-04-27 21:00", "end": "2026-04-27 21:15"},
            ],
            "problems": [],
        }
    ])

    assert result == [{"ok": True, "action_id": "a1", "operation": "split", "message": "split into 2 parts"}]
    assert calls[0] == ("update", "Family::event-uid-1", "阅读 15 分钟", "2026-04-27 08:00", "2026-04-27 08:15")
    assert calls[1][0:5] == ("create", "阅读 15 分钟", "2026-04-27 21:00", "2026-04-27 21:15", "Family")
    assert calls[2][0:3] == ("status", "a1", "adapted")
    assert logged[0]["external_id"] == "Family::event-uid-1"
    assert logged[1]["external_id"] == "Family::new-uid-2"
    assert [item["summary"] for item in logged] == ["阅读 15 分钟", "阅读 15 分钟"]


def test_apply_adaptation_plan_defaults_created_events_to_personal_calendar(monkeypatch):
    calls = []
    logged = []

    monkeypatch.setattr(
        "nudge.adapt.create_calendar_event",
        lambda summary, start, end, calendar_name, notes=None, timeout=30: calls.append((summary, calendar_name)) or (True, "new-uid"),
    )
    monkeypatch.setattr("nudge.adapt.log_action", lambda **kwargs: logged.append(kwargs) or "new-action")

    result = apply_adaptation_plan([
        {
            "type": "increase",
            "operation": "create",
            "safe": True,
            "summary": "新增阅读",
            "start": "2026-04-27 08:00",
            "end": "2026-04-27 08:30",
            "reason": "补一次",
            "problems": [],
        }
    ])

    assert result == [{"ok": True, "action_id": None, "operation": "create", "message": "new-uid"}]
    assert calls == [("新增阅读", "Personal")]
    assert logged[0]["external_id"] == "Personal::new-uid"


def test_build_adaptation_plan_marks_non_calendar_target_unsafe():
    actions = [
        {
            "id": "r1",
            "type": "reminder",
            "summary": "20:00 闭环",
            "status": "created",
            "scheduled_at": "2026-07-05 20:00",
            "external_id": "nudge://reminder/abc",
        }
    ]
    suggestions = [
        {
            "type": "move",
            "title": "推迟闭环",
            "reason": "今天未反馈",
            "action_id": "r1",
            "start": "2026-07-06 20:00",
            "end": "2026-07-06 20:15",
        }
    ]

    plan = build_adaptation_plan(suggestions, actions)

    assert plan[0]["safe"] is False
    assert plan[0]["operation"] == "update"
    assert "action type is reminder" in plan[0]["problems"]
