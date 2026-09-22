"""Tests for nudge.commands.review."""

from click.testing import CliRunner

from nudge.commands.review import review_command


def test_review_weekly_with_adapt_prints_suggestions(monkeypatch):
    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: [
        {
            "type": "habit",
            "summary": "阅读 30 分钟",
            "status": "skipped",
            "scheduled_at": "2026-04-20 21:00",
        },
        {
            "type": "habit",
            "summary": "阅读 30 分钟",
            "status": "done",
            "scheduled_at": "2026-04-21 21:00",
        },
    ])
    monkeypatch.setattr(
        "nudge.commands.review.get_habit_streaks",
        lambda: {"reading": {"streak": 1, "last_logged": "2026-04-21"}},
    )
    monkeypatch.setattr("nudge.commands.review.suggest_adaptation", lambda actions, habit_streaks, **kwargs: [
        {
            "type": "reduce_scope",
            "title": "降低阅读目标",
            "reason": "本周阅读完成率偏低",
            "suggestion": "把每天 30 分钟阅读改成 10 分钟",
            "confidence": 0.8,
        }
    ])

    result = CliRunner().invoke(review_command, ["weekly", "--adapt"])

    assert result.exit_code == 0
    assert "调整建议" in result.output
    assert "降低阅读目标" in result.output
    assert "把每天 30 分钟阅读改成 10 分钟" in result.output


def test_review_weekly_without_adapt_does_not_call_suggest_adaptation(monkeypatch):
    called = False

    def fake_suggest_adaptation(actions, habit_streaks, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: [
        {"type": "habit", "summary": "跑步", "status": "done", "scheduled_at": "2026-04-20 07:00"},
    ])
    monkeypatch.setattr("nudge.commands.review.get_habit_streaks", lambda: {})
    monkeypatch.setattr("nudge.commands.review.suggest_adaptation", fake_suggest_adaptation)

    result = CliRunner().invoke(review_command, ["weekly"])

    assert result.exit_code == 0
    assert "调整建议" not in result.output
    assert called is False


def test_review_weekly_counts_partial_as_half_done(monkeypatch):
    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: [
        {"type": "habit", "summary": "阅读", "status": "done", "scheduled_at": "2026-04-20 21:00"},
        {"type": "habit", "summary": "跑步", "status": "partial", "scheduled_at": "2026-04-21 07:00"},
        {"type": "habit", "summary": "写作", "status": "created", "scheduled_at": "2026-04-22 09:00"},
    ])
    monkeypatch.setattr("nudge.commands.review.get_habit_streaks", lambda: {})

    result = CliRunner().invoke(review_command, ["weekly"])

    assert result.exit_code == 0
    assert "50%" in result.output
    assert "(1.5/3)" in result.output
    assert "◐ 部分: 1" in result.output


def test_review_weekly_summarizes_feedback_needed_and_unfinished_reasons(monkeypatch):
    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: [
        {"type": "habit", "summary": "阅读", "status": "deferred", "scheduled_at": "2026-04-20 21:00", "feedback": '{"reason": "low_energy", "next_action": "reschedule", "note": "太累"}'},
        {"type": "habit", "summary": "跑步", "status": "blocked", "scheduled_at": "2026-04-21 07:00", "feedback": '{"reason": "waiting_on_other", "next_action": "keep"}'},
        {"type": "habit", "summary": "写作", "status": "created", "scheduled_at": "2026-04-22 09:00"},
    ])
    monkeypatch.setattr("nudge.commands.review.get_habit_streaks", lambda: {})

    result = CliRunner().invoke(review_command, ["weekly"])

    assert result.exit_code == 0, result.output
    assert "↷ 延期: 1" in result.output
    assert "⛔ 阻塞: 1" in result.output
    assert "待反馈" in result.output
    assert "写作" in result.output
    assert "未完成原因" in result.output
    assert "low_energy" in result.output
    assert "waiting_on_other" in result.output


