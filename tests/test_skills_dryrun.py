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


def test_default_action_type_is_calendar_event():
    result = dry_run_skill(_minimal_skill(), _context(), weeks=1)

    assert len(result.actions) == 1
    assert result.actions[0]["type"] == "calendar_event"
    assert result.actions[0]["summary"] == "Test Skill：Morning practice"
    assert result.actions[0]["start"] == "2026-07-06 08:00"
    assert result.actions[0]["end"] == "2026-07-06 08:30"


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
