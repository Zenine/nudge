"""Tests for briefing command error handling."""

from click.testing import CliRunner

from nudge.commands.briefing import briefing_command


def test_briefing_renders_actionable_calendar_error(monkeypatch):
    monkeypatch.setattr(
        "nudge.commands.briefing.load_config",
        lambda: {"general": {"default_calendar": "Family"}},
    )
    monkeypatch.setattr("nudge.commands.briefing.get_configured_calendar_names", lambda config: ["Family"])
    monkeypatch.setattr(
        "nudge.commands.briefing.get_today_events",
        lambda calendar_names=None: (_ for _ in ()).throw(RuntimeError("not authorized")),
    )

    result = CliRunner().invoke(briefing_command, ["morning"])

    assert result.exit_code == 1
    assert "APPLE_PERMISSION_DENIED" in result.output
    assert "nudge doctor" in result.output


def test_evening_briefing_appends_feedback_pullback(monkeypatch):
    monkeypatch.setattr(
        "nudge.commands.briefing.load_config",
        lambda: {"general": {"default_calendar": "Family"}},
    )
    monkeypatch.setattr("nudge.commands.briefing.get_configured_calendar_names", lambda config: ["Family"])
    monkeypatch.setattr("nudge.commands.briefing.get_today_events", lambda calendar_names=None: [])
    monkeypatch.setattr(
        "nudge.commands.briefing.get_actions",
        lambda since=None, until=None: [
            {"id": "a1", "summary": "阅读 30 分钟", "status": "created", "scheduled_at": "2026-04-27 21:00"},
            {"id": "a2", "summary": "跑步", "status": "done", "scheduled_at": "2026-04-27 07:00"},
        ],
    )
    monkeypatch.setattr("nudge.commands.briefing.get_habit_streaks", lambda: {})
    monkeypatch.setattr(
        "nudge.commands.briefing.generate_evening_review",
        lambda events, completed_actions, skipped_actions, habit_streaks: "晚报正文",
    )
    monkeypatch.setattr(
        "nudge.commands.briefing.build_daemon_health_report",
        lambda: {"ok": True, "issues": []},
    )

    result = CliRunner().invoke(briefing_command, ["evening"])

    assert result.exit_code == 0, result.output
    assert "晚报正文" in result.output
    assert "待反馈 action" in result.output
    assert "阅读 30 分钟" in result.output
    assert "nudge log done --id a1" in result.output
    assert "批量回执模板" in result.output
    assert "nudge feedback apply --json" in result.output
    assert '"id": "a1"' in result.output
    assert '"status": "done"' in result.output


def test_morning_briefing_appends_daemon_health_alerts(monkeypatch):
    monkeypatch.setattr(
        "nudge.commands.briefing.load_config",
        lambda: {"general": {"default_calendar": "Family"}},
    )
    monkeypatch.setattr("nudge.commands.briefing.get_configured_calendar_names", lambda config: ["Family"])
    monkeypatch.setattr("nudge.commands.briefing.get_today_events", lambda calendar_names=None: [])
    monkeypatch.setattr("nudge.commands.briefing.get_due_today", lambda: [])
    monkeypatch.setattr("nudge.commands.briefing.get_unread_count", lambda: 0)
    monkeypatch.setattr("nudge.commands.briefing.get_recent_messages", lambda n=5: [])
    monkeypatch.setattr(
        "nudge.commands.briefing.generate_briefing",
        lambda events, reminders, unread_count, recent_emails: "早报正文",
    )
    monkeypatch.setattr(
        "nudge.commands.briefing.build_daemon_health_report",
        lambda: {
            "ok": False,
            "status": "fail",
            "queue": {"queued": 2, "running": 1, "failed": 0, "dead_letter": 1},
            "stale_running": {
                "count": 1,
                "items": [{"request_id": "req-stale", "will_dead_letter": False}],
            },
            "issues": [
                {
                    "severity": "warn",
                    "code": "LAUNCHD_NOT_LOADED",
                    "message": "daemon LaunchAgent 当前未加载。",
                },
                {
                    "severity": "warn",
                    "code": "STALE_RUNNING_COMMANDS",
                    "message": "存在卡在 running 的旧命令。",
                },
                {
                    "severity": "fail",
                    "code": "DEAD_LETTER_COMMANDS",
                    "message": "存在 dead_letter 命令。",
                },
            ],
        },
    )

    result = CliRunner().invoke(briefing_command, ["morning"])

    assert result.exit_code == 0, result.output
    assert "早报正文" in result.output
    assert "Nudge daemon 告警" in result.output
    assert "LAUNCHD_NOT_LOADED" in result.output
    assert "DEAD_LETTER_COMMANDS" in result.output
    assert "queued=2 running=1 dead_letter=1" in result.output
    assert "nudge daemon health" in result.output
    assert "nudge daemon recover" in result.output
    assert "nudge daemon queue --status dead_letter" in result.output


