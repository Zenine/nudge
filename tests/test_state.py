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
