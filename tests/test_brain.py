"""Tests for nudge.brain module (non-LLM parts)."""

import json

import pytest

from nudge.brain import LLMError, _call, _parse_json, call_llm


class TestParseJson:
    def test_plain_json_array(self):
        result = _parse_json('[{"type": "alarm", "time": "07:00", "label": "wake up"}]')
        assert isinstance(result, list)
        assert result[0]["type"] == "alarm"

    def test_json_with_markdown_fences(self):
        raw = '```json\n[{"type": "alarm"}]\n```'
        result = _parse_json(raw)
        assert isinstance(result, list)

    def test_json_with_fences_no_closing(self):
        raw = '```json\n[{"type": "alarm"}]'
        result = _parse_json(raw)
        assert isinstance(result, list)

    def test_json_object_with_surrounding_text(self):
        raw = '解析结果如下：\n{"type": "reminder", "name": "test"}\n请确认。'
        result = _parse_json(raw)
        assert result == {"type": "reminder", "name": "test"}

    def test_json_array_with_fenced_block_and_extra_text(self):
        raw = '可以，JSON 如下：\n```json\n[{"type": "alarm"}]\n```\n以上。'
        result = _parse_json(raw)
        assert result == [{"type": "alarm"}]

    def test_extracts_first_valid_json_when_earlier_bracket_is_text(self):
        raw = '候选 [不是 JSON]：\n{"type": "reminder", "name": "test"}\n后续说明'
        result = _parse_json(raw)
        assert result["type"] == "reminder"

    def test_single_object(self):
        result = _parse_json('{"type": "reminder", "name": "test"}')
        assert isinstance(result, dict)
        assert result["type"] == "reminder"

    def test_invalid_json_raises(self):
        with pytest.raises(LLMError, match="JSON 解析失败"):
            _parse_json("this is not json")

    def test_invalid_json_error_uses_safe_diagnostic_excerpt(self):
        with pytest.raises(LLMError) as exc_info:
            _parse_json("prefix DASHSCOPE_API_KEY=abc123 password: hunter2 not json")

        message = str(exc_info.value)
        assert "prefix" in message
        assert "DASHSCOPE_API_KEY=<redacted>" in message
        assert "password=<redacted>" in message
        assert "abc123" not in message
        assert "hunter2" not in message

    def test_empty_array(self):
        result = _parse_json("[]")
        assert result == []


class TestCallRetry:
    def test_public_call_forwards_timeout_and_zero_retries(self, monkeypatch):
        import nudge.brain as brain

        calls = []

        class FakeProvider:
            def call(self, system, user_message, model, timeout=None, max_retries=None):
                calls.append((system, user_message, model, timeout, max_retries))
                return "ok"

        monkeypatch.setattr(brain, "_get_provider", lambda: FakeProvider())
        monkeypatch.setattr(brain, "get_model_for_task", lambda task, config: "fast-model")

        assert call_llm("system", "message", task="fast", timeout=10.0, retries=0) == "ok"
        assert calls == [("system", "message", "fast-model", 10.0, 0)]

    def test_retry_backoff_adds_jitter_for_llm_error(self, monkeypatch):
        import nudge.brain as brain

        calls = []
        sleeps = []

        class FakeProvider:
            def call(self, system, user_message, model):
                calls.append((system, user_message, model))
                if len(calls) == 1:
                    raise LLMError("rate limited")
                return "ok"

        monkeypatch.setattr(brain, "_get_provider", lambda: FakeProvider())
        monkeypatch.setattr(brain, "get_model_for_task", lambda task, config: "test-model")
        monkeypatch.setattr(brain.random, "uniform", lambda low, high: 0.25)
        monkeypatch.setattr(brain.time, "sleep", lambda seconds: sleeps.append(seconds))

        assert _call("system", "message", retries=1) == "ok"

        assert len(calls) == 2
        assert sleeps == [1.25]

    def test_does_not_retry_non_llm_error(self, monkeypatch):
        import nudge.brain as brain

        calls = []
        sleeps = []

        class FakeProvider:
            def call(self, system, user_message, model):
                calls.append((system, user_message, model))
                raise ValueError("not retryable")

        monkeypatch.setattr(brain, "_get_provider", lambda: FakeProvider())
        monkeypatch.setattr(brain, "get_model_for_task", lambda task, config: "test-model")
        monkeypatch.setattr(brain.random, "uniform", lambda low, high: 0.25)
        monkeypatch.setattr(brain.time, "sleep", lambda seconds: sleeps.append(seconds))

        with pytest.raises(ValueError, match="not retryable"):
            _call("system", "message", retries=1)

        assert len(calls) == 1
        assert sleeps == []


