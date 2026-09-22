"""Tests for the structured feedback interview domain model."""

from datetime import datetime

import pytest

from nudge.feedback_interview import (
    build_gpt_followup_questions,
    classify_feedback_risk,
    normalize_interview_response,
    plan_sleep_derived_effects,
    sanitize_terminal_text,
    select_feedback_candidates,
    validate_gpt_questions,
)


NOW = datetime(2026, 7, 19, 12, 0)


def _action(action_id, scheduled_at, *, status="created", summary="普通任务", action_type="reminder"):
    return {
        "id": action_id,
        "type": action_type,
        "summary": summary,
        "scheduled_at": scheduled_at,
        "completed_at": None,
        "status": status,
        "feedback": None,
    }


def test_select_week_overdue_uses_local_week_cutoff_and_pending_statuses():
    actions = [
        _action("current-week", "2026-07-13 08:00"),
        _action("too-recent", "2026-07-18 13:00"),
        _action("previous-week", "2026-07-12 08:00"),
        _action("already-done", "2026-07-14 08:00", status="done"),
        _action("unscheduled", None),
    ]

    batch = select_feedback_candidates(actions, scope="week-overdue", now=NOW)

    assert [item["id"] for item in batch.items] == ["current-week"]
    assert batch.total == 1
    assert batch.remaining == 0


def test_select_today_includes_pending_actions_for_whole_local_day():
    actions = [
        _action("morning", "2026-07-19 08:00", status="pending"),
        _action("future-today", "2026-07-19 20:00"),
        _action("tomorrow", "2026-07-20 08:00"),
    ]

    batch = select_feedback_candidates(actions, scope="today", now=NOW)

    assert [item["id"] for item in batch.items] == ["morning", "future-today"]


def test_select_all_overdue_is_stable_and_reports_limit_counts():
    actions = [
        _action("b", "2026-07-13 08:00"),
        _action("a", "2026-07-13 08:00"),
        _action("oldest", "2026-07-12 08:00"),
    ]

    batch = select_feedback_candidates(actions, scope="all-overdue", now=NOW, limit=2)

    assert [item["id"] for item in batch.items] == ["oldest", "a"]
    assert batch.total == 3
    assert batch.remaining == 1


@pytest.mark.parametrize("limit", [0, 51])
def test_select_candidates_rejects_limit_outside_one_to_fifty(limit):
    with pytest.raises(ValueError, match="limit"):
        select_feedback_candidates([], scope="week-overdue", now=NOW, limit=limit)


def test_risk_classifier_is_deterministic_and_conservative_for_invalid_fields():
    assert classify_feedback_risk(_action("medical", "2026-07-13 08:00", summary="复诊确认用药剂量")) == "high"
    assert classify_feedback_risk(_action("travel", "2026-07-13 08:00", summary="确认明天航班")) == "high"
    assert classify_feedback_risk(_action("ordinary", "2026-07-13 08:00", summary="整理书桌")) == "normal"
    assert classify_feedback_risk(_action("unknown", "2026-07-13 08:00", summary="新的业务主题")) == "normal"
    assert classify_feedback_risk({"id": "invalid", "type": "reminder", "summary": None}) == "high"


@pytest.mark.parametrize(
    ("summary", "extra"),
    [
        ("周六围棋课", {"reminder_list": "家庭"}),
        ("交物业费", {}),
        ("去机场", {}),
    ],
)
def test_risk_classifier_covers_family_payment_and_travel_context(summary, extra):
    action = _action("high-risk", "2026-07-13 08:00", summary=summary)
    action.update(extra)

    assert classify_feedback_risk(action) == "high"


def test_validate_gpt_questions_normalizes_supported_schema():
    payload = {
        "questions": [
            {
                "id": "main_blocker",
                "type": "multi_choice",
                "prompt": "主要阻力有哪些？",
                "options": ["时间不足", "精力不足"],
                "required": False,
                "max_selections": 2,
            },
            {
                "id": "worth_continuing",
                "type": "boolean",
                "prompt": "还值得继续吗？",
                "required": False,
            },
        ]
    }

    questions = validate_gpt_questions(payload)

    assert questions[0]["source"] == "gpt"
    assert questions[0]["max_selections"] == 2
    assert questions[1]["type"] == "boolean"