def test_review_weekly_excludes_sleep_after_skip_from_failure_denominator(monkeypatch):
    captured = {}

    actions = [
        {"type": "reminder", "summary": "22:30 睡觉", "status": "done", "scheduled_at": "2026-04-20 22:30"},
        {"type": "reminder", "summary": "不要熬夜", "status": "skipped_after_sleep", "scheduled_at": "2026-04-20 23:00"},
        {"type": "reminder", "summary": "真的该睡了", "status": "skipped_after_sleep", "scheduled_at": "2026-04-20 23:30"},
    ]
    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: actions)
    monkeypatch.setattr("nudge.commands.review.get_habit_streaks", lambda: {})

    def fake_suggest_adaptation(filtered_actions, habit_streaks, **kwargs):
        captured["actions"] = filtered_actions
        return []

    monkeypatch.setattr("nudge.commands.review.suggest_adaptation", fake_suggest_adaptation)

    result = CliRunner().invoke(review_command, ["weekly", "--adapt"])

    assert result.exit_code == 0, result.output
    assert "100%" in result.output
    assert "(1/1)" in result.output
    assert "☾ 已睡后作废: 2" in result.output
    assert captured["actions"] == [actions[0]]


def test_review_weekly_adapt_dry_run_prints_plan_without_apply(monkeypatch):
    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: [
        {
            "id": "a1",
            "type": "calendar_event",
            "summary": "阅读 30 分钟",
            "status": "created",
            "scheduled_at": "2026-04-27 21:00",
            "external_id": "event-uid-1",
        },
    ])
    monkeypatch.setattr("nudge.commands.review.get_habit_streaks", lambda: {})
    monkeypatch.setattr("nudge.commands.review.suggest_adaptation", lambda actions, habit_streaks, **kwargs: [
        {
            "type": "move",
            "title": "把阅读提前",
            "reason": "晚上容易跳过",
            "action_id": "a1",
            "start": "2026-04-27 08:00",
            "end": "2026-04-27 08:30",
        }
    ])
    monkeypatch.setattr(
        "nudge.commands.review.apply_adaptation_plan",
        lambda plan: (_ for _ in ()).throw(AssertionError("apply should not run")),
    )

    result = CliRunner().invoke(review_command, ["weekly", "--adapt", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "调整预览" in result.output
    assert "把阅读提前" in result.output
    assert "2026-04-27 08:00" in result.output
    assert "未写入 Calendar" in result.output


def test_review_weekly_adapt_apply_requires_confirmation_and_runs_plan(monkeypatch):
    applied = []
    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: [
        {
            "id": "a1",
            "type": "calendar_event",
            "summary": "阅读 30 分钟",
            "status": "created",
            "scheduled_at": "2026-04-27 21:00",
            "external_id": "event-uid-1",
        },
    ])
    monkeypatch.setattr("nudge.commands.review.get_habit_streaks", lambda: {})
    monkeypatch.setattr("nudge.commands.review.suggest_adaptation", lambda actions, habit_streaks, **kwargs: [
        {"type": "delete", "title": "删除过量任务", "action_id": "a1"}
    ])
    monkeypatch.setattr(
        "nudge.commands.review.apply_adaptation_plan",
        lambda plan: applied.append(plan) or [{"ok": True, "action_id": "a1", "operation": "delete", "message": "deleted"}],
    )

    result = CliRunner().invoke(review_command, ["weekly", "--adapt", "--apply"], input="y\n")

    assert result.exit_code == 0, result.output
    assert applied
    assert "已应用" in result.output
    assert "delete" in result.output


def test_review_weekly_adapt_apply_renders_failed_calendar_result(monkeypatch):
    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: [
        {
            "id": "a1",
            "type": "calendar_event",
            "summary": "阅读 30 分钟",
            "status": "created",
            "scheduled_at": "2026-04-27 21:00",
            "external_id": "event-uid-1",
        },
    ])
    monkeypatch.setattr("nudge.commands.review.get_habit_streaks", lambda: {})
    monkeypatch.setattr("nudge.commands.review.suggest_adaptation", lambda actions, habit_streaks, **kwargs: [
        {"type": "delete", "title": "删除过量任务", "action_id": "a1"}
    ])
    monkeypatch.setattr(
        "nudge.commands.review.apply_adaptation_plan",
        lambda plan: [{"ok": False, "action_id": "a1", "operation": "delete", "message": "timed out"}],
    )

    result = CliRunner().invoke(review_command, ["weekly", "--adapt", "--apply"], input="y\n")

    assert result.exit_code == 0, result.output
    assert "APPLE_TIMEOUT" in result.output
    assert "nudge doctor" in result.output


