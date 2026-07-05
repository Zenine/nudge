"""Tests for SQLite state initialization caching and migration."""

import json
import sqlite3
from pathlib import Path


ACTION_INDEXES = {
    "idx_actions_status",
    "idx_actions_plan_id",
    "idx_actions_scheduled_at",
    "idx_actions_completed_at",
    "idx_actions_created_at",
}


def _isolate_state(monkeypatch, tmp_path, state):
    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")
    monkeypatch.setattr(state, "_migrated", False)
    monkeypatch.setattr(state, "_schema_initialized_for", None, raising=False)


def test_schema_initialization_runs_once_per_db_path(monkeypatch, tmp_path):
    import nudge.state as state

    _isolate_state(monkeypatch, tmp_path, state)
    calls = {"count": 0}
    original_init_tables = state._init_tables

    def counted_init_tables(conn):
        calls["count"] += 1
        return original_init_tables(conn)

    monkeypatch.setattr(state, "_init_tables", counted_init_tables)

    plan_id = state.create_plan("每周力量训练", {"week": 1})
    assert state.get_plan(plan_id)["goal"] == "每周力量训练"
    state.log_action("reminder", "训练 A", plan_id=plan_id, status="pending")
    assert [row["summary"] for row in state.get_actions(plan_id=plan_id)] == ["训练 A"]

    assert calls["count"] == 1


