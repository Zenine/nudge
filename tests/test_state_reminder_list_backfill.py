"""Tests for atomic SQLite reminder-list ownership backfill."""

import sqlite3

import pytest

import nudge.state as state


SNAPSHOT_FIELDS = ("id", "type", "summary", "scheduled_at", "status", "reminder_list")


def _valid_snapshot(action_id="first"):
    return {
        "id": action_id,
        "type": "reminder",
        "summary": action_id,
        "scheduled_at": None,
        "status": "pending",
        "reminder_list": None,
    }


def _isolate_state(monkeypatch, tmp_path):
    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")
    monkeypatch.setattr(state, "_migrated", False)
    monkeypatch.setattr(state, "_schema_initialized_for", None, raising=False)


def _insert_action(
    action_id,
    *,
    action_type="reminder",
    summary=None,
    scheduled_at="2026-07-19 09:00",
    completed_at=None,
    status="pending",
    external_id=None,
    reminder_list=None,
    feedback=None,
):
    conn = state._get_conn()
    try:
        conn.execute(
            """
            INSERT INTO actions (
                id, type, summary, scheduled_at, completed_at, status,
                external_id, reminder_list, feedback
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_id,
                action_type,
                summary or action_id,
                scheduled_at,
                completed_at,
                status,
                external_id,
                reminder_list,
                feedback,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _action(action_id):
    return next(item for item in state.get_actions() if item["id"] == action_id)


def _snapshot(action_id):
    action = _action(action_id)
    return {field: action[field] for field in SNAPSHOT_FIELDS}


def test_backfill_changes_only_reminder_list_and_returns_applied_ids(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    _insert_action(
        "first",
        summary="Keep every other column",
        scheduled_at="2026-07-19 10:30",
        completed_at="2026-07-19 10:45",
        status="created",
        external_id="apple-123",
        feedback='{"note": "unchanged"}',
    )
    before = _action("first")

    applied = state.apply_reminder_list_backfill(
        [{"id": "first", "target_list": "  Focus  "}],
        snapshots={"first": _snapshot("first")},
    )

    after = _action("first")
    assert applied == ["first"]
    assert after["reminder_list"] == "Focus"
    assert {
        key: value for key, value in after.items() if key != "reminder_list"
    } == {
        key: value for key, value in before.items() if key != "reminder_list"
    }


def test_stale_second_snapshot_rejects_entire_batch(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    _insert_action("first")
    _insert_action("second")
    snapshots = {action_id: _snapshot(action_id) for action_id in ("first", "second")}
    conn = state._get_conn()
    try:
        conn.execute(
            "UPDATE actions SET reminder_list = ? WHERE id = ?",
            ("Elsewhere", "second"),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(state.ReminderListBackfillConflictError) as exc_info:
        state.apply_reminder_list_backfill(
            [
                {"id": "first", "target_list": "Focus"},
                {"id": "second", "target_list": "Tasks"},
            ],
            snapshots=snapshots,
        )

    assert exc_info.value.action_ids == ["second"]
    assert str(exc_info.value) == "reminder list backfill action conflict: second"
    assert _action("first")["reminder_list"] is None
    assert _action("second")["reminder_list"] == "Elsewhere"


def test_sqlite_error_rolls_back_entire_batch(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    _insert_action("first")
    _insert_action("second")
    snapshots = {action_id: _snapshot(action_id) for action_id in ("first", "second")}
    conn = state._get_conn()
    try:
        conn.execute(
            """
            CREATE TRIGGER abort_second_backfill
            BEFORE UPDATE OF reminder_list ON actions
            WHEN OLD.id = 'second'
            BEGIN
                SELECT RAISE(ABORT, 'second backfill rejected');
            END
            """
        )
        conn.commit()
    finally:
        conn.close()

    try:
        with pytest.raises(sqlite3.IntegrityError, match="second backfill rejected"):
            state.apply_reminder_list_backfill(
                [
                    {"id": "first", "target_list": "Focus"},
                    {"id": "second", "target_list": "Tasks"},
                ],
                snapshots=snapshots,
            )
        assert _action("first")["reminder_list"] is None
        assert _action("second")["reminder_list"] is None
    finally:
        cleanup = state._get_conn()
        try:
            cleanup.execute("DROP TRIGGER IF EXISTS abort_second_backfill")
            cleanup.commit()
        finally:
            cleanup.close()


@pytest.mark.parametrize("target_list", ["", "   ", None, ["Focus"]])
def test_backfill_rejects_invalid_target_list_before_opening_transaction(
    monkeypatch, tmp_path, target_list
):
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        state,
        "_get_conn",
        lambda: pytest.fail("invalid input must not open a database connection"),
    )

    with pytest.raises(ValueError, match="target_list"):
        state.apply_reminder_list_backfill(
            [{"id": "first", "target_list": target_list}],
            snapshots={
                "first": {
                    "id": "first",
                    "type": "reminder",
                    "summary": "first",
                    "scheduled_at": None,
                    "status": "pending",
                    "reminder_list": None,
                }
            },
        )


@pytest.mark.parametrize(
    ("updates", "snapshots", "message"),
    [
        (None, {}, "updates"),
        ([], {}, "updates"),
        ({"id": "first"}, {}, "updates"),
        (["first"], {}, r"updates\[1\]"),
        ([{"id": "", "target_list": "Focus"}], {}, r"updates\[1\]\.id"),
        (
            [
                {"id": "first", "target_list": "Focus"},
                {"id": "first", "target_list": "Tasks"},
            ],
            {"first": _valid_snapshot()},
            r"updates\[2\]\.id",
        ),
        ([{"id": "first", "target_list": "Focus"}], None, "snapshots"),
        ([{"id": "first", "target_list": "Focus"}], [], "snapshots"),
        ([{"id": "first", "target_list": "Focus"}], {}, "snapshot"),
        (
            [{"id": "first", "target_list": "Focus"}],
            {"first": []},
            "snapshot",
        ),
    ],
)
def test_backfill_rejects_malformed_batch_before_opening_transaction(
    monkeypatch, tmp_path, updates, snapshots, message
):
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        state,
        "_get_conn",
        lambda: pytest.fail("invalid input must not open a database connection"),
    )

    with pytest.raises(ValueError, match=message):
        state.apply_reminder_list_backfill(updates, snapshots=snapshots)


@pytest.mark.parametrize("missing_field", SNAPSHOT_FIELDS)
def test_backfill_rejects_snapshot_missing_required_field_before_opening_transaction(
    monkeypatch, tmp_path, missing_field
):
    _isolate_state(monkeypatch, tmp_path)
    snapshot = _valid_snapshot()
    del snapshot[missing_field]
    monkeypatch.setattr(
        state,
        "_get_conn",
        lambda: pytest.fail("invalid input must not open a database connection"),
    )

    with pytest.raises(ValueError, match="snapshot"):
        state.apply_reminder_list_backfill(
            [{"id": "first", "target_list": "Focus"}],
            snapshots={"first": snapshot},
        )


@pytest.mark.parametrize("snapshot_id", ["second", 123, "", "   ", None])
def test_backfill_rejects_invalid_snapshot_id_before_opening_transaction(
    monkeypatch, tmp_path, snapshot_id
):
    _isolate_state(monkeypatch, tmp_path)
    snapshot = _valid_snapshot()
    snapshot["id"] = snapshot_id
    monkeypatch.setattr(
        state,
        "_get_conn",
        lambda: pytest.fail("invalid input must not open a database connection"),
    )

    with pytest.raises(ValueError, match="snapshot.*id"):
        state.apply_reminder_list_backfill(
            [{"id": "first", "target_list": "Focus"}],
            snapshots={"first": snapshot},
        )


def test_backfill_rejects_more_than_500_updates_before_validating_snapshots_or_opening_db(
    monkeypatch, tmp_path
):
    _isolate_state(monkeypatch, tmp_path)
    updates = [
        {"id": f"action-{index}", "target_list": "Focus"}
        for index in range(501)
    ]
    monkeypatch.setattr(
        state,
        "_get_conn",
        lambda: pytest.fail("oversized input must not open a database connection"),
    )

    with pytest.raises(ValueError, match="500"):
        state.apply_reminder_list_backfill(updates, snapshots={})
