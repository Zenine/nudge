"""Tests for user-facing error reports."""


from nudge.errors import (
    ErrorReport,
    agent_batch_too_large_report,
    agent_confirmation_invalid_report,
    agent_confirmation_required_report,
    agent_text_plan_confirmation_required_report,
    classify_apple_error,
    format_llm_error,
    format_llm_schema_error,
)


def test_error_report_render_is_pure_formatting(monkeypatch):
    monkeypatch.setattr(
        "nudge.errors.log_error_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("render must not write runtime logs")),
        raising=False,
    )
    error = ErrorReport(
        code="TEST_ERROR",
        title="测试错误",
        detail="用于固定 render 契约",
        next_steps=("第一步", "第二步"),
        raw_error="raw detail",
    )

    rendered = error.render(indent="  ")

    assert "  ERROR [TEST_ERROR]: 测试错误" in rendered
    assert "  1. 第一步" in rendered
    assert "  原始错误：raw detail" in rendered


def test_classify_calendar_missing_target_error_is_actionable():
    report = classify_apple_error(
        service="Calendar",
        target_kind="Calendar",
        target_name="Family",
        raw_error='Can’t get calendar "Family".',
    )

    text = report.render()

    assert report.code == "APPLE_TARGET_NOT_FOUND"
    assert "目标 Calendar 不存在：Family" in text
    assert "运行 `nudge doctor`" in text
    assert "config.toml" in text
    assert "原始错误" in text


def test_classify_reminders_permission_error_mentions_system_settings():
    report = classify_apple_error(
        service="Reminders",
        target_kind="Reminder list",
        target_name="日常",
        raw_error="Not authorized to send Apple events to Reminders. (-1743)",
    )

    text = report.render()

    assert report.code == "APPLE_PERMISSION_DENIED"
    assert "Reminders 权限不足" in text
    assert "系统设置" in text
    assert "隐私与安全性" in text
    assert "提醒事项" in text


def test_classify_notes_permission_error_mentions_automation():
    report = classify_apple_error(
        service="Notes",
        target_kind="Notes folder",
        target_name="Nudge",
        raw_error="Not authorized to send Apple events to Notes. (-1743)",
    )

    text = report.render()

    assert report.code == "APPLE_PERMISSION_DENIED"
    assert "Notes 权限不足" in text
    assert "自动化" in text
    assert "Notes" in text


def test_classify_timeout_error_warns_not_to_retry_blindly():
    report = classify_apple_error(
        service="Calendar",
        target_kind="Calendar",
        target_name="Family",
        raw_error="AppleScript execution timed out",
    )

    text = report.render()

    assert report.code == "APPLE_TIMEOUT"
    assert "Calendar 操作超时" in text
    assert "不要直接反复重试" in text


def test_format_llm_invalid_json_error_points_to_prompt_contract():
    text = format_llm_error("LLM returned invalid JSON after retry: nope")

    assert "LLM 返回了无效 JSON" in text
    assert "docs/PROMPT_PLAYBOOK.md" in text
    assert "nudge --dry-run" in text


def test_format_llm_schema_error_describes_missing_fields():
    text = format_llm_schema_error("action 1 calendar_event missing fields: end")

    assert "LLM JSON 结构不符合 action schema" in text
    assert "action 1 calendar_event missing fields: end" in text
    assert "Prompt Playbook" in text


def test_agent_confirmation_errors_are_actionable():
    required = agent_confirmation_required_report()
    invalid = agent_confirmation_invalid_report()

    assert required.code == "AGENT_CONFIRMATION_REQUIRED"
    assert "dry_run_token" in required.render()
    assert "dry-run" in required.render()
    assert invalid.code == "AGENT_CONFIRMATION_INVALID"
    assert "重新执行 dry-run" in invalid.render()


def test_agent_text_plan_confirmation_required_error_is_actionable():
    report = agent_text_plan_confirmation_required_report()

    text = report.render()

    assert report.code == "AGENT_TEXT_PLAN_CONFIRMATION_REQUIRED"
    assert "文本计划" in text
    assert "text_plan_confirmed=true" in text
    assert "text_plan_ref" in text
    assert "dry-run" in text


def test_agent_batch_too_large_report_is_actionable():
    report = agent_batch_too_large_report(limit=10, received=11)

    assert report.code == "AGENT_BATCH_TOO_LARGE"
    assert "11" in report.detail
    assert "10" in report.detail
    assert report.next_steps
    assert "拆成" in report.render()
