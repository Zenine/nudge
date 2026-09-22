"""Tests for Skill Spec v0.1 schema validation."""

from pathlib import Path
from textwrap import dedent

import pytest

from nudge.skills.schema import SkillValidationError, load_skill_file, validate_skill


def valid_skill() -> dict:
    return {
        "schema_version": "0.1",
        "kind": "skill",
        "metadata": {
            "id": "strength-basics-12w",
            "title": "12 周力量基础",
            "version": "1.0.0",
            "creator": "张教练",
            "category": "fitness",
        },
        "audience": {"goals": ["建立训练习惯"], "prerequisites": ["无严重伤病"]},
        "assessment": [
            {
                "id": "current_frequency",
                "question": "你目前每周训练几次？",
                "type": "single_choice",
                "options": [{"id": "never", "label": "从不"}],
            }
        ],
        "personalization": [
            {
                "id": "beginner_frequency",
                "when": {"==": [{"var": "assessment.current_frequency"}, "never"]},
                "apply": [
                    {
                        "op": "set",
                        "path": "plan_template.defaults.sessions_per_week",
                        "value": 3,
                    }
                ],
            }
        ],
        "plan_template": {
            "defaults": {"sessions_per_week": 4, "session_minutes": 45},
            "phases": [
                {
                    "id": "foundation",
                    "weeks": 4,
                    "sessions": [
                        {
                            "id": "lower_a",
                            "exercises": [{"name": "硬拉"}, {"name": "深蹲"}],
                        }
                    ],
                }
            ],
        },
        "tracking": {
            "metrics": [
                {"id": "session_completed", "type": "boolean"},
                {"id": "subjective_effort", "type": "scale", "min": 1, "max": 10},
            ]
        },
        "adaptation": [
            {
                "id": "too_hard_deload",
                "trigger": {">": [{"var": "history.effort_avg_7d"}, 8]},
                "apply": [
                    {
                        "op": "clamp",
                        "path": "plan_template.defaults.session_minutes",
                        "max": 40,
                    }
                ],
            }
        ],
    }


def test_load_skill_file_accepts_yaml(tmp_path: Path):
    path = tmp_path / "skill.yaml"
    path.write_text(
        dedent(
            """
            schema_version: "0.1"
            kind: skill
            metadata:
              id: cpa-90d
              title: CPA 90 天
              version: 1.0.0
              creator: 李老师
              category: study
            audience:
              goals: ["通过 CPA"]
            assessment:
              - id: baseline
                question: 当前基础？
                type: text
            plan_template:
              defaults:
                daily_minutes: 90
            tracking:
              metrics:
                - id: study_completed
                  type: boolean
            """
        ).strip()
    )

    skill = load_skill_file(path)

    assert skill["metadata"]["id"] == "cpa-90d"
    validate_skill(skill)


def test_validate_skill_accepts_valid_skill():
    assert validate_skill(valid_skill()) == valid_skill()


def test_validate_skill_reports_missing_required_paths():
    skill = valid_skill()
    del skill["metadata"]["title"]
    del skill["tracking"]

    with pytest.raises(SkillValidationError) as exc_info:
        validate_skill(skill)

    message = str(exc_info.value)
    assert "metadata.title" in message
    assert "tracking" in message


def test_validate_skill_rejects_unsupported_schema_version():
    skill = valid_skill()
    skill["schema_version"] = "9.9"

    with pytest.raises(SkillValidationError) as exc_info:
        validate_skill(skill)

    assert "schema_version" in str(exc_info.value)
    assert "0.1" in str(exc_info.value)


def test_validate_skill_rejects_unknown_jsonlogic_operator():
    skill = valid_skill()
    skill["personalization"][0]["when"] = {"eval": "assessment.current_frequency == 'never'"}

    with pytest.raises(SkillValidationError) as exc_info:
        validate_skill(skill)

    assert "personalization[0].when" in str(exc_info.value)
    assert "eval" in str(exc_info.value)


def test_validate_skill_rejects_dangerous_patch_path():
    skill = valid_skill()
    skill["personalization"][0]["apply"][0]["path"] = "__proto__.polluted"

    with pytest.raises(SkillValidationError) as exc_info:
        validate_skill(skill)

    assert "__proto__" in str(exc_info.value)


def test_validate_skill_rejects_code_execution_fields():
    skill = valid_skill()
    skill["runtime"] = {"shell": "rm -rf /"}

    with pytest.raises(SkillValidationError) as exc_info:
        validate_skill(skill)

    assert "runtime.shell" in str(exc_info.value)
