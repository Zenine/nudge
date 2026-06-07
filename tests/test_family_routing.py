"""Tests for family recipient routing helper boundaries."""

from __future__ import annotations

from nudge.family_routing import resolve_family_recipients


FAMILY_MEMBERS = [
    {"key": "ming", "name": "小明"},
    {"key": "hong", "name": "小红"},
]


def test_all_assignee_expands_to_every_family_member():
    result = resolve_family_recipients(
        {"type": "reminder", "name": "全家检查护照", "person": "全家"},
        FAMILY_MEMBERS,
        {"default": "all"},
    )

    assert [member["key"] for member in result.members] == ["ming", "hong"]
    assert result.metadata["source"] == "default"
    assert result.metadata["assignees"] == ["all"]


def test_unknown_member_blocks_keyword_route_with_actionable_metadata():
    result = resolve_family_recipients(
        {"type": "reminder", "name": "报名课程", "person": "全家"},
        FAMILY_MEMBERS,
        {
            "default": "all",
            "rules": [
                {"id": "course", "keywords": ["课程"], "assignees": ["unknown"]},
            ],
        },
    )

    assert result.members == []
    assert result.metadata["source"] == "keyword_invalid"
    assert result.metadata["rule_id"] == "course"
    assert result.metadata["invalid_assignees"] == ["unknown"]
    assert result.metadata["assignees"] == []


def test_low_confidence_llm_suggestion_falls_back_to_default_route():
    result = resolve_family_recipients(
        {"type": "reminder", "name": "准备周末安排", "person": "全家"},
        FAMILY_MEMBERS,
        {
            "default": ["hong"],
            "llm_fallback": True,
            "llm_confidence_threshold": 0.8,
        },
        llm_router=lambda _action, _members, _routing: {
            "assignees": ["ming"],
            "confidence": 0.4,
            "reason": "不够确定",
        },
    )

    assert [member["key"] for member in result.members] == ["hong"]
    assert result.metadata["source"] == "default"
    assert result.metadata["assignees"] == ["hong"]
    assert result.metadata["llm_error"] == "low_confidence"
    assert result.metadata["llm_confidence"] == 0.4