def test_configure_state_switching_db_path_initializes_new_database(monkeypatch, tmp_path):
    import nudge.state as state

    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    monkeypatch.setattr(state, "STATE_DIR", first_dir)
    monkeypatch.setattr(state, "DB_PATH", first_dir / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", first_dir / "state.json")
    monkeypatch.setattr(state, "_migrated", False)
    monkeypatch.setattr(state, "_schema_initialized_for", None, raising=False)
    calls = {"count": 0}
    original_init_tables = state._init_tables

    def counted_init_tables(conn):
        calls["count"] += 1
        return original_init_tables(conn)

    monkeypatch.setattr(state, "_init_tables", counted_init_tables)

    state.configure_state({"state": {"dir": str(first_dir)}})
    first_plan_id = state.create_plan("第一个状态目录")
    assert state.get_plan(first_plan_id)["goal"] == "第一个状态目录"

    state.configure_state({"state": {"dir": str(second_dir)}})
    second_plan_id = state.create_plan("第二个状态目录")
    assert state.get_plan(second_plan_id)["goal"] == "第二个状态目录"
    assert state.get_plan(first_plan_id) is None

    assert calls["count"] == 2


def test_actions_query_indexes_exist(monkeypatch, tmp_path):
    import nudge.state as state

    _isolate_state(monkeypatch, tmp_path, state)

    state.log_action("reminder", "建立 actions schema", status="pending")

    conn = sqlite3.connect(str(state.DB_PATH))
    try:
        index_names = {row[1] for row in conn.execute("PRAGMA index_list('actions')").fetchall()}
    finally:
        conn.close()

    assert ACTION_INDEXES <= index_names


def test_legacy_state_json_migration_still_imports_habits(monkeypatch, tmp_path):
    import nudge.state as state

    _isolate_state(monkeypatch, tmp_path, state)
    state.LEGACY_JSON.write_text(
        json.dumps(
            {
                "habits": {
                    "reading": {"last_logged": "2026-07-03", "streak": 5},
                }
            }
        ),
        encoding="utf-8",
    )

    streaks = state.get_habit_streaks()

    assert streaks["reading"] == {"streak": 5, "last_logged": "2026-07-03"}
    assert not state.LEGACY_JSON.exists()
    assert state.LEGACY_JSON.with_suffix(".json.bak").exists()

    conn = sqlite3.connect(str(state.DB_PATH))
    try:
        rows = conn.execute(
            "SELECT habit_name, date, streak FROM habit_logs WHERE habit_name = ?",
            ("reading",),
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("reading", "2026-07-03", 5)]


def test_invalid_legacy_state_json_is_left_for_retry(monkeypatch, tmp_path):
    import nudge.state as state

    _isolate_state(monkeypatch, tmp_path, state)
    state.LEGACY_JSON.write_text("{not valid json", encoding="utf-8")

    assert state.get_habit_streaks() == {}
    assert state.LEGACY_JSON.exists()
    assert not state.LEGACY_JSON.with_suffix(".json.bak").exists()

    conn = sqlite3.connect(str(state.DB_PATH))
    try:
        migration_status = conn.execute(
            "SELECT status FROM state_migrations WHERE name = ?",
            ("legacy_state_json",),
        ).fetchone()
    finally:
        conn.close()
    assert migration_status is None


def test_existing_sqlite_habits_skip_legacy_state_json_migration(monkeypatch, tmp_path):
    import nudge.state as state

    _isolate_state(monkeypatch, tmp_path, state)
    state.update_habit("existing")
    state.LEGACY_JSON.write_text(
        json.dumps(
            {
                "habits": {
                    "legacy-only": {"last_logged": "2026-07-04", "streak": 9},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(state, "_migrated", False)

    streaks = state.get_habit_streaks()

    assert "existing" in streaks
    assert "legacy-only" not in streaks
    assert state.LEGACY_JSON.exists()
    assert not state.LEGACY_JSON.with_suffix(".json.bak").exists()

    conn = sqlite3.connect(str(state.DB_PATH))
    try:
        migration_status = conn.execute(
            "SELECT status FROM state_migrations WHERE name = ?",
            ("legacy_state_json",),
        ).fetchone()
    finally:
        conn.close()
    assert migration_status is None


def test_legacy_state_json_archive_failure_is_retryable(monkeypatch, tmp_path):
    import nudge.state as state

    _isolate_state(monkeypatch, tmp_path, state)
    state.LEGACY_JSON.write_text(
        json.dumps(
            {
                "habits": {
                    "mobility": {"last_logged": "2026-07-04", "streak": 2},
                }
            }
        ),
        encoding="utf-8",
    )

    original_rename = Path.rename
    fail_rename = {"value": True}

    def flaky_rename(self, target):
        if self == state.LEGACY_JSON and fail_rename["value"]:
            raise OSError("simulated archive failure")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)

    streaks = state.get_habit_streaks()

    assert streaks["mobility"] == {"streak": 2, "last_logged": "2026-07-04"}
    assert state.LEGACY_JSON.exists()
    assert not state.LEGACY_JSON.with_suffix(".json.bak").exists()

    conn = sqlite3.connect(str(state.DB_PATH))
    try:
        rows_after_failure = conn.execute(
            "SELECT habit_name, date, streak FROM habit_logs WHERE habit_name = ?",
            ("mobility",),
        ).fetchall()
        migration_status = conn.execute(
            "SELECT status FROM state_migrations WHERE name = ?",
            ("legacy_state_json",),
        ).fetchone()
    finally:
        conn.close()
    assert rows_after_failure == [("mobility", "2026-07-04", 2)]
    assert migration_status == ("archive_pending",)

    fail_rename["value"] = False
    monkeypatch.setattr(state, "_migrated", False)

    retried_streaks = state.get_habit_streaks()

    assert retried_streaks["mobility"] == {"streak": 2, "last_logged": "2026-07-04"}
    assert not state.LEGACY_JSON.exists()
    assert state.LEGACY_JSON.with_suffix(".json.bak").exists()

    conn = sqlite3.connect(str(state.DB_PATH))
    try:
        rows_after_retry = conn.execute(
            "SELECT habit_name, date, streak FROM habit_logs WHERE habit_name = ?",
            ("mobility",),
        ).fetchall()
        migration_status = conn.execute(
            "SELECT status FROM state_migrations WHERE name = ?",
            ("legacy_state_json",),
        ).fetchone()
    finally:
        conn.close()
    assert rows_after_retry == [("mobility", "2026-07-04", 2)]
    assert migration_status == ("archived",)
