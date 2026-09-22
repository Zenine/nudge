"""Tests for dogfood weekly report aggregation and rendering."""

from datetime import date

from nudge.commands.doctor import CheckResult, FAIL, PASS, WARN
from nudge.dogfood import build_weekly_dogfood_report, render_weekly_dogfood_report, save_weekly_dogfood_report


def test_build_weekly_dogfood_report_counts_completion_and_adapt_metrics():
    actions = [
        {"id": "1", "type": "calendar_event", "summary": "A", "status": "done", "external_id": "Family::uid"},
        {"id": "2", "type": "reminder", "summary": "B", "status": "partial", "feedback": '{"note": "只做了一半"}'},
        {"id": "3", "type": "calendar_event", "summary": "C", "status": "skipped", "feedback": '{"note": "临时有事"}'},
        {"id": "4", "type": "calendar_event", "summary": "D", "status": "created", "external_id": "Family::uid2"},
        {
            "id": "5",
            "type": "calendar_event",
            "summary": "E",
            "status": "adapted",
            "feedback": '{"source": "review weekly --adapt"}',
        },
    ]
    checks = [
        CheckResult(PASS, "Calendar", "ok"),
        CheckResult(WARN, "Reminders", "timeout"),
        CheckResult(FAIL, "Mail", "denied"),
    ]

    report = build_weekly_dogfood_report(
        actions=actions,
        checks=checks,
        today=date(2026, 4, 26),
        note="本周主要验证闭环",
    )

    assert report["period"] == {"start": "2026-04-20", "end": "2026-04-26", "iso_week": "2026-W17"}
    assert report["actions"]["total"] == 5
    assert report["actions"]["completion_score"] == 1.5
    assert report["actions"]["completion_rate"] == 30
    assert report["actions"]["calendar_writes"] == 2
    assert report["actions"]["adapt_accepts"] == 1
    assert report["actions"]["deferred"] == 0
    assert report["actions"]["blocked"] == 0
    assert report["reasons"] == ["只做了一半", "临时有事"]
    assert report["doctor"] == {"PASS": 1, "WARN": 1, "FAIL": 1}
    assert report["note"] == "本周主要验证闭环"


def test_build_weekly_dogfood_report_tracks_feedback_needed_and_structured_reasons():
    report = build_weekly_dogfood_report(
        actions=[
            {"id": "1", "type": "calendar_event", "summary": "A", "status": "created", "scheduled_at": "2026-04-26 09:00"},
            {"id": "2", "type": "calendar_event", "summary": "B", "status": "deferred", "feedback": '{"reason": "no_time", "next_action": "reschedule", "note": "开会冲突"}'},
            {"id": "3", "type": "calendar_event", "summary": "C", "status": "blocked", "feedback": '{"reason": "waiting_on_other", "next_action": "keep"}'},
        ],
        checks=[],
        today=date(2026, 4, 26),
    )

    assert report["actions"]["pending"] == 1
    assert report["actions"]["deferred"] == 1
    assert report["actions"]["blocked"] == 1
    assert report["feedback_needed"] == [
        {"id": "1", "summary": "A", "scheduled_at": "2026-04-26 09:00"}
    ]
    assert report["reasons"] == [
        "B：no_time / reschedule · 开会冲突",
        "C：waiting_on_other / keep",
    ]


def test_build_weekly_dogfood_report_excludes_sleep_after_skip_from_completion_denominator():
    report = build_weekly_dogfood_report(
        actions=[
            {"id": "1", "type": "reminder", "summary": "22:30 睡觉", "status": "done"},
            {"id": "2", "type": "reminder", "summary": "不要熬夜", "status": "skipped_after_sleep"},
            {"id": "3", "type": "reminder", "summary": "真的该睡了", "status": "skipped_after_sleep"},
        ],
        checks=[],
        today=date(2026, 4, 26),
    )

    assert report["actions"]["total"] == 1
    assert report["actions"]["completion_score"] == 1
    assert report["actions"]["completion_rate"] == 100
    assert report["actions"]["skipped_after_sleep"] == 2

    text = render_weekly_dogfood_report(report)
    assert "完成率：100% (1/1)" in text
    assert "已睡后作废：2" in text


