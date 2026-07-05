"""Public-safe tests for SQLite state and daemon queue behavior."""

import contextlib
import sqlite3


def test_claim_next_queued_command_returns_none_if_selected_row_was_already_claimed(monkeypatch, tmp_path):
    """A worker must not return a command another worker claimed after its SELECT."""
    import nudge.state as state
    from nudge.state import claim_next_queued_command, enqueue_agent_command, list_queued_commands

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")

    enqueue_agent_command(
        payload={"request_id": "r-race", "actions": []},
        request_type="agent.apply",
        source="unit-test",
        request_id="r-race",
    )

    original_db = state._db
    race_triggered = {"value": False}

    class RacingConnection:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, params=()):
            result = self._conn.execute(sql, params)
            if (
                not race_triggered["value"]
                and "SELECT request_id, source, request_type, payload, queue_created_at" in sql
                and "WHERE status = 'queued'" in sql
            ):
                row = result.fetchone()
                assert row is not None
                race_triggered["value"] = True
                other = sqlite3.connect(str(state.DB_PATH))
                try:
                    other.execute(
                        """
                        UPDATE command_queue
                        SET status = 'running', attempts = attempts + 1, started_at = datetime('now', 'localtime')
                        WHERE request_id = ? AND status = 'queued'
                        """,
                        (row["request_id"],),
                    )
                    other.commit()
                finally:
                    other.close()

                class OneRowCursor:
                    def fetchone(self_nonlocal):
                        return row

                return OneRowCursor()
            return result

        def commit(self):
            return self._conn.commit()

        def close(self):
            return self._conn.close()

    @contextlib.contextmanager
    def racing_db():
        with original_db() as conn:
            yield RacingConnection(conn)

    monkeypatch.setattr(state, "_db", racing_db)

    assert claim_next_queued_command() is None
    running = list_queued_commands(status="running")
    assert [row["request_id"] for row in running] == ["r-race"]
    assert running[0]["attempts"] == 1


def test_sleep_auto_skip_updates_later_reminders_with_one_state_connection(monkeypatch, tmp_path):
    """Skipping later sleep reminders should query and update in one DB context."""
    import nudge.state as state
    from nudge.sleep_reminders import SLEEP_AFTER_SKIP_STATUS

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")
    monkeypatch.setattr(state, "_migrated", False)
    monkeypatch.setattr(state, "_schema_initialized_for", None)

    with state._db() as conn:
        conn.executemany(
            """
            INSERT INTO actions (id, type, summary, scheduled_at, completed_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("sleep-done", "reminder", "睡觉", "2026-07-05 22:30", "2026-07-05 22:35", "done"),
                ("later-sleep-1", "reminder", "该睡了", "2026-07-05 23:00", None, "created"),
                ("later-sleep-2", "reminder", "不要熬夜", "2026-07-06 00:15", None, "pending"),
                ("non-sleep", "reminder", "喝水", "2026-07-05 23:15", None, "created"),
                ("already-done", "reminder", "该去睡", "2026-07-05 23:30", None, "done"),
            ],
        )

    original_db = state._db
    db_entries = {"count": 0}

    @contextlib.contextmanager
    def counting_db():
        db_entries["count"] += 1
        with original_db() as conn:
            yield conn

    monkeypatch.setattr(state, "_db", counting_db)

    skipped = state.skip_later_sleep_reminders_after_completion("sleep-done")

    assert db_entries["count"] == 1
    assert [action["id"] for action in skipped] == ["later-sleep-1", "later-sleep-2"]

    rows = {action["id"]: action for action in state.get_actions()}
    assert rows["sleep-done"]["status"] == "done"
    assert rows["later-sleep-1"]["status"] == SLEEP_AFTER_SKIP_STATUS
    assert rows["later-sleep-2"]["status"] == SLEEP_AFTER_SKIP_STATUS
    assert rows["non-sleep"]["status"] == "created"
    assert rows["already-done"]["status"] == "done"
