"""Tests for deterministic Skill patch application."""

import pytest

from nudge.skills.patch import PatchError, apply_patches, validate_path


def base_target() -> dict:
    return {
        "plan_template": {
            "defaults": {"sessions_per_week": 4, "session_minutes": 45},
            "phases": [
                {
                    "id": "foundation",
                    "sessions": [
                        {
                            "id": "lower_a",
                            "exercises": [{"name": "硬拉"}, {"name": "深蹲"}],
                        }
                    ],
                }
            ],
        }
    }


def test_apply_set_and_clamp_patches_without_mutating_input():
    target = base_target()

    result = apply_patches(
        target,
        [
            {"op": "set", "path": "plan_template.defaults.sessions_per_week", "value": 3},
            {"op": "clamp", "path": "plan_template.defaults.session_minutes", "max": 40},
        ],
        context={},
    )

    assert result["plan_template"]["defaults"]["sessions_per_week"] == 3
    assert result["plan_template"]["defaults"]["session_minutes"] == 40
    assert target["plan_template"]["defaults"]["sessions_per_week"] == 4
    assert target["plan_template"]["defaults"]["session_minutes"] == 45


def test_apply_replace_patch_with_item_where_rule():
    result = apply_patches(
        base_target(),
        [
            {
                "op": "replace",
                "path": "plan_template.phases[].sessions[].exercises[]",
                "where": {"==": [{"var": "item.name"}, "硬拉"]},
                "value": {"name": "哑铃罗马尼亚硬拉"},
            }
        ],
        context={},
    )

    exercises = result["plan_template"]["phases"][0]["sessions"][0]["exercises"]
    assert exercises == [{"name": "哑铃罗马尼亚硬拉"}, {"name": "深蹲"}]


def test_apply_insert_tag_and_validate_patches():
    result = apply_patches(
        base_target(),
        [
            {
                "op": "insert",
                "path": "plan_template.phases",
                "value": {"id": "deload", "weeks": 1},
            },
            {"op": "tag", "value": "beginner"},
            {
                "op": "validate",
                "rule": {"==": [{"var": "plan_template.defaults.sessions_per_week"}, 4]},
                "message": "sessions_per_week must remain 4",
            },
        ],
        context={},
    )

    assert result["_tags"] == ["beginner"]
    assert result["plan_template"]["phases"][-1]["id"] == "deload"


def test_apply_insert_creates_missing_list_path():
    result = apply_patches(
        base_target(),
        [{"op": "insert", "path": "plan.weeks", "value": {"kind": "deload"}}],
        context={},
    )

    assert result["plan"]["weeks"] == [{"kind": "deload"}]


def test_validate_patch_raises_when_rule_is_false():
    with pytest.raises(PatchError) as exc_info:
        apply_patches(
            base_target(),
            [
                {
                    "op": "validate",
                    "rule": {"<=": [{"var": "plan_template.defaults.sessions_per_week"}, 3]},
                    "message": "too many sessions",
                }
            ],
            context={},
        )

    assert "too many sessions" in str(exc_info.value)


def test_validate_path_rejects_dangerous_paths():
    for path in ["/tmp/skill", "plan..defaults", "__proto__.x", "plan.constructor.value"]:
        with pytest.raises(PatchError):
            validate_path(path)
