import pytest

from nudge.skills.dryrun import dry_run_skill


def _minimal_skill(*, defaults_action_type=None, session_action_type=None):
    defaults = {
        "sessions_per_week": 1,
        "preferred_days": ["Monday"],
        "preferred_time": "08:00",
    }
    if defaults_action_type is not None:
        defaults["action_type"] = defaults_action_type

    session = {
        "id": "session-1",
        "title": "Morning practice",
        "duration_minutes": 30,
    }
    if session_action_type is not None:
        session["action_type"] = session_action_type

    return {
        "schema_version": "0.1",
        "kind": "skill",
        "metadata": {
            "id": "test-skill",
            "title": "Test Skill",
            "version": "1.0.0",
            "creator": "test",
            "category": "test",
        },
        "audience": {"description": "test audience"},
        "assessment": [
            {
                "id": "readiness",
                "question": "Ready?",
                "type": "boolean",
            }
        ],
        "plan_template": {
            "defaults": defaults,
            "phases": [
                {
                    "id": "phase-1",
                    "title": "Phase 1",
                    "weeks": [1],
                    "sessions": [session],
                }
            ],
        },
        "tracking": {
            "metrics": [
                {
                    "id": "completion",
                    "type": "count",
                }
            ]
        },
    }


def _context():
    return {"profile": {"start_date": "2026-07-06"}}


def _skill() -> dict:
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
        "audience": {"goals": ["建立训练习惯"]},
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
                    {"op": "set", "path": "plan_template.defaults.sessions_per_week", "value": 3}
                ],
            }
        ],
        "plan_template": {
            "defaults": {
                "sessions_per_week": 4,
                "session_minutes": 45,
                "preferred_days": ["Monday", "Wednesday", "Friday", "Sunday"],
                "preferred_time": "07:30",
            },
            "phases": [
                {
                    "id": "foundation",
                    "title": "基础期",
                    "weeks": 4,
                    "sessions": [
                        {"id": "upper_a", "title": "上肢 A", "duration_minutes": 45},
                        {"id": "lower_a", "title": "下肢 A", "duration_minutes": 45},
                        {"id": "mobility", "focus": "灵活性", "duration_minutes": 30},
                    ],
                }
            ],
        },
        "tracking": {"metrics": [{"id": "session_completed", "type": "boolean"}]},
        "adaptation": [
            {
                "id": "too_hard_deload",
                "trigger": {">": [{"var": "history.effort_avg_7d"}, 8]},
                "apply": [
                    {"op": "clamp", "path": "plan_template.defaults.session_minutes", "max": 40}
                ],
            }
        ],
    }


def test_default_action_type_is_calendar_event():
    result = dry_run_skill(_minimal_skill(), _context(), weeks=1)

    assert len(result.actions) == 1
    assert result.actions[0]["type"] == "calendar_event"
    assert result.actions[0]["summary"] == "Test Skill：Morning practice"
    assert result.actions[0]["start"] == "2026-07-06 08:00"
    assert result.actions[0]["end"] == "2026-07-06 08:30"



def test_preferred_days_shorter_than_sessions_per_week_staggers_same_day_sessions():
    skill = _minimal_skill()
    skill["plan_template"]["defaults"]["sessions_per_week"] = 3
    skill["plan_template"]["defaults"]["preferred_days"] = ["Monday"]

    result = dry_run_skill(skill, _context(), weeks=1)

    assert [action["scheduled_date"] for action in result.actions] == [
        "2026-07-06",
        "2026-07-06",
        "2026-07-06",
    ]
    assert [action["start"] for action in result.actions] == [
        "2026-07-06 08:00",
        "2026-07-06 08:30",
        "2026-07-06 09:00",
    ]
    assert len({action["start"] for action in result.actions}) == 3

def test_session_action_type_reminder_outputs_reminder_contract_fields():
    result = dry_run_skill(
        _minimal_skill(session_action_type="reminder"),
        _context(),
        weeks=1,
    )

    action = result.actions[0]
    assert action["type"] == "reminder"
    assert action["name"] == action["summary"]
    assert action["due_date"] == "2026-07-06 08:00"
    assert action["start"] == "2026-07-06 08:00"