def test_review_weekly_summarizes_feedback_sources(monkeypatch):
    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: [
        {"type": "habit", "summary": "阅读", "status": "skipped", "scheduled_at": "2026-04-20 21:00", "feedback": '{"source": "nudge log", "note": "太累"}'},
        {"type": "reminder", "summary": "称重", "status": "done", "scheduled_at": "2026-04-21 07:00", "feedback": '{"source": "nudge reminders sync-completed"}'},
        {"type": "calendar_event", "summary": "写作", "status": "partial", "scheduled_at": "2026-04-22 09:00", "feedback": '{"source_type": "agent", "channel": "mcp.report_action_status"}'},
    ])
    monkeypatch.setattr("nudge.commands.review.get_habit_streaks", lambda: {})

    result = CliRunner().invoke(review_command, ["weekly"])

    assert result.exit_code == 0, result.output
    assert "反馈来源" in result.output
    assert "subjective=1 objective=1 agent=1 unknown=0" in result.output


def test_review_weekly_includes_health_context(monkeypatch):
    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: [
        {"type": "habit", "summary": "跑步", "status": "done", "scheduled_at": "2026-07-01 07:00"},
    ])
    monkeypatch.setattr("nudge.commands.review.get_habit_streaks", lambda: {})
    monkeypatch.setattr(
        "nudge.commands.review.get_health_daily_summaries",
        lambda since=None, until=None: [
            {"date": "2026-07-04", "steps": 6000, "sleep_asleep_minutes": 360, "active_energy_kcal": 300},
            {"date": "2026-07-05", "steps": 9000, "sleep_asleep_minutes": 420, "active_energy_kcal": 500},
        ],
    )
    monkeypatch.setattr(
        "nudge.commands.review.get_health_workouts",
        lambda since=None, until=None: [
            {"duration_minutes": 30, "start_at": "2026-07-01 07:00"},
            {"duration_minutes": 45, "start_at": "2026-07-03 18:00"},
        ],
    )

    result = CliRunner().invoke(review_command, ["weekly"])

    assert result.exit_code == 0, result.output
    assert "健康数据" in result.output
    assert "睡眠均值 390min" in result.output
    assert "步数均值 7500" in result.output
    assert "运动 2 次/75min" in result.output


def test_review_weekly_includes_subjective_score_and_passes_to_adapt(monkeypatch):
    captured = {}
    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: [
        {"type": "habit", "summary": "跑步", "status": "done", "scheduled_at": "2026-07-01 07:00"},
    ])
    monkeypatch.setattr("nudge.commands.review.get_habit_streaks", lambda: {})
    monkeypatch.setattr("nudge.commands.review.get_health_daily_summaries", lambda since=None, until=None: [])
    monkeypatch.setattr("nudge.commands.review.get_health_workouts", lambda since=None, until=None: [])
    monkeypatch.setattr(
        "nudge.commands.review.get_latest_evaluation",
        lambda period, period_start=None, period_end=None: {
            "metrics": {"difficulty": 6, "recovery": 7, "sleep": 5, "mood": 8},
            "insights": "训练能完成，但晚上偏累",
        },
    )

    def fake_suggest_adaptation(actions, habit_streaks, **kwargs):
        captured["objective_context"] = kwargs.get("objective_context")
        return []

    monkeypatch.setattr("nudge.commands.review.suggest_adaptation", fake_suggest_adaptation)

    result = CliRunner().invoke(review_command, ["weekly", "--adapt"])

    assert result.exit_code == 0, result.output
    assert "主观打分" in result.output
    assert "difficulty=6" in result.output
    assert "训练能完成，但晚上偏累" in result.output
    assert "主观打分" in captured["objective_context"]
    assert "sleep=5" in captured["objective_context"]