class TestSuggestFamilyRouting:
    def test_parses_json_object_and_normalizes_list_assignees(self, monkeypatch):
        import nudge.brain as brain

        captured = {}

        def fake_call(system, user_message, task="default"):
            captured["system"] = system
            captured["user_message"] = user_message
            captured["task"] = task
            return json.dumps({
                "assignees": ["mom"],
                "confidence": "0.9",
                "reason": "妈妈更适合处理",
            }, ensure_ascii=False)

        monkeypatch.setattr(brain, "_call", fake_call)

        result = brain.suggest_family_routing(
            {"type": "reminder", "name": "买实验课材料", "person": "家庭组"},
            [{"key": "mom", "name": "妈妈"}, {"key": "dad", "name": "爸爸"}],
            {"default": "all", "rules": []},
        )

        assert result == {
            "assignees": ["mom"],
            "confidence": 0.9,
            "reason": "妈妈更适合处理",
        }
        assert captured["task"] == "fast"
        assert "assignees" in captured["system"]
        assert "买实验课材料" in captured["user_message"]
        assert "妈妈" in captured["user_message"]

    def test_accepts_string_assignee(self, monkeypatch):
        import nudge.brain as brain

        monkeypatch.setattr(
            brain,
            "_call",
            lambda *args, **kwargs: json.dumps({
                "assignees": "mom",
                "confidence": 0.8,
                "reason": "妈妈处理",
            }, ensure_ascii=False),
        )

        result = brain.suggest_family_routing(
            {"type": "reminder", "name": "报名", "person": "家庭组"},
            [{"key": "mom", "name": "妈妈"}],
            {"default": "all"},
        )

        assert result["assignees"] == ["mom"]
        assert result["confidence"] == 0.8

    def test_non_dict_response_raises_llm_error(self, monkeypatch):
        import nudge.brain as brain

        monkeypatch.setattr(brain, "_call", lambda *args, **kwargs: '["mom"]')

        with pytest.raises(LLMError, match="家庭路由 JSON 必须是对象"):
            brain.suggest_family_routing(
                {"type": "reminder", "name": "报名", "person": "家庭组"},
                [{"key": "mom", "name": "妈妈"}],
                {"default": "all"},
            )

    def test_invalid_confidence_becomes_zero(self, monkeypatch):
        import nudge.brain as brain

        monkeypatch.setattr(
            brain,
            "_call",
            lambda *args, **kwargs: json.dumps({
                "assignees": ["mom"],
                "confidence": "not-a-number",
                "reason": None,
            }, ensure_ascii=False),
        )

        result = brain.suggest_family_routing(
            {"type": "reminder", "name": "报名", "person": "家庭组"},
            [{"key": "mom", "name": "妈妈"}],
            {"default": "all"},
        )

        assert result == {"assignees": ["mom"], "confidence": 0.0, "reason": ""}

    def test_boolean_confidence_becomes_zero(self, monkeypatch):
        import nudge.brain as brain

        monkeypatch.setattr(
            brain,
            "_call",
            lambda *args, **kwargs: json.dumps({
                "assignees": ["mom"],
                "confidence": True,
                "reason": "妈妈处理",
            }, ensure_ascii=False),
        )

        result = brain.suggest_family_routing(
            {"type": "reminder", "name": "报名", "person": "家庭组"},
            [{"key": "mom", "name": "妈妈"}],
            {"default": "all"},
        )

        assert result["confidence"] == 0.0
        assert result["confidence"] != 1.0

    def test_prompt_payload_uses_explicit_minimal_whitelist(self, monkeypatch):
        import nudge.brain as brain

        captured = {}

        def fake_call(system, user_message, task="default"):
            captured["user_message"] = user_message
            return json.dumps({
                "assignees": ["mom"],
                "confidence": 0.9,
                "reason": "妈妈处理",
            }, ensure_ascii=False)

        monkeypatch.setattr(brain, "_call", fake_call)

        long_body = "需要准备材料。" * 40
        brain.suggest_family_routing(
            {
                "type": "reminder",
                "name": "科学实验课带材料",
                "due_date": "2026-05-10 20:00",
                "body": long_body,
                "person": "家庭组",
                "priority": 9,
                "_family_routing": {"source": "keyword"},
                "_external_id": "reminder-secret-id",
            },
            [
                {
                    "key": "mom",
                    "name": "妈妈",
                    "display_name": "李梅",
                    "role": "mom",
                    "aliases": ["妈妈", "妈"],
                    "calendar": "个人",
                    "reminder_list": "家庭",
                }
            ],
            {
                "default": "all",
                "llm_fallback": True,
                "llm_confidence_threshold": 0.7,
                "rules": [
                    {
                        "id": "kids_courses",
                        "description": "internal details",
                        "keywords": ["科学实验"],
                        "assignees": ["mom"],
                    }
                ],
                "private_notes": "do not send",
            },
        )

        payload = json.loads(captured["user_message"])
        assert payload["action"] == {
            "type": "reminder",
            "name": "科学实验课带材料",
            "due_date": "2026-05-10 20:00",
            "body": long_body[:200],
        }
        assert payload["members"] == [
            {"key": "mom", "display_name": "李梅", "name": "妈妈", "role": "mom"}
        ]
        assert payload["routing"] == {
            "default": "all",
            "llm_confidence_threshold": 0.7,
            "rules": [{"id": "kids_courses", "keywords": ["科学实验"], "assignees": ["mom"]}],
        }
        serialized = captured["user_message"]
        for forbidden in (
            "calendar",
            "reminder_list",
            "aliases",
            "_family_routing",
            "_external_id",
            "priority",
            "private_notes",
            "internal details",
        ):
            assert forbidden not in serialized


