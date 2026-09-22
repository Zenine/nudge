"""Tests for high-level Skill personalization and adaptation execution."""

from tests.test_skills_schema import valid_skill

from nudge.skills.engine import apply_adaptations, personalize_skill


def test_personalize_skill_applies_matching_rules():
    skill = valid_skill()
    skill["personalization"].append(
        {
            "id": "lower_back_safe_substitution",
            "when": {"in": ["lower_back", {"var": "assessment.injuries"}]},
            "apply": [
                {
                    "op": "replace",
                    "path": "plan_template.phases[].sessions[].exercises[]",
                    "where": {"==": [{"var": "item.name"}, "硬拉"]},
                    "value": {"name": "哑铃罗马尼亚硬拉"},
                }
            ],
        }
    )

    result = personalize_skill(
        skill,
        {
            "assessment": {
                "current_frequency": "never",
                "injuries": ["lower_back"],
            }
        },
    )

    assert result.applied_rules == ["beginner_frequency", "lower_back_safe_substitution"]
    assert result.skill["plan_template"]["defaults"]["sessions_per_week"] == 3
    exercises = result.skill["plan_template"]["phases"][0]["sessions"][0]["exercises"]
    assert exercises[0]["name"] == "哑铃罗马尼亚硬拉"


def test_personalize_skill_skips_non_matching_rules():
    result = personalize_skill(
        valid_skill(),
        {"assessment": {"current_frequency": "three_plus", "injuries": []}},
    )

    assert result.applied_rules == []
    assert result.skill["plan_template"]["defaults"]["sessions_per_week"] == 4


def test_apply_adaptations_applies_matching_triggers_after_personalization():
    result = apply_adaptations(
        valid_skill(),
        {"history": {"effort_avg_7d": 9}},
    )

    assert result.applied_rules == ["too_hard_deload"]
    assert result.skill["plan_template"]["defaults"]["session_minutes"] == 40
