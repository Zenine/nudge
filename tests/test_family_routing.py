import pytest

from nudge.family_routing import resolve_family_recipients
from nudge.config import get_family_routing


MEMBERS = [
    {"key": "dad", "name": "爸爸", "display_name": "爸爸", "role": "dad", "reminder_list": "家庭"},
    {"key": "mom", "name": "李梅", "display_name": "李梅", "role": "mom", "reminder_list": "家庭"},
    {"key": "kid", "name": "孩子", "display_name": "孩子", "role": "kid", "reminder_list": "家庭"},
]


ROUTING = {
    "default": "all",
    "llm_fallback": False,
    "rules": [
        {
            "id": "kids_courses",
            "description": "孩子课程",
            "keywords": ["课程", "科学实验", "跆拳道"],
            "assignees": ["mom"],
            "notification_policy": "prestart_only",
        },
        {
            "id": "payments",
            "description": "付款缴费",
            "keywords": ["缴费", "付款"],
            "assignees": ["dad", "mom"],
        },
        {
            "id": "family_all",
            "description": "全家事项",
            "keywords": ["家庭会议", "一起"],
            "assignees": ["all"],
        },
    ],
}


def test_keyword_route_kids_course_to_mom():
    result = resolve_family_recipients(
        {"type": "reminder", "name": "科学实验上课", "person": "家庭组"},
        MEMBERS,
        ROUTING,
    )

    assert [member["key"] for member in result.members] == ["mom"]
    assert result.metadata == {
        "source": "keyword",
        "rule_id": "kids_courses",
        "original_person": "家庭组",
        "assignees": ["mom"],
        "notification_policy": "prestart_only",
        "reason": "命中关键词：科学实验",
    }


def test_family_routing_rejects_unknown_notification_policy():
    config = {
        "family": {
            "routing": {
                "rules": [{
                    "id": "kids_courses",
                    "keywords": ["课程"],
                    "assignees": ["mom"],
                    "notification_policy": "prestart-only",
                }],
            },
        },
    }

    with pytest.raises(
        ValueError,
        match="kids_courses.*notification_policy.*prestart-only",
    ):
        get_family_routing(config)


def test_keyword_route_payment_to_dad_and_mom():
    result = resolve_family_recipients(
        {"type": "reminder", "name": "家庭组缴费", "person": "家庭组"},
        MEMBERS,
        ROUTING,
    )

    assert [member["key"] for member in result.members] == ["dad", "mom"]
    assert result.metadata["rule_id"] == "payments"


def test_keyword_route_family_meeting_to_all_members():
    result = resolve_family_recipients(
        {"type": "reminder", "name": "家庭会议", "person": "家庭组"},
        MEMBERS,
        ROUTING,
    )

    assert [member["key"] for member in result.members] == ["dad", "mom", "kid"]
    assert result.metadata["assignees"] == ["all"]


def test_keyword_route_rejects_mixed_all_and_invalid_assignees():
    routing = {
        **ROUTING,
        "rules": [
            {
                "id": "mixed_all_invalid",
                "keywords": ["家庭会议"],
                "assignees": ["all", "unknown"],
            }
        ],
    }

    result = resolve_family_recipients(
        {"type": "reminder", "name": "家庭会议", "person": "家庭组"},
        MEMBERS,
        routing,
    )

    assert result.members == []
    assert result.metadata["source"] == "keyword_invalid"
    assert result.metadata["rule_id"] == "mixed_all_invalid"
    assert result.metadata["assignees"] == ["all"]
    assert result.metadata["invalid_assignees"] == ["unknown"]
    assert "invalid assignees" in result.metadata["reason"]


def test_keyword_route_rejects_mixed_invalid_and_all_assignees_regardless_of_order():
    routing = {
        **ROUTING,
        "rules": [
            {
                "id": "mixed_invalid_all",
                "keywords": ["家庭会议"],
                "assignees": ["unknown", "all"],
            }
        ],
    }

    result = resolve_family_recipients(
        {"type": "reminder", "name": "家庭会议", "person": "家庭组"},
        MEMBERS,
        routing,
    )

    assert result.members == []
    assert result.metadata["source"] == "keyword_invalid"
    assert result.metadata["rule_id"] == "mixed_invalid_all"
    assert result.metadata["assignees"] == ["all"]
    assert result.metadata["invalid_assignees"] == ["unknown"]


