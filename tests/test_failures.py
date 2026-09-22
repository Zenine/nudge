"""Tests for failure visibility aggregation."""

from datetime import datetime

from nudge.failures import build_failure_visibility_report, failure_followup_section, render_failure_visibility_report


def test_build_failure_visibility_report_groups_overdue_and_unexplained_actions():
    actions = [
        {
            "id": "pending-old",
            "summary": "补记录早餐",
            "status": "pending",
            "scheduled_at": "2026-04-27 08:00",
        },
        {
            "id": "pending-new",
            "summary": "今天晚点反馈",
            "status": "created",
            "scheduled_at": "2026-04-28 20:00",
        },
        {
            "id": "blocked-no-next",
            "summary": "等医生回复",
            "status": "blocked",
            "scheduled_at": "2026-04-27 09:00",
            "feedback": '{"reason": "waiting_on_other"}',
        },
        {
            "id": "deferred-no-reason",
            "summary": "力量训练",
            "status": "deferred",
            "scheduled_at": "2026-04-26 18:00",
            "feedback": '{"next_action": "reschedule", "note": "周末补"}',
        },
        {
            "id": "skipped-explained",
            "summary": "散步",
            "status": "skipped",
            "scheduled_at": "2026-04-27 19:00",
            "feedback": '{"reason": "weather", "next_action": "keep"}',
        },
    ]

    report = build_failure_visibility_report(
        actions,
        now=datetime(2026, 4, 28, 12, 0),
        overdue_hours=24,
    )

    assert report["summary"] == {
        "pending_overdue": 1,
        "blocked_open": 1,
        "deferred_open": 1,
        "missing_reason": 1,
        "missing_next_action": 1,
    }
    assert [item["id"] for item in report["pending_overdue"]] == ["pending-old"]
    assert report["pending_overdue"][0]["age_hours"] == 28
    assert [item["id"] for item in report["blocked_open"]] == ["blocked-no-next"]
    assert [item["id"] for item in report["missing_reason"]] == ["deferred-no-reason"]
    assert [item["id"] for item in report["missing_next_action"]] == ["blocked-no-next"]
    assert "nudge log blocked --id blocked-no-next" in report["blocked_open"][0]["followup_command"]
    assert "--reason waiting_on_other" in report["blocked_open"][0]["followup_command"]
    assert "--next-action keep" in report["blocked_open"][0]["followup_command"]


def test_render_failure_visibility_report_and_briefing_section():
    report = build_failure_visibility_report(
        [
            {
                "id": "pending-old",
                "summary": "补记录早餐",
                "status": "pending",
                "scheduled_at": "2026-04-27 08:00",
            }
        ],
        now=datetime(2026, 4, 28, 12, 0),
        overdue_hours=24,
    )

    text = render_failure_visibility_report(report)
    section = failure_followup_section(report)

    assert "失败/阻塞可见性" in text
    assert "overdue=1" in text
    assert "补记录早餐" in text
    assert "nudge log" in text
    assert "失败/阻塞待跟进" in section
    assert "补记录早餐" in section


def test_due_soon_bucket_collects_upcoming_pending_when_enabled():
    actions = [
        {"id": "upcoming-soon", "summary": "12:30 吃药", "status": "pending", "scheduled_at": "2026-04-28 12:30"},
        {"id": "upcoming-far", "summary": "晚上跑步", "status": "created", "scheduled_at": "2026-04-28 18:00"},
        {"id": "already-overdue", "summary": "补记录早餐", "status": "pending", "scheduled_at": "2026-04-27 08:00"},
    ]

    report = build_failure_visibility_report(
        actions,
        now=datetime(2026, 4, 28, 12, 0),
        overdue_hours=24,
        due_soon_minutes=60,
    )

    assert report["summary"]["due_soon"] == 1
    assert [item["id"] for item in report["due_soon"]] == ["upcoming-soon"]
    # Upcoming does not double-count as overdue; the past pending stays overdue.
    assert report["summary"]["pending_overdue"] == 1
    # Upcoming (future) is not counted as a failure in total_open_issues.
    assert report["total_open_issues"] == report["summary"]["pending_overdue"]
    # Enabled report also surfaces due_soon in the priority follow-up view.
    assert "12:30 吃药" in render_failure_visibility_report(report)
    assert "due_soon=1" in render_failure_visibility_report(report)


def test_due_soon_bucket_absent_by_default():
    report = build_failure_visibility_report(
        [{"id": "upcoming-soon", "summary": "12:30 吃药", "status": "pending", "scheduled_at": "2026-04-28 12:30"}],
        now=datetime(2026, 4, 28, 12, 0),
    )

    assert "due_soon" not in report["summary"]
    assert "due_soon" not in report


def test_failure_visibility_empty_state_is_quiet():
    report = build_failure_visibility_report([], now=datetime(2026, 4, 28, 12, 0))

    assert report["ok"] is True
    assert report["summary"] == {
        "pending_overdue": 0,
        "blocked_open": 0,
        "deferred_open": 0,
        "missing_reason": 0,
        "missing_next_action": 0,
    }
    assert "暂无失败/阻塞待跟进" in render_failure_visibility_report(report)
    assert failure_followup_section(report) == ""