def test_review_weekly_adapt_includes_profile_memory(monkeypatch):
    captured = {}
    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: [
        {"type": "habit", "summary": "跑步", "status": "done", "scheduled_at": "2026-07-01 07:00"},
    ])
    monkeypatch.setattr("nudge.commands.review.get_habit_streaks", lambda: {})
    monkeypatch.setattr("nudge.commands.review.get_health_daily_summaries", lambda since=None, until=None: [])
    monkeypatch.setattr("nudge.commands.review.get_health_workouts", lambda since=None, until=None: [])
    monkeypatch.setattr("nudge.commands.review.get_latest_evaluation", lambda period, period_start=None, period_end=None: None)
    monkeypatch.setattr(
        "nudge.commands.review.latest_profile_context",
        lambda: "长期画像:\n- 优先安排在 07 点附近。",
    )

    def fake_suggest_adaptation(actions, habit_streaks, **kwargs):
        captured["objective_context"] = kwargs.get("objective_context")
        return []

    monkeypatch.setattr("nudge.commands.review.suggest_adaptation", fake_suggest_adaptation)

    result = CliRunner().invoke(review_command, ["weekly", "--adapt"])

    assert result.exit_code == 0, result.output
    assert "长期画像" in captured["objective_context"]
    assert "优先安排在 07" in captured["objective_context"]


def _adapt_env(monkeypatch, *, subjective_evaluation, health_summaries):
    """Wire a minimal weekly --adapt run and capture save_evaluation calls."""
    saved = []
    monkeypatch.setattr("nudge.commands.review.get_actions", lambda since=None, until=None: [
        {"type": "habit", "summary": "跑步", "status": "done", "scheduled_at": "2026-07-01 07:00"},
    ])
    monkeypatch.setattr("nudge.commands.review.get_habit_streaks", lambda: {})
    monkeypatch.setattr(
        "nudge.commands.review.get_health_daily_summaries",
        lambda since=None, until=None: health_summaries,
    )
    monkeypatch.setattr("nudge.commands.review.get_health_workouts", lambda since=None, until=None: [])
    monkeypatch.setattr(
        "nudge.commands.review.get_latest_evaluation",
        lambda period, period_start=None, period_end=None: subjective_evaluation,
    )
    monkeypatch.setattr("nudge.commands.review.latest_profile_context", lambda: None)
    monkeypatch.setattr(
        "nudge.commands.review.suggest_adaptation",
        lambda actions, habit_streaks, **kwargs: [
            {"title": "保持节奏", "reason": "完成率高", "suggestion": "维持现状"},
        ],
    )

    def fake_save_evaluation(**kwargs):
        saved.append(kwargs)
        return len(saved)

    monkeypatch.setattr("nudge.commands.review.save_evaluation", fake_save_evaluation)
    return saved


def test_review_weekly_adapt_persists_degradation_when_subjective_missing(monkeypatch):
    # No weekly_subjective score and no health context -> conservative fallback,
    # and the reason must be persisted as a machine-readable weekly_adapt record.
    saved = _adapt_env(monkeypatch, subjective_evaluation=None, health_summaries=[])

    result = CliRunner().invoke(review_command, ["weekly", "--adapt"])

    assert result.exit_code == 0, result.output
    adapt_rows = [row for row in saved if row.get("period") == "weekly_adapt"]
    assert len(adapt_rows) == 1
    metrics = adapt_rows[0]["metrics"]
    assert metrics["subjective_missing"] is True
    assert metrics["objective_missing"] is True
    assert metrics["mode"] == "conservative"
    assert adapt_rows[0]["insights"]  # human-readable reason present
    assert adapt_rows[0]["adaptations"]  # suggestions snapshot persisted


def test_review_weekly_adapt_records_normal_mode_when_subjective_present(monkeypatch):
    saved = _adapt_env(
        monkeypatch,
        subjective_evaluation={
            "metrics": {"difficulty": 6, "recovery": 7, "sleep": 5, "mood": 8},
            "insights": "还行",
        },
        health_summaries=[{"date": "2026-07-01", "steps": 7500}],
    )

    result = CliRunner().invoke(review_command, ["weekly", "--adapt"])

    assert result.exit_code == 0, result.output
    adapt_rows = [row for row in saved if row.get("period") == "weekly_adapt"]
    assert len(adapt_rows) == 1
    metrics = adapt_rows[0]["metrics"]
    assert metrics["subjective_missing"] is False
    assert metrics["objective_missing"] is False
    assert metrics["mode"] == "normal"