def test_render_weekly_dogfood_report_is_short_chinese_markdown():
    report = build_weekly_dogfood_report(
        actions=[
            {"type": "calendar_event", "summary": "A", "status": "done", "external_id": "Family::uid"},
            {"type": "calendar_event", "summary": "B", "status": "skipped", "feedback": '{"note": "太晚了"}'},
        ],
        checks=[CheckResult(PASS, "Calendar", "ok")],
        today=date(2026, 4, 26),
    )

    text = render_weekly_dogfood_report(report)

    assert "# Nudge Dogfood 周报 · 2026-W17" in text
    assert "完成率：50% (1/2)" in text
    assert "真实 Calendar 写入：1" in text
    assert "Adapt 采纳：0" in text
    assert "未完成原因" in text
    assert "太晚了" in text
    assert "Doctor：PASS 1 / WARN 0 / FAIL 0" in text


def test_render_weekly_dogfood_report_shows_feedback_needed():
    report = build_weekly_dogfood_report(
        actions=[
            {"id": "1", "type": "calendar_event", "summary": "A", "status": "created", "scheduled_at": "2026-04-26 09:00"},
        ],
        checks=[],
        today=date(2026, 4, 26),
    )

    text = render_weekly_dogfood_report(report)

    assert "待反馈 action" in text
    assert "A" in text
    assert "nudge log done --id 1" in text


def test_save_weekly_dogfood_report_writes_iso_week_file(tmp_path):
    report = build_weekly_dogfood_report(
        actions=[],
        checks=[],
        today=date(2026, 4, 26),
    )

    path = save_weekly_dogfood_report(report, base_dir=tmp_path)

    assert path == tmp_path / "dogfood" / "2026-W17.md"
    assert path.exists()
    assert "Nudge Dogfood 周报" in path.read_text()


def test_weekly_dogfood_report_includes_failure_visibility_summary():
    report = build_weekly_dogfood_report(
        actions=[
            {"id": "old", "type": "reminder", "summary": "补记录早餐", "status": "pending", "scheduled_at": "2026-04-24 08:00"},
            {"id": "blocked", "type": "calendar_event", "summary": "等医生回复", "status": "blocked", "scheduled_at": "2026-04-25 09:00", "feedback": '{"reason": "waiting_on_other"}'},
            {"id": "sleep2", "type": "reminder", "summary": "23:00 睡觉提醒", "status": "skipped_after_sleep", "scheduled_at": "2026-04-25 23:00"},
        ],
        checks=[],
        today=date(2026, 4, 26),
    )

    failure = report["failure_visibility"]
    assert failure["summary"]["pending_overdue"] == 1
    assert failure["summary"]["blocked_open"] == 1
    assert failure["summary"]["missing_next_action"] == 1
    assert failure["summary"]["missing_reason"] == 0

    text = render_weekly_dogfood_report(report)
    assert "失败可解释" in text
    assert "overdue=1" in text
    assert "blocked=1" in text
    assert "missing_next_action=1" in text


def test_weekly_dogfood_report_summarizes_feedback_sources():
    report = build_weekly_dogfood_report(
        actions=[
            {"id": "1", "type": "calendar_event", "summary": "A", "status": "skipped", "feedback": '{"source": "nudge log", "note": "太累"}'},
            {"id": "2", "type": "reminder", "summary": "B", "status": "done", "feedback": '{"source": "nudge reminders sync-completed"}'},
            {"id": "3", "type": "calendar_event", "summary": "C", "status": "partial", "feedback": '{"source_type": "agent", "channel": "mcp.report_action_status"}'},
        ],
        checks=[],
        today=date(2026, 4, 26),
    )

    assert report["feedback_sources"] == {
        "total": 3,
        "by_type": {"subjective": 1, "objective": 1, "agent": 1},
        "by_channel": {"cli.log": 1, "reminders.sync_completed": 1, "mcp.report_action_status": 1},
    }
    text = render_weekly_dogfood_report(report)
    assert "反馈来源：subjective=1 objective=1 agent=1 unknown=0" in text