def test_no_keyword_uses_default_all():
    result = resolve_family_recipients(
        {"type": "reminder", "name": "买一把伞", "person": "家庭组"},
        MEMBERS,
        ROUTING,
    )

    assert [member["key"] for member in result.members] == ["dad", "mom", "kid"]
    assert result.metadata["source"] == "default"


def test_keyword_route_accepts_string_assignee_with_whitespace():
    routing = {
        **ROUTING,
        "rules": [
            {
                "id": "mom_string",
                "keywords": ["报名"],
                "assignees": " mom ",
            }
        ],
    }

    result = resolve_family_recipients(
        {"type": "reminder", "name": "科学课报名", "person": "家庭组"},
        MEMBERS,
        routing,
    )

    assert [member["key"] for member in result.members] == ["mom"]
    assert result.metadata["source"] == "keyword"
    assert result.metadata["assignees"] == ["mom"]


def test_dict_assignee_is_invalid_not_treated_as_iterable_keys():
    routing = {
        **ROUTING,
        "rules": [
            {
                "id": "dict_assignee",
                "keywords": ["报名"],
                "assignees": {"mom": True},
            }
        ],
    }

    result = resolve_family_recipients(
        {"type": "reminder", "name": "科学课报名", "person": "家庭组"},
        MEMBERS,
        routing,
    )

    assert result.members == []
    assert result.metadata["source"] == "keyword_invalid"
    assert result.metadata["rule_id"] == "dict_assignee"
    assert result.metadata["invalid_assignees"] == [{"mom": True}]
    assert "unsupported_type:dict" in result.metadata["reason"]


def test_keyword_route_filters_empty_and_reports_mixed_invalid_assignees():
    routing = {
        **ROUTING,
        "rules": [
            {
                "id": "mixed_assignees",
                "keywords": ["报名"],
                "assignees": [" mom ", "", "unknown", "dad"],
            }
        ],
    }

    result = resolve_family_recipients(
        {"type": "reminder", "name": "科学课报名", "person": "家庭组"},
        MEMBERS,
        routing,
    )

    assert result.members == []
    assert result.metadata["source"] == "keyword_invalid"
    assert result.metadata["assignees"] == ["mom", "dad"]
    assert result.metadata["invalid_assignees"] == ["unknown"]
    assert result.metadata["empty_assignees"] == [""]


def test_keyword_route_empty_assignees_returns_visible_error_without_default_fallback():
    routing = {
        **ROUTING,
        "rules": [
            {"id": "empty", "keywords": ["报名"], "assignees": []}
        ],
    }

    result = resolve_family_recipients(
        {"type": "reminder", "name": "科学课报名", "person": "家庭组"},
        MEMBERS,
        routing,
    )

    assert result.members == []
    assert result.metadata["source"] == "keyword_invalid"
    assert result.metadata["rule_id"] == "empty"
    assert result.metadata["reason"] == "keyword rule has no valid assignees"


def test_llm_high_confidence_routes_valid_assignees():
    routing = {**ROUTING, "llm_fallback": True, "rules": []}

    result = resolve_family_recipients(
        {"type": "reminder", "name": "提醒家庭组", "person": "家庭组"},
        MEMBERS,
        routing,
        llm_router=lambda action, members, routing: {
            "confidence": 0.9,
            "assignees": ["mom"],
            "reason": "妈妈处理",
        },
    )

    assert [member["key"] for member in result.members] == ["mom"]
    assert result.metadata["source"] == "llm"
    assert result.metadata["confidence"] == 0.9


def test_llm_low_confidence_reports_fallback_reason_before_default():
    routing = {**ROUTING, "llm_fallback": True, "rules": [], "llm_confidence_threshold": 0.8}

    result = resolve_family_recipients(
        {"type": "reminder", "name": "提醒家庭组", "person": "家庭组"},
        MEMBERS,
        routing,
        llm_router=lambda action, members, routing: {"confidence": 0.5, "assignees": ["mom"]},
    )

    assert [member["key"] for member in result.members] == ["dad", "mom", "kid"]
    assert result.metadata["source"] == "default"
    assert result.metadata["llm_error"] == "low_confidence"
    assert result.metadata["llm_confidence"] == 0.5


