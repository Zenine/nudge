"""Tests for plan state helpers."""

import json


def test_get_plan_returns_row_or_none(monkeypatch, tmp_path):
    import nudge.state as state

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")

    plan_id = state.create_plan("每周力量训练", {"kind": "strength", "week": 1})

    row = state.get_plan(plan_id)

    assert row is not None
    assert row["id"] == plan_id
    assert row["goal"] == "每周力量训练"
    assert json.loads(row["config"])["kind"] == "strength"
    assert state.get_plan("missing") is None
    assert state.get_plan("") is None


def test_update_plan_config_replaces_config_json(monkeypatch, tmp_path):
    import nudge.state as state

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")

    plan_id = state.create_plan("第 2 周训练", {"kind": "strength", "week": 1})

    state.update_plan_config(plan_id, {"week": 2, "extra": "值"})

    row = state.get_plan(plan_id)
    assert row is not None
    assert json.loads(row["config"]) == {"week": 2, "extra": "值"}


def test_update_plan_status_changes_active_filter(monkeypatch, tmp_path):
    import nudge.state as state

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")

    plan_id = state.create_plan("第 1 周训练", {"kind": "strength"})

    state.update_plan_status(plan_id, "failed")

    row = state.get_plan(plan_id)
    assert row is not None
    assert row["status"] == "failed"
    assert [plan["id"] for plan in state.get_plans(status="active")] == []
    assert [plan["id"] for plan in state.get_plans(status="failed")] == [plan_id]
