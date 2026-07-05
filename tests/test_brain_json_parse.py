"""Tests for robust LLM JSON response parsing."""

import json

import pytest

from nudge.brain import _parse_json, parse_json_response


def test_parse_json_response_accepts_plain_object():
    assert parse_json_response('{"ok": true, "value": 42}') == {"ok": True, "value": 42}


def test_parse_json_response_accepts_plain_list():
    assert parse_json_response('[{"type": "reminder"}]') == [{"type": "reminder"}]


def test_parse_json_response_extracts_fenced_json_surrounded_by_text():
    raw = "Here is the parsed result:\n```json\n{\"status\": \"done\"}\n```\nHope this helps."

    assert parse_json_response(raw) == {"status": "done"}


def test_parse_json_response_accepts_leading_whitespace_before_fence():
    raw = "  \n\t```json\n{\"assignees\": [\"all\"], \"confidence\": 0.9}\n```"

    assert parse_json_response(raw) == {"assignees": ["all"], "confidence": 0.9}


def test_parse_json_response_extracts_first_complete_json_from_body():
    raw = "模型说明：先给出结论 {\"next_action\": \"split\"} 后面还有文字 {\"ignored\": true}"

    assert parse_json_response(raw) == {"next_action": "split"}


def test_parse_json_response_accepts_markdown_fenced_json_list():
    raw = "Result follows:\n```json\n[{\"type\": \"reminder\"}, {\"type\": \"alarm\"}]\n```"

    assert _parse_json(raw) == [{"type": "reminder"}, {"type": "alarm"}]


def test_parse_json_response_raises_when_no_json_is_parseable():
    with pytest.raises(json.JSONDecodeError):
        parse_json_response("没有任何可解析 JSON 的普通文本")
