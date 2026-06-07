"""State persistence tests that use isolated temporary SQLite files."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

import nudge.state as state


@pytest.fixture(autouse=True)
def isolated_state_db(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")
    monkeypatch.setattr(state, "_migrated", False)


def _queue_row(request_id: str) -> dict:
    rows = state.list_queued_commands(status=None)
    for row in rows:
        if row["request_id"] == request_id:
            return row
    raise AssertionError(f"missing queue row: {request_id}")


def _set_queue_row(request_id: str, **fields) -> None:
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with state._db() as conn:
        conn.execute(
            f"UPDATE command_queue SET {assignments} WHERE request_id = ?",
            [*fields.values(), request_id],
        )


def test_action_log_status_and_external_id_updates_round_trip():
    action_id = state.log_action(
        action_type="reminder",
        summary="提交日报",
        scheduled_at="2026-06-07 18:00",
        status="pending",
    )

    state.update_action_external_id(action_id, "reminders://abc")
    state.update_action_status(action_id, "blocked", feedback={"reason": "等待确认"})

    action = state.get_action(action_id)
    assert action is not None
    assert action["type"] == "reminder"
    assert action["summary"] == "提交日报"
    assert action["scheduled_at"] == "2026-06-07 18:00"
    assert action["status"] == "blocked"
    assert action["external_id"] == "reminders://abc"
    assert json.loads(action["feedback"]) == {"reason": "等待确认"}


def test_complete_skip_and_partial_action_statuses_persist_feedback():
    done_id = state.log_action("reminder", "完成复盘")
    skipped_id = state.log_action("reminder", "作废提醒")
    partial_id = state.log_action("reminder", "整理草稿")

    state.complete_action(done_id, feedback={"source": "test"}, completed_at="2026-06-07 10:00")
    state.skip_action(skipped_id, feedback={"reason": "过期作废"})
    state.partial_action(partial_id, feedback={"progress": "一半"}, completed_at="2026-06-07 11:00")

    done = state.get_action(done_id)
    skipped = state.get_action(skipped_id)
    partial = state.get_action(partial_id)

    assert done["status"] == "done"
    assert done["completed_at"] == "2026-06-07 10:00"
    assert json.loads(done["feedback"]) == {"source": "test"}
    assert skipped["status"] == "skipped"
    assert json.loads(skipped["feedback"]) == {"reason": "过期作废"}
    assert partial["status"] == "partial"
    assert partial["completed_at"] == "2026-06-07 11:00"
    assert json.loads(partial["feedback"]) == {"progress": "一半"}


def test_queue_claim_returns_oldest_payload_and_marks_running():
    newer_id = state.enqueue_agent_command(
        request_id="newer",
        source="mcp",
        request_type="agent.apply",
        payload={"summary": "newer"},
    )
    older_id = state.enqueue_agent_command(
        request_id="older",
        source="cli",
        request_type="agent.apply",
        payload={"summary": "older"},
    )
    _set_queue_row(newer_id, queue_created_at="2026-06-07 10:01:00")
    _set_queue_row(older_id, queue_created_at="2026-06-07 10:00:00")

    claimed = state.claim_next_queued_command()

    assert claimed["request_id"] == "older"
    assert claimed["source"] == "cli"
    assert claimed["payload"] == {"summary": "older"}
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1
    assert _queue_row("older")["status"] == "running"
    assert _queue_row("newer")["status"] == "queued"


def test_stale_recovery_requeues_running_below_retry_ceiling_and_dead_letters_exhausted():
    requeue_id = state.enqueue_agent_command(request_id="retry-me", payload={"n": 1})
    dead_id = state.enqueue_agent_command(request_id="dead-me", payload={"n": 2})
    old_started = (datetime.now() - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S")
    _set_queue_row(requeue_id, status="running", attempts=1, started_at=old_started)
    _set_queue_row(dead_id, status="running", attempts=3, started_at=old_started)

    result = state.recover_stale_running_commands(stale_minutes=30, max_attempts=3)

    assert result["scanned_count"] == 2
    assert result["requeued_count"] == 1
    assert result["dead_lettered_count"] == 1
    requeued = _queue_row(requeue_id)
    dead_lettered = _queue_row(dead_id)
    assert requeued["status"] == "queued"
    assert requeued["started_at"] is None
    assert "stale running command recovered" in requeued["last_error"]
    assert dead_lettered["status"] == "dead_letter"
    assert dead_lettered["last_exit_code"] == 1
    assert "stale running command recovered" in dead_lettered["last_error"]


def test_retry_moves_failed_and_dead_letter_back_to_queued():
    failed_id = state.enqueue_agent_command(request_id="failed", payload={"n": 1})
    dead_id = state.enqueue_agent_command(request_id="dead", payload={"n": 2})
    queued_id = state.enqueue_agent_command(request_id="already-queued", payload={"n": 3})
    _set_queue_row(
        failed_id,
        status="failed",
        attempts=2,
        started_at="2026-06-07 10:00:00",
        finished_at="2026-06-07 10:01:00",
        last_error="boom",
        last_exit_code=1,
        last_duration_ms=500,
        command_id="cmd-failed",
    )
    _set_queue_row(
        dead_id,
        status="dead_letter",
        attempts=3,
        started_at="2026-06-07 10:00:00",
        finished_at="2026-06-07 10:01:00",
        last_error="exhausted",
        last_exit_code=1,
        last_duration_ms=700,
        command_id="cmd-dead",
    )

    retried_failed = state.retry_queued_command(failed_id)
    retried_dead = state.retry_queued_command(dead_id)
    unchanged = state.retry_queued_command(queued_id)

    assert retried_failed["status"] == "queued"
    assert retried_dead["status"] == "queued"
    assert unchanged is None
    for request_id in (failed_id, dead_id):
        row = _queue_row(request_id)
        assert row["attempts"] == 0
        assert row["started_at"] is None
        assert row["finished_at"] is None
        assert row["last_error"] is None
        assert row["last_exit_code"] is None
        assert row["last_duration_ms"] is None
        assert row["command_id"] is None


def test_queue_completion_rejects_unknown_status():
    request_id = state.enqueue_agent_command(request_id="bad-status", payload={"n": 1})
    state.claim_next_queued_command()

    with pytest.raises(ValueError, match="invalid queue status"):
        state.mark_queued_command_complete(request_id, status="not-a-real-status")