def test_defaults_action_type_reminder_applies_to_all_sessions():
    result = dry_run_skill(
        _minimal_skill(defaults_action_type="reminder"),
        _context(),
        weeks=2,
    )

    assert [action["type"] for action in result.actions] == ["reminder", "reminder"]
    assert all(action["name"] == action["summary"] for action in result.actions)
    assert all(action["due_date"] == action["start"] for action in result.actions)


def test_unsupported_action_type_raises_value_error():
    with pytest.raises(ValueError, match="unsupported plan_template action_type"):
        dry_run_skill(_minimal_skill(defaults_action_type="note"), _context(), weeks=1)


def test_non_string_action_type_raises_value_error():
    with pytest.raises(ValueError, match="unsupported plan_template action_type"):
        dry_run_skill(_minimal_skill(defaults_action_type=["reminder"]), _context(), weeks=1)


def test_explicit_falsey_session_action_type_raises_value_error():
    with pytest.raises(ValueError, match="unsupported plan_template action_type"):
        dry_run_skill(_minimal_skill(session_action_type=[]), _context(), weeks=1)


def test_explicit_falsey_defaults_action_type_raises_value_error():
    with pytest.raises(ValueError, match="unsupported plan_template action_type"):
        dry_run_skill(_minimal_skill(defaults_action_type={}), _context(), weeks=1)


def test_dry_run_skill_applies_rules_and_generates_week_one_actions():
    result = dry_run_skill(
        _skill(),
        {
            "assessment": {"current_frequency": "never"},
            "profile": {"start_date": "2026-04-27"},
        },
        weeks=1,
    )

    assert result.personalization_applied == ["beginner_frequency"]
    assert result.adaptation_applied == []
    assert len(result.actions) == 3
    assert result.actions[0] == {
        "type": "calendar_event",
        "source": "skill_dry_run",
        "skill_id": "strength-basics-12w",
        "skill_title": "12 周力量基础",
        "week": 1,
        "phase_id": "foundation",
        "phase_title": "基础期",
        "session_id": "upper_a",
        "summary": "12 周力量基础：上肢 A",
        "scheduled_date": "2026-04-27",
        "start": "2026-04-27 07:30",
        "end": "2026-04-27 08:15",
        "duration_minutes": 45,
    }
    assert result.actions[1]["scheduled_date"] == "2026-04-29"
    assert result.actions[2]["scheduled_date"] == "2026-05-01"
    assert result.skill["plan_template"]["defaults"]["sessions_per_week"] == 3


def test_dry_run_skill_supports_multiple_weeks_and_profile_overrides():
    result = dry_run_skill(
        _skill(),
        {
            "assessment": {"current_frequency": "never"},
            "profile": {
                "start_date": "2026-04-27",
                "preferred_days": ["Tuesday", "Thursday"],
                "preferred_time": "20:00",
            },
        },
        weeks=2,
    )

    assert len(result.actions) == 6
    assert result.actions[0]["start"] == "2026-04-28 20:00"
    assert result.actions[1]["start"] == "2026-04-30 20:00"
    # 同日第三次 session 顺延到上一节之后（公开库 dry-run 的同日错开规则）
    assert result.actions[2]["start"] == "2026-04-28 20:45"
    assert result.actions[3]["week"] == 2
    assert result.actions[3]["start"] == "2026-05-05 20:00"


def test_dry_run_skill_reports_adaptation_rules_and_default_duration():
    skill = _skill()
    del skill["plan_template"]["phases"][0]["sessions"][0]["duration_minutes"]

    result = dry_run_skill(
        skill,
        {
            "assessment": {"current_frequency": "never"},
            "history": {"effort_avg_7d": 9},
            "profile": {"start_date": "2026-04-27"},
        },
        weeks=1,
    )

    assert result.adaptation_applied == ["too_hard_deload"]
    assert result.actions[0]["duration_minutes"] == 40
    assert result.actions[0]["end"] == "2026-04-27 08:10"


def test_dry_run_skill_never_schedules_before_profile_start_date():
    result = dry_run_skill(
        _skill(),
        {
            "assessment": {"current_frequency": "never"},
            "profile": {
                "start_date": "2026-04-29",
                "preferred_days": ["Monday", "Friday"],
            },
        },
        weeks=1,
    )

    assert all(action["scheduled_date"] >= "2026-04-29" for action in result.actions)