@pytest.mark.parametrize(
    "payload",
    [
        {"questions": [{"id": str(index), "type": "boolean", "prompt": "问题", "required": False} for index in range(4)]},
        {"questions": [{"id": "bad", "type": "rating", "prompt": "问题", "required": False}]},
        {"questions": [{"id": "bad", "type": "single_choice", "prompt": "问题", "options": ["仅一个"], "required": False}]},
        {"questions": [{"id": "bad", "type": "boolean", "prompt": "问题", "required": True}]},
    ],
)
def test_validate_gpt_questions_rejects_invalid_schema(payload):
    with pytest.raises(ValueError):
        validate_gpt_questions(payload)


def test_normalize_response_preserves_structured_answer_and_user_text():
    question = validate_gpt_questions({
        "questions": [{
            "id": "main_blocker",
            "type": "multi_choice",
            "prompt": "主要阻力有哪些？",
            "options": ["时间不足", "精力不足"],
            "required": False,
            "max_selections": 2,
        }]
    })[0]

    response = normalize_interview_response(
        question,
        ["时间不足", "精力不足"],
        user_text="下班后已经没精力了",
    )

    assert response == {
        "id": "main_blocker",
        "type": "multi_choice",
        "source": "gpt",
        "prompt": "主要阻力有哪些？",
        "answer": ["时间不足", "精力不足"],
        "skipped": False,
        "user_text": "下班后已经没精力了",
    }


def test_normalize_response_records_optional_skip_explicitly():
    question = validate_gpt_questions({
        "questions": [{"id": "detail", "type": "short_text", "prompt": "补充说明？", "required": False}]
    })[0]

    response = normalize_interview_response(question, None, skipped=True)

    assert response["answer"] is None
    assert response["skipped"] is True


def test_sanitize_terminal_text_removes_ansi_and_control_characters():
    raw = "正常\x1b[31m红色\x1b[0m\x00内容\n下一行\t缩进"

    assert sanitize_terminal_text(raw) == "正常红色内容\n下一行\t缩进"


def test_build_gpt_followups_calls_fast_model_once_with_ten_second_timeout():
    calls = []

    def fake_llm(system, user_message, **kwargs):
        calls.append((system, user_message, kwargs))
        return '{"questions":[{"id":"blocker","type":"boolean","prompt":"遇到阻力了吗？","required":false}]}'

    result = build_gpt_followup_questions(
        _action("ordinary", "2026-07-13 08:00", summary="整理书桌"),
        {"resolution": "partial", "reason": "no_time", "next_action": "split"},
        llm_call=fake_llm,
    )

    assert len(calls) == 1
    assert calls[0][2] == {"task": "fast", "timeout": 10.0, "retries": 0}
    assert result.mode == "core_plus_gpt"
    assert result.warning_code is None
    assert result.questions[0]["id"] == "blocker"


@pytest.mark.parametrize(
    "llm_result",
    [
        RuntimeError("provider down"),
        "not json",
        '{"questions":[{"id":"bad","type":"rating","prompt":"评分？","required":false}]}',
    ],
)
def test_build_gpt_followups_degrades_without_retry_or_raw_output(llm_result):
    calls = []

    def fake_llm(*args, **kwargs):
        calls.append((args, kwargs))
        if isinstance(llm_result, Exception):
            raise llm_result
        return llm_result

    result = build_gpt_followup_questions(
        _action("ordinary", "2026-07-13 08:00"),
        {"resolution": "deferred", "reason": "no_time", "next_action": "reschedule"},
        llm_call=fake_llm,
    )

    assert len(calls) == 1
    assert result.mode == "core_only"
    assert result.questions == []
    assert result.warning_code == "FEEDBACK_INTERVIEW_LLM_DEGRADED"
    assert result.diagnostic in {"RuntimeError", "invalid_json", "invalid_schema"}
    assert str(llm_result) not in result.diagnostic


def test_sleep_derived_effects_are_planned_before_write_and_exclude_explicit_updates():
    bedtime = _action("bedtime", "2026-07-19 22:30", summary="关机睡觉")
    later = _action("later", "2026-07-19 23:00", summary="不要熬夜")
    explicit = _action("explicit", "2026-07-19 23:30", summary="该睡觉了")

    effects = plan_sleep_derived_effects(
        [bedtime, later, explicit],
        [
            {"id": "bedtime", "resolution": "done", "completed_at": "2026-07-19 22:31"},
            {"id": "explicit", "resolution": "deferred"},
        ],
    )

    assert [effect["id"] for effect in effects] == ["later"]
    assert effects[0]["status"] == "skipped_after_sleep"
    assert effects[0]["feedback"]["channel"] == "sleep.auto_skip"
    assert effects[0]["feedback"]["completed_sleep_action_id"] == "bedtime"