def test_llm_boolean_confidence_falls_back_to_default_with_diagnostic():
    routing = {**ROUTING, "llm_fallback": True, "rules": []}

    result = resolve_family_recipients(
        {"type": "reminder", "name": "提醒家庭组", "person": "家庭组"},
        MEMBERS,
        routing,
        llm_router=lambda action, members, routing: {
            "confidence": True,
            "assignees": ["mom"],
            "reason": "妈妈处理",
        },
    )

    assert [member["key"] for member in result.members] == ["dad", "mom", "kid"]
    assert result.metadata["source"] == "default"
    assert result.metadata["llm_error"] == "invalid_confidence_type"


def test_llm_rejects_out_of_range_confidence_before_default_fallback():
    routing = {**ROUTING, "llm_fallback": True, "rules": []}

    cases = [
        (2, "out_of_range_confidence"),
        (-1, "out_of_range_confidence"),
    ]

    for confidence, expected_error in cases:
        result = resolve_family_recipients(
            {"type": "reminder", "name": "提醒家庭组", "person": "家庭组"},
            MEMBERS,
            routing,
            llm_router=lambda action, members, routing, confidence=confidence: {
                "confidence": confidence,
                "assignees": ["mom"],
                "reason": "妈妈处理",
            },
        )

        assert [member["key"] for member in result.members] == ["dad", "mom", "kid"]
        assert result.metadata["source"] == "default"
        assert result.metadata["llm_error"] == expected_error
        assert result.metadata["llm_confidence"] == confidence


def test_llm_exception_non_dict_nan_and_invalid_assignee_are_safe():
    routing = {**ROUTING, "llm_fallback": True, "rules": []}

    def raises(action, members, routing):
        raise RuntimeError("boom")

    cases = [
        (raises, "exception:RuntimeError"),
        (lambda action, members, routing: ["mom"], "non_dict_suggestion"),
        (lambda action, members, routing: {"confidence": float("nan"), "assignees": ["mom"]}, "non_finite_confidence"),
        (lambda action, members, routing: {"confidence": 0.9, "assignees": ["unknown"]}, "invalid_assignees"),
        (lambda action, members, routing: {"confidence": 0.9, "assignees": []}, "no_valid_assignees"),
    ]

    for router, expected_error in cases:
        result = resolve_family_recipients(
            {"type": "reminder", "name": "提醒家庭组", "person": "家庭组"},
            MEMBERS,
            routing,
            llm_router=router,
        )

        assert [member["key"] for member in result.members] == ["dad", "mom", "kid"]
        assert result.metadata["source"] == "default"
        assert result.metadata["llm_error"] == expected_error


def test_llm_rejects_mixed_all_and_invalid_assignees_before_default_fallback():
    routing = {**ROUTING, "llm_fallback": True, "rules": []}

    result = resolve_family_recipients(
        {"type": "reminder", "name": "提醒家庭组", "person": "家庭组"},
        MEMBERS,
        routing,
        llm_router=lambda action, members, routing: {
            "confidence": 0.9,
            "assignees": ["all", "unknown"],
            "reason": "全员处理",
        },
    )

    assert result.metadata["source"] != "llm"
    assert [member["key"] for member in result.members] == ["dad", "mom", "kid"]
    assert result.metadata["llm_error"] == "invalid_assignees"
    assert result.metadata["invalid_assignees"] == ["unknown"]
    assert result.metadata["assignees"] == ["all"]


def test_default_rejects_mixed_all_and_invalid_assignees():
    routing = {**ROUTING, "default": ["all", "unknown"], "rules": []}

    result = resolve_family_recipients(
        {"type": "reminder", "name": "买一把伞", "person": "家庭组"},
        MEMBERS,
        routing,
    )

    assert result.members == []
    assert result.metadata["source"] == "default_invalid"
    assert result.metadata["assignees"] == ["all"]
    assert result.metadata["invalid_assignees"] == ["unknown"]
    assert "invalid assignees" in result.metadata["reason"]
