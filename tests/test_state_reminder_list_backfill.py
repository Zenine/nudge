"""Tests for atomic SQLite reminder-list ownership backfill."""

import hashlib
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


def _directory_snapshot(directory):
    return {
        path.name: (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in directory.iterdir()
        if path.is_file()
    }


def _create_minimal_actions_database(db_path, *, journal_mode="DELETE"):
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA journal_mode={journal_mode}")
    conn.execute(
        """
        CREATE TABLE actions (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            summary TEXT NOT NULL,
            scheduled_at TEXT,
            completed_at TEXT,
            status TEXT,
            external_id TEXT,
            reminder_list TEXT,
            feedback TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO actions (
            id, type, summary, scheduled_at, status, reminder_list, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy", "reminder", "Buy milk", "2026-07-01 09:00",
            "pending", None, "2026-07-01 08:00",
        ),
    )
    conn.commit()
    return conn


def test_get_actions_readonly_missing_database_creates_nothing(monkeypatch, tmp_path):
    state_dir = tmp_path / "missing-state"
    _isolate_state(monkeypatch, state_dir)

    with pytest.raises(sqlite3.OperationalError):
        state.get_actions_readonly()

    assert not state_dir.exists()
    assert not (state_dir / "nudge.db").exists()
    assert not (state_dir / "state.json").exists()


def test_get_actions_readonly_preserves_database_files_and_legacy_json(monkeypatch, tmp_path):
    state_dir = tmp_path / "readonly-state"
    state_dir.mkdir()
    db_path = state_dir / "nudge.db"
    legacy_path = state_dir / "state.json"
    legacy_contents = '{"habits": {"private": {"streak": 1}}}'
    legacy_path.write_text(legacy_contents, encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE actions (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                summary TEXT NOT NULL,
                scheduled_at TEXT,
                completed_at TEXT,
                status TEXT,
                external_id TEXT,
                reminder_list TEXT,
                feedback TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO actions (
                id, type, summary, scheduled_at, status, reminder_list, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy", "reminder", "Buy milk", "2026-07-01 09:00",
                "pending", None, "2026-07-01 08:00",
            ),
        )
    _isolate_state(monkeypatch, state_dir)
    before_files = {path.name for path in state_dir.iterdir()}
    before_mtime = db_path.stat().st_mtime_ns

    actions = state.get_actions_readonly()

    assert actions == [{
        "id": "legacy",
        "type": "reminder",
        "summary": "Buy milk",
        "scheduled_at": "2026-07-01 09:00",
        "status": "pending",
        "reminder_list": None,
    }]
    assert db_path.stat().st_mtime_ns == before_mtime
    assert {path.name for path in state_dir.iterdir()} == before_files
    assert legacy_path.read_text(encoding="utf-8") == legacy_contents
    assert not (state_dir / "state.json.bak").exists()


def test_get_actions_readonly_checkpointed_wal_database_changes_no_files(monkeypatch, tmp_path):
    state_dir = tmp_path / "wal-checkpointed"
    state_dir.mkdir()
    db_path = state_dir / "nudge.db"
    conn = _create_minimal_actions_database(db_path, journal_mode="WAL")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    _isolate_state(monkeypatch, state_dir)
    before = _directory_snapshot(state_dir)

    actions = state.get_actions_readonly()

    assert [action["id"] for action in actions] == ["legacy"]
    assert _directory_snapshot(state_dir) == before
    assert not (state_dir / "nudge.db-wal").exists()
    assert not (state_dir / "nudge.db-shm").exists()


def test_get_actions_readonly_rejects_nonempty_wal_without_touching_files(monkeypatch, tmp_path):
    state_dir = tmp_path / "wal-pending"
    state_dir.mkdir()
    db_path = state_dir / "nudge.db"
    writer = _create_minimal_actions_database(db_path, journal_mode="WAL")
    writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    writer.execute(
        "INSERT INTO actions (id, type, summary, created_at) VALUES (?, ?, ?, ?)",
        ("uncheckpointed", "reminder", "Pending WAL", "2026-07-02 08:00"),
    )
    writer.commit()
    wal_path = state_dir / "nudge.db-wal"
    assert wal_path.exists() and wal_path.stat().st_size > 0
    _isolate_state(monkeypatch, state_dir)
    before = _directory_snapshot(state_dir)

    try:
        with pytest.raises(sqlite3.OperationalError, match="non-empty WAL"):
            state.get_actions_readonly()
        assert _directory_snapshot(state_dir) == before
    finally:
        writer.close()


def test_get_actions_readonly_rejects_nonempty_rollback_journal_without_recovery(monkeypatch, tmp_path):
    state_dir = tmp_path / "rollback-pending"
    state_dir.mkdir()
    db_path = state_dir / "nudge.db"
    _create_minimal_actions_database(db_path).close()
    journal_path = state_dir / "nudge.db-journal"
    journal_path.write_bytes(b"simulated hot rollback journal")
    _isolate_state(monkeypatch, state_dir)
    before = _directory_snapshot(state_dir)

    with pytest.raises(sqlite3.OperationalError, match="non-empty rollback journal"):
        state.get_actions_readonly()

    assert _directory_snapshot(state_dir) == before


def test_get_actions_readonly_rejects_rollback_journal_change_during_read(monkeypatch, tmp_path):
    state_dir = tmp_path / "rollback-changed"
    state_dir.mkdir()
    db_path = state_dir / "nudge.db"
    _create_minimal_actions_database(db_path).close()
    journal_path = state_dir / "nudge.db-journal"
    journal_path.touch()
    _isolate_state(monkeypatch, state_dir)
    original_optional_identity = state._readonly_optional_identity
    journal_identity = original_optional_identity(journal_path)
    changed_journal_identity = (*journal_identity[:-1], journal_identity[-1] + 1)
    journal_calls = 0

    def changing_optional_identity(path):
        nonlocal journal_calls
        if path == journal_path:
            journal_calls += 1
            return journal_identity if journal_calls == 1 else changed_journal_identity
        return original_optional_identity(path)

    monkeypatch.setattr(state, "_readonly_optional_identity", changing_optional_identity)

    with pytest.raises(sqlite3.OperationalError, match="changed"):
        state.get_actions_readonly()

    assert journal_calls == 2


def test_get_actions_readonly_rejects_database_change_during_read(monkeypatch, tmp_path):
    state_dir = tmp_path / "changed-during-read"
    state_dir.mkdir()
    db_path = state_dir / "nudge.db"
    _create_minimal_actions_database(db_path).close()
    _isolate_state(monkeypatch, state_dir)
    stat_result = db_path.stat()
    original = (
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_size,
        stat_result.st_mtime_ns,
    )
    changed = (*original[:-1], original[-1] + 1)
    identities = iter((original, changed))
    calls = []

    def changing_identity(path):
        calls.append(path)
        return next(identities)

    monkeypatch.setattr(state, "_readonly_db_identity", changing_identity, raising=False)

    with pytest.raises(sqlite3.OperationalError, match="changed"):
        state.get_actions_readonly()

    assert calls == [db_path, db_path]


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


@pytest.mark.parametrize("outcome", ["success", "conflict", "write_error"])
def test_backfill_existing_write_never_initializes_or_migrates_legacy_state(
    monkeypatch,
    tmp_path,
    outcome,
):
    state_dir = tmp_path / "legacy-state"
    state_dir.mkdir()
    db_path = state_dir / "nudge.db"
    legacy_path = state_dir / "state.json"
    legacy_contents = (
        '{"habits":{"private-habit":{"last_logged":"2026-07-18","streak":7}}}'
    )
    legacy_path.write_text(legacy_contents, encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE actions (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                summary TEXT NOT NULL,
                scheduled_at TEXT,
                completed_at TEXT,
                status TEXT,
                external_id TEXT,
                reminder_list TEXT,
                feedback TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO actions (
                id, type, summary, scheduled_at, status, reminder_list, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy", "reminder", "Buy milk", "2026-07-01 09:00",
                "pending", None, "2026-07-01 08:00",
            ),
        )
        if outcome == "write_error":
            conn.execute(
                """
                CREATE TRIGGER abort_legacy_backfill
                BEFORE UPDATE OF reminder_list ON actions
                BEGIN
                    SELECT RAISE(ABORT, 'legacy backfill rejected');
                END
                """
            )
    _isolate_state(monkeypatch, state_dir)
    snapshot = {
        "id": "legacy",
        "type": "reminder",
        "summary": "Stale title" if outcome == "conflict" else "Buy milk",
        "scheduled_at": "2026-07-01 09:00",
        "status": "pending",
        "reminder_list": None,
    }

    if outcome == "conflict":
        with pytest.raises(state.ReminderListBackfillConflictError):
            state.apply_reminder_list_backfill(
                [{"id": "legacy", "target_list": "Tasks"}],
                snapshots={"legacy": snapshot},
            )
    elif outcome == "write_error":
        with pytest.raises(sqlite3.IntegrityError, match="legacy backfill rejected"):
            state.apply_reminder_list_backfill(
                [{"id": "legacy", "target_list": "Tasks"}],
                snapshots={"legacy": snapshot},
            )
    else:
        assert state.apply_reminder_list_backfill(
            [{"id": "legacy", "target_list": "Tasks"}],
            snapshots={"legacy": snapshot},
        ) == ["legacy"]

    assert legacy_path.read_text(encoding="utf-8") == legacy_contents
    assert not (state_dir / "state.json.bak").exists()
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        reminder_list = conn.execute(
            "SELECT reminder_list FROM actions WHERE id = 'legacy'"
        ).fetchone()[0]
    assert "habit_logs" not in tables
    assert "state_migrations" not in tables
    assert reminder_list == ("Tasks" if outcome == "success" else None)


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