class TestSuggestAdaptation:
    def test_no_actions_returns_empty_list_without_llm_call(self, monkeypatch):
        import nudge.brain as brain

        called = False

        def fake_call(*args, **kwargs):
            nonlocal called
            called = True
            return "[]"

        monkeypatch.setattr(brain, "_call", fake_call)

        assert brain.suggest_adaptation(actions=[], habit_streaks={}) == []
        assert called is False

    def test_returns_adaptation_suggestions_from_json_array(self, monkeypatch):
        import nudge.brain as brain

        captured = {}

        def fake_call(system, user_message, task="default"):
            captured["system"] = system
            captured["user_message"] = user_message
            captured["task"] = task
            return json.dumps([
                {
                    "type": "reduce_scope",
                    "title": "降低阅读目标",
                    "reason": "本周阅读完成率偏低",
                    "suggestion": "把每天 30 分钟阅读改成 10 分钟",
                    "confidence": 0.8,
                }
            ], ensure_ascii=False)

        monkeypatch.setattr(brain, "_call", fake_call)

        suggestions = brain.suggest_adaptation(
            actions=[
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
            ],
            habit_streaks={"reading": {"streak": 1, "last_logged": "2026-04-21"}},
        )

        assert suggestions == [
            {
                "type": "reduce_scope",
                "title": "降低阅读目标",
                "reason": "本周阅读完成率偏低",
                "suggestion": "把每天 30 分钟阅读改成 10 分钟",
                "confidence": 0.8,
            }
        ]
        assert captured["task"] == "strong"
        assert "完成率: 50%" in captured["system"]
        assert "阅读 30 分钟" in captured["system"]
        assert captured["user_message"] == "请根据本周执行数据给出调整建议"

    def test_suggest_adaptation_includes_objective_context(self, monkeypatch):
        import nudge.brain as brain

        captured = {}

        def fake_call(system, user_message, task="default"):
            captured["system"] = system
            return "[]"

        monkeypatch.setattr(brain, "_call", fake_call)

        brain.suggest_adaptation(
            actions=[{"summary": "跑步", "status": "done"}],
            habit_streaks={},
            objective_context="健康数据（近 7 天）:\n- 睡眠均值 390min；步数均值 7500",
        )

        assert "Objective / subjective context" in captured["system"]
        assert "睡眠均值 390min" in captured["system"]
        assert "subjective feedback is missing" in captured["system"]

    def test_wraps_single_json_object_as_list(self, monkeypatch):
        import nudge.brain as brain

        monkeypatch.setattr(
            brain,
            "_call",
            lambda *args, **kwargs: json.dumps({
                "type": "keep_going",
                "title": "保持节奏",
                "reason": "完成率稳定",
                "suggestion": "下周继续当前安排",
                "confidence": 0.7,
            }, ensure_ascii=False),
        )

        suggestions = brain.suggest_adaptation(
            actions=[{"summary": "跑步", "status": "done"}],
            habit_streaks={},
        )

        assert isinstance(suggestions, list)
        assert suggestions[0]["type"] == "keep_going"

    def test_invalid_json_raises_clear_error(self, monkeypatch):
        import nudge.brain as brain

        monkeypatch.setattr(brain, "_call", lambda *args, **kwargs: "not json")

        with pytest.raises(LLMError, match="调整建议 JSON 解析失败"):
            brain.suggest_adaptation(
                actions=[{"summary": "跑步", "status": "done"}],
                habit_streaks={},
            )


class TestParseCheckInFeedback:
    def test_returns_check_in_parse_object(self, monkeypatch):
        import nudge.brain as brain

        captured = {}

        def fake_call(system, user_message, task="default"):
            captured["system"] = system
            captured["user_message"] = user_message
            captured["task"] = task
            return json.dumps({
                "status": "done",
                "note": "跑了 2 公里",
                "metrics": {"distance_km": 2, "effort": 7},
                "match": "跑步",
            }, ensure_ascii=False)

        monkeypatch.setattr(brain, "_call", fake_call)

        parsed = brain.parse_check_in_feedback("跑步完成了，2 公里，体感 7 分")

        assert parsed == {
            "status": "done",
            "note": "跑了 2 公里",
            "metrics": {"distance_km": 2, "effort": 7},
            "match": "跑步",
        }
        assert captured["task"] == "fast"
        assert "done / skipped / partial / deferred / blocked" in captured["system"]
        assert "reason" in captured["system"]
        assert "next_action" in captured["system"]

    def test_invalid_json_raises_clear_error(self, monkeypatch):
        import nudge.brain as brain

        monkeypatch.setattr(brain, "_call", lambda *args, **kwargs: "not json")

        with pytest.raises(LLMError, match="Check-in JSON 解析失败"):
            brain.parse_check_in_feedback("读完了")
