"""Tests for deterministic skill instance runtime helpers."""

import json

import pytest


_SKILL = {
    "metadata": {
        "id": "test-skill",
        "title": "测试 Skill",
        "version": "1.0.0",
    },
    "plan_template": {
        "phases": [
            {"id": "phase-1", "weeks": 4},
            {"id": "phase-2", "weeks": 8},
        ],
    },
    "tracking": {
        "metrics": [
            {"id": "session_completed", "type": "boolean"},
            {"id": "effort", "type": "number"},
        ],
    },
}


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    import nudge.state as state

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")


def test_instance_roundtrip():
    from nudge.skills.runtime import create_skill_instance, get_skill_instance, list_skill_instances

    context = {"answers": {"level": "beginner"}}

    plan_id = create_skill_instance(
        _SKILL,
        context,
        start_date="2026-07-06",
        weeks_total=12,
        materialized_through_week=1,
        personalization_applied=["preferred_days"],
    )

    instance = get_skill_instance(plan_id)
    assert instance is not None
    assert instance["plan_id"] == plan_id
    assert instance["goal"] == "Skill: 测试 Skill"
    assert instance["status"] == "active"
    assert instance["created_at"]
    assert instance["kind"] == "skill_instance"
    assert instance["skill_id"] == "test-skill"
    assert instance["skill_version"] == "1.0.0"
    assert instance["context"] == context
    assert instance["start_date"] == "2026-07-06"
    assert instance["weeks_total"] == 12
    assert instance["materialized_through_week"] == 1
    assert instance["personalization_applied"] == ["preferred_days"]

    context["answers"]["level"] = "changed"
    assert get_skill_instance(plan_id)["context"]["answers"]["level"] == "beginner"
    assert [item["plan_id"] for item in list_skill_instances()] == [plan_id]


def test_list_skips_non_skill_plans():
    import nudge.state as state
    from nudge.skills.runtime import get_skill_instance, list_skill_instances

    state.create_plan("普通计划", {"kind": "ordinary"})
    state.create_plan("无配置计划")

    assert list_skill_instances() == []
    assert get_skill_instance("missing") is None

    with state._db() as conn:
        conn.execute(
            "INSERT INTO plans (id, goal, config) VALUES (?, ?, ?)",
            ("bad-json", "坏配置", "not json"),
        )
    assert get_skill_instance("bad-json") is None


def test_record_materialized_week_only_moves_forward():
    from nudge.skills.runtime import (
        create_skill_instance,
        get_skill_instance,
        record_materialized_week,
    )

    plan_id = create_skill_instance(
        _SKILL,
        {},
        start_date="2026-07-06",
        weeks_total=12,
        materialized_through_week=1,
        personalization_applied=[],
    )

    record_materialized_week(plan_id, 3)
    assert get_skill_instance(plan_id)["materialized_through_week"] == 3

    record_materialized_week(plan_id, 2)
    assert get_skill_instance(plan_id)["materialized_through_week"] == 3

    with pytest.raises(ValueError):
        record_materialized_week("missing", 1)


def test_record_materialized_week_preserves_raw_config_conflicting_keys():
    import nudge.state as state
    from nudge.skills import runtime

    plan_id = runtime.create_skill_instance(
        _SKILL,
        {},
        start_date="2026-07-06",
        weeks_total=12,
        materialized_through_week=1,
        personalization_applied=[],
    )
    original_config = {
        "kind": runtime.SKILL_INSTANCE_KIND,
        "materialized_through_week": 1,
        "plan_id": "config-plan-id",
        "goal": "config-goal",
        "status": "config-status",
        "created_at": "config-created-at",
        "custom": {"nested": True},
    }
    state.update_plan_config(plan_id, original_config)

    runtime.record_materialized_week(plan_id, 3)

    row = state.get_plan(plan_id)
    saved_config = json.loads(row["config"])
    assert saved_config == {
        **original_config,
        "materialized_through_week": 3,
    }


def test_skill_helpers():
    from nudge.skills.runtime import numeric_metric_ids, skill_weeks_total

    assert skill_weeks_total(_SKILL) == 12
    assert skill_weeks_total({}) is None
    assert skill_weeks_total({"plan_template": {"phases": [{"weeks": 0}]}}) is None
    assert numeric_metric_ids(_SKILL) == ["effort"]
    assert numeric_metric_ids({}) == []


def _tracked_action(state, plan_id, scheduled_at, status, metrics=None):
    action_id = state.log_action(
        "reminder",
        f"{plan_id} {scheduled_at} {status}",
        scheduled_at=scheduled_at,
        plan_id=plan_id,
    )
    feedback = {"metrics": metrics} if metrics is not None else None
    if status == "done":
        state.complete_action(action_id, feedback=feedback)
    elif status == "partial":
        state.partial_action(action_id, feedback=feedback)
    elif status == "skipped":
        state.skip_action(action_id, feedback=feedback)
    return action_id


def test_build_tracking_context_windows_and_metrics():
    from datetime import date

    import nudge.state as state
    from nudge.skills.runtime import build_tracking_context

    plan_id = "plan-a"
    other_plan_id = "plan-b"

    _tracked_action(state, plan_id, "2026-07-04 09:00", "done", {"effort": 9})
    _tracked_action(state, plan_id, "2026-07-01 09:00", "done", {"effort": 8})
    state.log_action("reminder", "planned session", scheduled_at="2026-07-02 09:00", plan_id=plan_id)
    _tracked_action(state, plan_id, "2026-06-30 09:00", "skipped", {"effort": 99})
    _tracked_action(state, plan_id, "2026-06-28 09:00", "partial", {"effort": 6})
    _tracked_action(state, plan_id, "2026-06-24 09:00", "done", {"effort": 3})
    _tracked_action(state, plan_id, "2026-06-20 09:00", "done", {"effort": 1})
    _tracked_action(state, plan_id, None, "done", {"effort": 1})
    _tracked_action(state, other_plan_id, "2026-07-04 09:00", "done", {"effort": 10})

    context = build_tracking_context(
        plan_id,
        ["effort"],
        today=date(2026, 7, 4),
    )

    history = context["history"]
    assert history["sessions_total_7d"] == 5
    assert history["sessions_completed_7d"] == 2
    assert history["sessions_partial_7d"] == 1
    assert history["sessions_skipped_7d"] == 1
    assert history["completion_rate_7d"] == 0.4
    assert history["effort_avg_7d"] == round((9 + 8 + 6) / 3, 2)

    assert history["sessions_total_14d"] == 6
    assert history["sessions_completed_14d"] == 3
    assert history["sessions_partial_14d"] == 1
    assert history["sessions_skipped_14d"] == 1
    assert history["completion_rate_14d"] == 0.5
    assert history["effort_avg_14d"] == round((9 + 8 + 6 + 3) / 4, 2)


def test_build_tracking_context_empty_plan_omits_metric_keys():
    from datetime import date

    from nudge.skills.runtime import build_tracking_context

    context = build_tracking_context(
        "empty-plan",
        ["effort"],
        today=date(2026, 7, 4),
    )

    history = context["history"]
    assert history["sessions_total_7d"] == 0
    assert history["completion_rate_7d"] == 0.0
    assert history["sessions_total_14d"] == 0
    assert history["completion_rate_14d"] == 0.0
    assert "effort_avg_7d" not in history
    assert "effort_avg_14d" not in history
