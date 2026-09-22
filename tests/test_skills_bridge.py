"""Tests for the Skill dry-run -> agent apply bridge helpers."""

import pytest

from nudge.skills.bridge import (
    build_skill_agent_request,
    chunk_actions,
    skill_actions_to_agent_actions,
)


def _skill_action(**overrides):
    action = {
        "type": "calendar_event",
        "source": "skill_dry_run",
        "skill_id": "strength-basics-12w",
        "skill_title": "力量入门 12 周",
        "week": 1,
        "phase_title": "适应期",
        "summary": "力量入门：全身 A",
        "start": "2026-07-06 09:00",
        "end": "2026-07-06 09:45",
    }
    action.update(overrides)
    return action


def test_skill_actions_map_to_calendar_event_create():
    agent_actions = skill_actions_to_agent_actions([_skill_action()])

    assert len(agent_actions) == 1
    item = agent_actions[0]
    assert item["type"] == "calendar_event.create"
    assert item["summary"] == "力量入门：全身 A"
    # Datetimes pass through unchanged (already agent-apply's "%Y-%m-%d %H:%M").
    assert item["start"] == "2026-07-06 09:00"
    assert item["end"] == "2026-07-06 09:45"
    # Skill provenance is carried into notes for traceability.
    assert "力量入门 12 周" in item["notes"]
    assert "W1" in item["notes"]


def test_skill_actions_target_calendar_when_provided():
    agent_actions = skill_actions_to_agent_actions([_skill_action()], calendar="个人")

    assert agent_actions[0]["target"] == {"calendar": "个人"}


def test_skill_actions_reject_unsupported_types():
    with pytest.raises(ValueError):
        skill_actions_to_agent_actions([_skill_action(type="note")])


def test_skill_reminder_actions_become_reminder_create():
    action = _skill_action(type="reminder")
    action["name"] = action["summary"]
    action["due_date"] = action["start"]

    converted = skill_actions_to_agent_actions([action], reminder_list="Tasks")

    assert converted == [{
        "type": "reminder.create",
        "name": action["summary"],
        "due_date": action["start"],
        "body": "力量入门 12 周 · W1 · 适应期",
        "target": {"list": "Tasks"},
    }]


def test_chunk_actions_splits_by_size():
    items = list(range(23))

    chunks = chunk_actions(items, 10)

    assert [len(c) for c in chunks] == [10, 10, 3]
    assert chunks[0][0] == 0
    assert chunks[-1] == [20, 21, 22]


def test_chunk_actions_rejects_bad_size():
    with pytest.raises(ValueError):
        chunk_actions([1, 2], 0)


def test_build_request_sets_plan_driven_confirmation():
    request = build_skill_agent_request(
        [{"type": "calendar_event.create", "summary": "x", "start": "a", "end": "b"}],
        source="skills.schedule",
        text_plan_ref="docs/plans/example-plan.md",
        request_id="skill-x-1",
        dry_run=True,
    )

    assert request["plan_driven"] is True
    assert request["text_plan_confirmed"] is True
    assert request["text_plan_ref"] == "docs/plans/example-plan.md"
    assert request["require_confirmation"] is True
    assert request["dry_run"] is True
    assert request["dry_run_token"] is None
    assert request["request_id"] == "skill-x-1"


def test_build_request_carries_dry_run_token_for_real_write():
    request = build_skill_agent_request(
        [{"type": "calendar_event.create", "summary": "x", "start": "a", "end": "b"}],
        source="skills.schedule",
        text_plan_ref="docs/plans/example-plan.md",
        request_id="skill-x-1",
        dry_run=False,
        dry_run_token="nudge.agent.confirm.v1:deadbeef",
    )

    assert request["dry_run"] is False
    assert request["dry_run_token"] == "nudge.agent.confirm.v1:deadbeef"