def test_briefing_notify_sends_separate_daemon_alert_notification(monkeypatch):
    notifications = []

    monkeypatch.setattr(
        "nudge.commands.briefing.load_config",
        lambda: {"general": {"default_calendar": "Family"}},
    )
    monkeypatch.setattr("nudge.commands.briefing.get_configured_calendar_names", lambda config: ["Family"])
    monkeypatch.setattr("nudge.commands.briefing.get_today_events", lambda calendar_names=None: [])
    monkeypatch.setattr("nudge.commands.briefing.get_due_today", lambda: [])
    monkeypatch.setattr("nudge.commands.briefing.get_unread_count", lambda: 0)
    monkeypatch.setattr("nudge.commands.briefing.get_recent_messages", lambda n=5: [])
    monkeypatch.setattr(
        "nudge.commands.briefing.generate_briefing",
        lambda events, reminders, unread_count, recent_emails: "早报正文",
    )
    monkeypatch.setattr(
        "nudge.commands.briefing.build_daemon_health_report",
        lambda: {
            "ok": False,
            "status": "warn",
            "queue": {"queued": 0, "running": 1, "failed": 0, "dead_letter": 0},
            "stale_running": {"count": 1, "items": [{"request_id": "req-stale"}]},
            "issues": [
                {
                    "severity": "warn",
                    "code": "STALE_RUNNING_COMMANDS",
                    "message": "存在卡在 running 的旧命令。",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "nudge.commands.briefing.notify",
        lambda title, message, subtitle=None, sound="default": notifications.append({
            "title": title,
            "message": message,
            "subtitle": subtitle,
            "sound": sound,
        }) or (True, ""),
    )

    result = CliRunner().invoke(briefing_command, ["morning", "--notify"])

    assert result.exit_code == 0, result.output
    assert [item["title"] for item in notifications] == ["Nudge 早报", "Nudge daemon 告警"]
    assert "Nudge daemon 告警" not in notifications[0]["message"]
    assert "STALE_RUNNING_COMMANDS" in notifications[1]["message"]
    assert "nudge daemon recover" in notifications[1]["message"]


def test_evening_briefing_suppresses_daemon_alerts_when_healthy(monkeypatch):
    monkeypatch.setattr(
        "nudge.commands.briefing.load_config",
        lambda: {"general": {"default_calendar": "Family"}},
    )
    monkeypatch.setattr("nudge.commands.briefing.get_configured_calendar_names", lambda config: ["Family"])
    monkeypatch.setattr("nudge.commands.briefing.get_today_events", lambda calendar_names=None: [])
    monkeypatch.setattr("nudge.commands.briefing.get_actions", lambda since=None, until=None: [])
    monkeypatch.setattr("nudge.commands.briefing.get_habit_streaks", lambda: {})
    monkeypatch.setattr(
        "nudge.commands.briefing.generate_evening_review",
        lambda events, completed_actions, skipped_actions, habit_streaks: "晚报正文",
    )
    monkeypatch.setattr(
        "nudge.commands.briefing.build_daemon_health_report",
        lambda: {
            "ok": True,
            "status": "ok",
            "queue": {"queued": 0, "running": 0, "failed": 0, "dead_letter": 0},
            "stale_running": {"count": 0, "items": []},
            "issues": [],
        },
    )

    result = CliRunner().invoke(briefing_command, ["evening"])

    assert result.exit_code == 0, result.output
    assert "晚报正文" in result.output
    assert "Nudge daemon 告警" not in result.output


def test_evening_briefing_appends_failure_followup_section(monkeypatch):
    monkeypatch.setattr(
        "nudge.commands.briefing.load_config",
        lambda: {"general": {"default_calendar": "Family"}},
    )
    monkeypatch.setattr("nudge.commands.briefing.get_configured_calendar_names", lambda config: ["Family"])
    monkeypatch.setattr("nudge.commands.briefing.get_today_events", lambda calendar_names=None: [])
    monkeypatch.setattr(
        "nudge.commands.briefing.get_actions",
        lambda since=None, until=None: [
            {
                "id": "late1",
                "summary": "补记录早餐",
                "status": "created",
                "scheduled_at": "2000-01-01 08:00",
            },
            {
                "id": "block1",
                "summary": "等医生回复",
                "status": "blocked",
                "scheduled_at": "2000-01-01 09:00",
                "feedback": '{"reason": "waiting_on_other"}',
            },
        ],
    )
    monkeypatch.setattr("nudge.commands.briefing.get_habit_streaks", lambda: {})
    monkeypatch.setattr(
        "nudge.commands.briefing.generate_evening_review",
        lambda events, completed_actions, skipped_actions, habit_streaks: "晚报正文",
    )
    monkeypatch.setattr(
        "nudge.commands.briefing.build_daemon_health_report",
        lambda: {
            "ok": True,
            "status": "ok",
            "queue": {"queued": 0, "running": 0, "failed": 0, "dead_letter": 0},
            "stale_running": {"count": 0, "items": []},
            "issues": [],
        },
    )

    result = CliRunner().invoke(briefing_command, ["evening"])

    assert result.exit_code == 0, result.output
    assert "失败/阻塞待跟进" in result.output
    assert "overdue=1" in result.output
    assert "blocked=1" in result.output
    assert "补记录早餐" in result.output
    assert "等医生回复" in result.output


def test_evening_briefing_appends_health_context(monkeypatch):
    monkeypatch.setattr(
        "nudge.commands.briefing.load_config",
        lambda: {"general": {"default_calendar": "Family"}},
    )
    monkeypatch.setattr("nudge.commands.briefing.get_configured_calendar_names", lambda config: ["Family"])
    monkeypatch.setattr("nudge.commands.briefing.get_today_events", lambda calendar_names=None: [])
    monkeypatch.setattr("nudge.commands.briefing.get_actions", lambda since=None, until=None: [])
    monkeypatch.setattr("nudge.commands.briefing.get_habit_streaks", lambda: {})
    monkeypatch.setattr(
        "nudge.commands.briefing.generate_evening_review",
        lambda events, completed_actions, skipped_actions, habit_streaks: "晚报正文",
    )
    monkeypatch.setattr(
        "nudge.commands.briefing.build_daemon_health_report",
        lambda: {"ok": True, "status": "ok", "queue": {}, "stale_running": {}, "issues": []},
    )
    monkeypatch.setattr(
        "nudge.commands.briefing.get_health_daily_summaries",
        lambda since=None, until=None: [
            {"date": "2026-07-04", "steps": 8000, "sleep_asleep_minutes": 420, "active_energy_kcal": 500},
            {"date": "2026-07-05", "steps": 10000, "sleep_asleep_minutes": 390, "active_energy_kcal": 600},
        ],
    )
    monkeypatch.setattr(
        "nudge.commands.briefing.get_health_workouts",
        lambda since=None, until=None: [{"duration_minutes": 45, "start_at": "2026-07-04 18:00"}],
    )

    result = CliRunner().invoke(briefing_command, ["evening"])

    assert result.exit_code == 0, result.output
    assert "健康数据" in result.output
    assert "睡眠均值 405min" in result.output
    assert "步数均值 9000" in result.output
    assert "运动 1 次/45min" in result.output
