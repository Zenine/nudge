"""Tests for nudge.state module (SQLite-based)."""

import contextlib
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest


def test_default_state_dir_refuses_implicit_fallback(monkeypatch):
    """缺配置时必须显式报错，不得静默回退到源码树 .nudge/。

    成因：静默回退会让漏传 --config 的命令打开或新建一个空库，并对「某条提醒
    是否存在 / 状态是什么 / external_id 是多少」给出自信但错误的答案。本测试
    此前断言的正是那个回退行为。
    """
    from nudge.config import StateDirNotConfiguredError
    from nudge.state import _default_state_dir

    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)

    with pytest.raises(StateDirNotConfiguredError) as excinfo:
        _default_state_dir({})

    message = str(excinfo.value)
    assert "NUDGE_STATE_DIR" in message
    assert "[state].dir" in message
    assert "--config" in message


def test_default_state_dir_can_be_overridden(monkeypatch, tmp_path):
    from nudge.state import _default_state_dir

    custom_dir = tmp_path / "custom-state"
    monkeypatch.setenv("NUDGE_STATE_DIR", str(custom_dir))

    assert _default_state_dir() == custom_dir


def test_default_state_dir_can_use_config(monkeypatch, tmp_path):
    from nudge.state import _default_state_dir

    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)

    assert _default_state_dir({"state": {"dir": str(tmp_path / "configured-state")}}) == tmp_path / "configured-state"


@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    """Redirect all DB operations to a temp directory."""
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.state.LEGACY_JSON", tmp_path / "state.json")


# ── Habit tracking ──────────────────────────────────────────────

def test_update_habit_new():
    from nudge.state import get_habit_streaks, update_habit

    update_habit("exercise")
    streaks = get_habit_streaks()
    assert streaks["exercise"]["streak"] == 1
    assert streaks["exercise"]["last_logged"] == date.today().isoformat()

def test_update_habit_duplicate_same_day():
    from nudge.state import get_habit_streaks, update_habit

    update_habit("exercise")
    update_habit("exercise")
    streaks = get_habit_streaks()
    assert streaks["exercise"]["streak"] == 1

def test_update_habit_consecutive_days(tmp_path):
    from nudge.state import _get_conn, get_habit_streaks, update_habit

    # Manually insert yesterday's record
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO habit_logs (habit_name, date, completed, streak) VALUES (?, ?, 1, 5)",
        ("exercise", yesterday),
    )
    conn.commit()
    conn.close()

    update_habit("exercise")
    streaks = get_habit_streaks()
    assert streaks["exercise"]["streak"] == 6

def test_update_habit_streak_broken(tmp_path):
    from nudge.state import _get_conn, get_habit_streaks, update_habit

    two_days_ago = (date.today() - timedelta(days=2)).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO habit_logs (habit_name, date, completed, streak) VALUES (?, ?, 1, 5)",
        ("exercise", two_days_ago),
    )
    conn.commit()
    conn.close()

    update_habit("exercise")
    streaks = get_habit_streaks()
    assert streaks["exercise"]["streak"] == 1

def test_update_habit_with_notes():
    from nudge.state import update_habit, _get_conn

    update_habit("exercise", notes="ran 5km")
    conn = _get_conn()
    row = conn.execute("SELECT notes FROM habit_logs WHERE habit_name = 'exercise'").fetchone()
    conn.close()
    assert row["notes"] == "ran 5km"

def test_get_habit_streaks_empty():
    from nudge.state import get_habit_streaks

    assert get_habit_streaks() == {}


# ── Action logging ──────────────────────────────────────────────

def test_log_action():
    from nudge.state import get_actions, log_action

    action_id = log_action(
        action_type="calendar_event",
        summary="Team meeting",
        scheduled_at="2026-04-14 15:00",
    )
    assert len(action_id) == 12

    actions = get_actions()
    assert len(actions) == 1
    assert actions[0]["summary"] == "Team meeting"
    assert actions[0]["status"] == "created"

def test_complete_action():
    from nudge.state import complete_action, get_actions, log_action

    action_id = log_action("reminder", "Buy milk", "2026-04-14 18:00")
    complete_action(action_id, feedback={"effort": 3})

    actions = get_actions(status="done")
    assert len(actions) == 1
    assert actions[0]["completed_at"] is not None
    assert '"effort": 3' in actions[0]["feedback"]

def test_complete_action_uses_provided_completed_at():
    from nudge.state import complete_action, get_action, log_action

    action_id = log_action("reminder", "称重", "2026-04-27 06:40")

    complete_action(
        action_id,
        feedback={"source": "test"},
        completed_at="2026-04-27 06:43",
    )

    action = get_action(action_id)
    assert action["status"] == "done"
    assert action["completed_at"] == "2026-04-27 06:43"

def test_skip_action():
    from nudge.state import get_actions, log_action, skip_action

    action_id = log_action("calendar_event", "Workout", "2026-04-14 07:00")
    skip_action(action_id)

    actions = get_actions(status="skipped")
    assert len(actions) == 1

def test_skip_action_can_record_feedback():
    from nudge.state import get_actions, log_action, skip_action

    action_id = log_action("calendar_event", "Workout", "2026-04-14 07:00")
    skip_action(action_id, feedback={"note": "临时有事"})

    actions = get_actions(status="skipped")
    assert '"note": "临时有事"' in actions[0]["feedback"]

def test_partial_action_records_feedback_and_timestamp():
    from nudge.state import get_actions, log_action, partial_action

    action_id = log_action("calendar_event", "Read chapter 1", "2026-04-14 21:00")
    partial_action(action_id, feedback={"note": "只读了一半"})

    actions = get_actions(status="partial")
    assert len(actions) == 1
    assert actions[0]["completed_at"] is not None
    assert '"note": "只读了一半"' in actions[0]["feedback"]

def test_partial_action_uses_provided_completed_at():
    from nudge.state import get_action, log_action, partial_action

    action_id = log_action("reminder", "快走", "2026-04-27 18:30")

    partial_action(
        action_id,
        feedback={"source": "test"},
        completed_at="2026-04-27 18:42",
    )

    action = get_action(action_id)
    assert action["status"] == "partial"
    assert action["completed_at"] == "2026-04-27 18:42"

def test_update_action_status_records_history_feedback():
    from nudge.state import get_actions, log_action, update_action_status

    action_id = log_action("calendar_event", "Read chapter 1", "2026-04-14 21:00")
    update_action_status(action_id, "adapted", feedback={"reason": "moved earlier"})

    actions = get_actions(status="adapted")
    assert len(actions) == 1
    assert '"reason": "moved earlier"' in actions[0]["feedback"]


def test_feedback_interview_batch_applies_all_updates_atomically(monkeypatch, tmp_path):
    import json

    from nudge.state import apply_feedback_interview_batch, get_action, log_action

    action_a = log_action("reminder", "任务 A", "2026-07-19 08:00")
    action_b = log_action("reminder", "任务 B", "2026-07-19 09:00")
    snapshots = {action_id: get_action(action_id) for action_id in (action_a, action_b)}

    apply_feedback_interview_batch(
        [
            {
                "id": action_a,
                "status": "done",
                "completed_at": "2026-07-19 12:00",
                "feedback": {"schema_version": "nudge.feedback.v1", "channel": "cli.feedback.interview"},
            },
            {
                "id": action_b,
                "status": "created",
                "completed_at": None,
                "feedback": {
                    "schema_version": "nudge.feedback.v1",
                    "channel": "cli.feedback.interview",
                    "interview": {"resolution": "unconfirmed"},
                },
            },
        ],
        snapshots=snapshots,
    )

    assert get_action(action_a)["status"] == "done"
    assert get_action(action_a)["completed_at"] == "2026-07-19 12:00"
    assert get_action(action_b)["status"] == "created"
    assert get_action(action_b)["completed_at"] is None
    assert json.loads(get_action(action_b)["feedback"])["interview"]["resolution"] == "unconfirmed"


def test_feedback_interview_batch_rolls_back_everything_on_snapshot_conflict(monkeypatch, tmp_path):
    from nudge.state import (
        FeedbackInterviewConflictError,
        apply_feedback_interview_batch,
        get_action,
        log_action,
        update_action_status,
    )

    action_a = log_action("reminder", "任务 A", "2026-07-19 08:00")
    action_b = log_action("reminder", "任务 B", "2026-07-19 09:00")
    snapshots = {action_id: get_action(action_id) for action_id in (action_a, action_b)}
    update_action_status(action_b, "blocked", feedback={"reason": "changed elsewhere"})

    with pytest.raises(FeedbackInterviewConflictError) as exc_info:
        apply_feedback_interview_batch(
            [
                {"id": action_a, "status": "done", "completed_at": "2026-07-19 12:00", "feedback": {}},
                {"id": action_b, "status": "done", "completed_at": "2026-07-19 12:00", "feedback": {}},
            ],
            snapshots=snapshots,
        )

    assert exc_info.value.action_ids == [action_b]
    assert get_action(action_a)["status"] == "created"
    assert get_action(action_b)["status"] == "blocked"


def test_feedback_interview_batch_rolls_back_when_second_update_fails(monkeypatch, tmp_path):
    import sqlite3

    import nudge.state as state
    from nudge.state import apply_feedback_interview_batch, get_action, log_action

    action_a = log_action("reminder", "任务 A", "2026-07-19 08:00")
    action_b = log_action("reminder", "任务 B", "2026-07-19 09:00")
    snapshots = {action_id: get_action(action_id) for action_id in (action_a, action_b)}
    original_get_conn = state._get_conn
    raw_conn = original_get_conn()

    class FailingConnection:
        def __init__(self, conn):
            self.conn = conn
            self.update_count = 0

        def execute(self, sql, params=()):
            if sql.lstrip().upper().startswith("UPDATE ACTIONS"):
                self.update_count += 1
                if self.update_count == 2:
                    raise sqlite3.OperationalError("simulated second update failure")
            return self.conn.execute(sql, params)

        def commit(self):
            return self.conn.commit()

        def rollback(self):
            return self.conn.rollback()

        def close(self):
            return self.conn.close()

    monkeypatch.setattr(state, "_get_conn", lambda: FailingConnection(raw_conn))
    with pytest.raises(sqlite3.OperationalError, match="second update failure"):
        apply_feedback_interview_batch(
            [
                {"id": action_a, "status": "done", "completed_at": "2026-07-19 12:00", "feedback": {}},
                {"id": action_b, "status": "done", "completed_at": "2026-07-19 12:00", "feedback": {}},
            ],
            snapshots=snapshots,
        )
    monkeypatch.setattr(state, "_get_conn", original_get_conn)

    assert get_action(action_a)["status"] == "created"
    assert get_action(action_b)["status"] == "created"


def test_feedback_interview_batch_rejects_non_json_feedback_before_writing(monkeypatch, tmp_path):
    from nudge.state import apply_feedback_interview_batch, get_action, log_action

    action_id = log_action("reminder", "任务 A", "2026-07-19 08:00")
    snapshot = get_action(action_id)

    with pytest.raises(ValueError, match="JSON serializable"):
        apply_feedback_interview_batch(
            [{
                "id": action_id,
                "status": "done",
                "completed_at": "2026-07-19 12:00",
                "feedback": {"bad": {object()}},
            }],
            snapshots={action_id: snapshot},
        )

    assert get_action(action_id)["status"] == "created"

def test_get_actions_filters():
    from nudge.state import get_actions, log_action

    log_action("calendar_event", "Event A", status="created")
    log_action("reminder", "Reminder B", status="created")

    all_actions = get_actions()
    assert len(all_actions) == 2

    only_created = get_actions(status="created")
    assert len(only_created) == 2

    only_done = get_actions(status="done")
    assert len(only_done) == 0

def test_get_actions_since_uses_scheduled_or_completed_time_for_periods():
    from nudge.state import _get_conn, get_actions

    conn = _get_conn()
    rows = [
        ("old-created-this-week", "calendar_event", "本周执行", "2026-04-28 09:00", None, "created", "2026-04-01 10:00:00"),
        ("future-created-this-week", "calendar_event", "未来执行", "2026-05-05 09:00", None, "created", "2026-04-28 10:00:00"),
        ("old-scheduled-done-this-week", "calendar_event", "本周补记", "2026-04-10 09:00", "2026-04-29 20:00", "done", "2026-04-01 10:00:00"),
        ("created-only-this-week", "note", "无计划时间", None, None, "created", "2026-04-29 10:00:00"),
    ]
    conn.executemany(
        "INSERT INTO actions (id, type, summary, scheduled_at, completed_at, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()

    actions = get_actions(since="2026-04-27", until="2026-05-04")

    summaries = {action["summary"] for action in actions}
    assert summaries == {"本周执行", "本周补记", "无计划时间"}


# ── Plan management ─────────────────────────────────────────────

def test_create_plan():
    from nudge.state import create_plan, get_plans

    plan_id = create_plan("Run 3x per week", config={"days": ["mon", "wed", "fri"]})
    assert len(plan_id) == 12

    plans = get_plans()
    assert len(plans) == 1
    assert plans[0]["goal"] == "Run 3x per week"
    assert plans[0]["status"] == "active"

def test_get_plans_empty():
    from nudge.state import get_plans

    assert get_plans() == []


# ── Legacy compat ───────────────────────────────────────────────

def test_load_state_compat():
    from nudge.state import load_state, update_habit

    update_habit("reading")
    state = load_state()
    assert "habits" in state
    assert state["habits"]["reading"]["streak"] == 1

def test_save_state_compat():
    from nudge.state import get_habit_streaks, save_state

    save_state({
        "habits": {
            "meditation": {"streak": 3, "last_logged": "2026-04-13"}
        }
    })
    streaks = get_habit_streaks()
    assert streaks["meditation"]["streak"] == 3


# ── JSON migration ──────────────────────────────────────────────

def test_migrate_from_json(tmp_path):
    import json
    from nudge.state import _migrate_from_json, get_habit_streaks, DB_PATH

    # Write a legacy state.json
    legacy = tmp_path / "state.json"
    legacy.write_text(json.dumps({
        "habits": {
            "exercise": {"streak": 7, "last_logged": "2026-04-12"},
            "reading": {"streak": 3, "last_logged": "2026-04-11"},
        }
    }))

    _migrate_from_json()

    streaks = get_habit_streaks()
    assert streaks["exercise"]["streak"] == 7
    assert streaks["reading"]["streak"] == 3

    # Legacy file should be renamed to .bak
    assert not legacy.exists()
    assert (tmp_path / "state.json.bak").exists()

def test_migrate_skips_if_already_migrated(tmp_path):
    import json
    from nudge.state import _get_conn, _migrate_from_json

    # Pre-populate DB
    conn = _get_conn()
    conn.execute(
        "INSERT INTO habit_logs (habit_name, date, completed, streak) VALUES ('x', '2026-01-01', 1, 1)"
    )
    conn.commit()
    conn.close()

    # Write a legacy file
    legacy = tmp_path / "state.json"
    legacy.write_text(json.dumps({"habits": {"y": {"streak": 5, "last_logged": "2026-04-12"}}}))

    _migrate_from_json()

    # Legacy file should NOT be renamed (migration skipped)
    assert legacy.exists()

def test_migrate_handles_corrupted_json(tmp_path):
    from nudge.state import _migrate_from_json

    legacy = tmp_path / "state.json"
    legacy.write_text("{invalid json")

    # Should not crash
    _migrate_from_json()
    assert legacy.exists()  # not renamed since migration failed

def test_enqueue_and_claim_command_queue(tmp_path):
    from nudge.state import (
        claim_next_queued_command,
        enqueue_agent_command,
        get_daemon_runtime_status,
        list_queued_commands,
        mark_queued_command_complete,
    )

    enqueue_agent_command(
        payload={"request_id": "r1", "actions": []},
        request_type="agent.apply",
        source="unit-test",
        request_id="r1",
    )
    enqueue_agent_command(
        payload={"request_id": "r2", "actions": []},
        request_type="agent.apply",
        source="unit-test",
        request_id="r2",
    )

    queued = list_queued_commands(status="queued", limit=10)
    assert [row["request_id"] for row in queued] == ["r1", "r2"]

    first = claim_next_queued_command()
    assert first is not None
    assert first["request_id"] == "r1"
    assert first["status"] == "running"

    mark_queued_command_complete(request_id="r1", status="succeeded", exit_code=0, duration_ms=12)

    status = get_daemon_runtime_status()
    assert status["queued"] == 1
    assert status["succeeded"] == 1
    assert status["running"] == 0


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


def test_enqueue_command_rejects_active_queue_over_capacity(tmp_path):
    from nudge.state import enqueue_agent_command

    enqueue_agent_command(
        payload={"request_id": "r1", "actions": []},
        request_type="agent.apply",
        source="unit-test",
        request_id="r1",
        max_queue_depth=1,
    )

    with pytest.raises(ValueError, match="command queue is full"):
        enqueue_agent_command(
            payload={"request_id": "r2", "actions": []},
            request_type="agent.apply",
            source="unit-test",
            request_id="r2",
            max_queue_depth=1,
        )

def test_recover_stale_running_commands_requeues_and_dead_letters(tmp_path):
    from nudge.state import (
        _get_conn,
        claim_next_queued_command,
        enqueue_agent_command,
        get_daemon_runtime_status,
        list_queued_commands,
        recover_stale_running_commands,
    )

    enqueue_agent_command(
        payload={"request_id": "r-retry", "actions": []},
        request_type="agent.apply",
        source="unit-test",
        request_id="r-retry",
    )
    enqueue_agent_command(
        payload={"request_id": "r-dead", "actions": []},
        request_type="agent.apply",
        source="unit-test",
        request_id="r-dead",
    )
    assert claim_next_queued_command()["request_id"] == "r-retry"
    assert claim_next_queued_command()["request_id"] == "r-dead"

    old_started_at = "2026-04-27 09:00:00"
    conn = _get_conn()
    conn.execute(
        """
        UPDATE command_queue
        SET started_at = ?,
            attempts = CASE request_id WHEN 'r-dead' THEN 3 ELSE attempts END
        WHERE request_id IN ('r-retry', 'r-dead')
        """,
        (old_started_at,),
    )
    conn.commit()
    conn.close()

    summary = recover_stale_running_commands(stale_minutes=10, max_attempts=3)

    assert summary["requeued_count"] == 1
    assert summary["dead_lettered_count"] == 1
    assert [item["request_id"] for item in summary["requeued"]] == ["r-retry"]
    assert [item["request_id"] for item in summary["dead_lettered"]] == ["r-dead"]

    queued = list_queued_commands(status="queued")
    assert [row["request_id"] for row in queued] == ["r-retry"]

    dead_letters = list_queued_commands(status="dead_letter")
    assert len(dead_letters) == 1
    assert dead_letters[0]["request_id"] == "r-dead"
    assert "stale running command" in dead_letters[0]["last_error"]

    runtime_status = get_daemon_runtime_status()
    assert runtime_status["queued"] == 1
    assert runtime_status["running"] == 0
    assert runtime_status["dead_letter"] == 1

def test_list_stale_running_commands_marks_exhausted_items(tmp_path):
    from nudge.state import (
        _get_conn,
        claim_next_queued_command,
        enqueue_agent_command,
        list_stale_running_commands,
    )

    enqueue_agent_command(
        payload={"request_id": "r-fresh", "actions": []},
        request_type="agent.apply",
        source="unit-test",
        request_id="r-fresh",
    )
    enqueue_agent_command(
        payload={"request_id": "r-stale", "actions": []},
        request_type="agent.apply",
        source="unit-test",
        request_id="r-stale",
    )
    enqueue_agent_command(
        payload={"request_id": "r-exhausted", "actions": []},
        request_type="agent.apply",
        source="unit-test",
        request_id="r-exhausted",
    )
    assert claim_next_queued_command()["request_id"] == "r-fresh"
    assert claim_next_queued_command()["request_id"] == "r-stale"
    assert claim_next_queued_command()["request_id"] == "r-exhausted"

    conn = _get_conn()
    conn.execute(
        """
        UPDATE command_queue
        SET started_at = CASE request_id
                WHEN 'r-fresh' THEN datetime('now', 'localtime')
                ELSE '2026-04-27 09:00:00'
            END,
            attempts = CASE request_id
                WHEN 'r-exhausted' THEN 3
                ELSE attempts
            END
        WHERE request_id IN ('r-fresh', 'r-stale', 'r-exhausted')
        """
    )
    conn.commit()
    conn.close()

    stale = list_stale_running_commands(stale_minutes=10, max_attempts=3)

    assert [row["request_id"] for row in stale] == ["r-stale", "r-exhausted"]
    exhausted = {row["request_id"]: row["will_dead_letter"] for row in stale}
    assert exhausted == {"r-stale": False, "r-exhausted": True}

def test_retry_queued_command_requeues_dead_letter_and_resets_attempts(tmp_path):
    from nudge.state import _get_conn, enqueue_agent_command, list_queued_commands, retry_queued_command

    enqueue_agent_command(
        payload={"request_id": "r-replay", "actions": []},
        request_type="agent.apply",
        source="unit-test",
        request_id="r-replay",
    )
    conn = _get_conn()
    conn.execute(
        """
        UPDATE command_queue
        SET status = 'dead_letter',
            attempts = 3,
            started_at = '2026-04-27 09:00:00',
            finished_at = '2026-04-27 09:30:00',
            last_error = 'too many stale attempts',
            last_exit_code = 1
        WHERE request_id = 'r-replay'
        """
    )
    conn.commit()
    conn.close()

    retried = retry_queued_command("r-replay")

    assert retried is not None
    assert retried["request_id"] == "r-replay"
    assert retried["status"] == "queued"
    assert retried["attempts"] == 0
    assert retried["last_error"] is None
    assert retried["started_at"] is None
    assert retried["finished_at"] is None

    queued = list_queued_commands(status="queued")
    assert [row["request_id"] for row in queued] == ["r-replay"]

def test_complete_sleep_action_auto_skips_later_sleep_reminders_same_day():
    from nudge.state import complete_action, get_actions, log_action
    from nudge.sleep_reminders import SLEEP_AFTER_SKIP_STATUS

    earlier_id = log_action("reminder", "21:30 开始收尾", "2026-04-27 21:30")
    sleep_id = log_action("reminder", "22:30 睡觉", "2026-04-27 22:30")
    later_sleep_id = log_action("reminder", "不要熬夜", "2026-04-27 23:00")
    later_sleep_again_id = log_action("reminder", "真的该睡了", "2026-04-27 23:30")
    later_non_sleep_id = log_action("reminder", "吃药", "2026-04-27 23:15")
    next_day_sleep_id = log_action("reminder", "睡觉", "2026-04-28 22:30")

    complete_action(
        sleep_id,
        feedback={"source": "test", "note": "已上床"},
        completed_at="2026-04-27 22:30",
    )

    by_id = {action["id"]: action for action in get_actions()}
    assert by_id[sleep_id]["status"] == "done"
    assert by_id[later_sleep_id]["status"] == SLEEP_AFTER_SKIP_STATUS
    assert by_id[later_sleep_again_id]["status"] == SLEEP_AFTER_SKIP_STATUS
    assert "已完成睡觉目标" in by_id[later_sleep_id]["feedback"]
    assert sleep_id in by_id[later_sleep_id]["feedback"]
    assert by_id[earlier_id]["status"] == "created"
    assert by_id[later_non_sleep_id]["status"] == "created"
    assert by_id[next_day_sleep_id]["status"] == "created"

def test_complete_sleep_action_without_explicit_completed_at_auto_skips_from_scheduled_at(monkeypatch):
    from datetime import datetime as real_datetime

    from nudge.state import complete_action, get_actions, log_action

    class FixedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 4, 27, 23, 59)

    monkeypatch.setattr("nudge.state.datetime", FixedDatetime)

    sleep_id = log_action("reminder", "22:30 睡觉", "2026-04-27 22:30")
    later_id = log_action("reminder", "23:00 不要熬夜", "2026-04-27 23:00")

    skipped = complete_action(sleep_id, feedback={"source": "test"})

    skipped_ids = {action["id"] for action in skipped}
    actions = {action["id"]: action for action in get_actions(since="2026-04-27", until="2026-04-28")}
    assert actions[sleep_id]["completed_at"] == "2026-04-27 23:59"
    assert later_id in skipped_ids
    assert actions[later_id]["status"] == "skipped_after_sleep"

def test_sleep_auto_skip_uses_actual_completed_at_not_scheduled_at():
    from nudge.state import complete_action, get_actions, log_action

    prep_id = log_action("reminder", "22:30 准备睡觉", "2026-04-27 22:30")
    middle_id = log_action("reminder", "23:00 不要熬夜", "2026-04-27 23:00")
    bedtime_id = log_action("reminder", "23:30 睡觉", "2026-04-27 23:30")
    later_id = log_action("reminder", "23:45 不要熬夜", "2026-04-27 23:45")

    skipped = complete_action(
        bedtime_id,
        feedback={"source": "test", "event_type": "sleep_start", "event_at": "2026-04-27 22:47"},
        completed_at="2026-04-27 22:47",
    )

    skipped_ids = {action["id"] for action in skipped}
    assert prep_id not in skipped_ids
    assert middle_id in skipped_ids
    assert later_id in skipped_ids

    actions = {action["id"]: action for action in get_actions(since="2026-04-27", until="2026-04-28")}
    assert actions[prep_id]["status"] == "created"
    assert actions[middle_id]["status"] == "skipped_after_sleep"
    assert actions[later_id]["status"] == "skipped_after_sleep"

def test_sleep_auto_skip_cross_midnight_uses_actual_completed_at_window():
    from nudge.state import complete_action, get_actions, log_action

    bedtime_id = log_action("reminder", "23:30 睡觉", "2026-04-27 23:30")
    early_next_day_id = log_action("reminder", "00:30 不要熬夜", "2026-04-28 00:30")
    next_evening_id = log_action("reminder", "22:30 睡觉", "2026-04-28 22:30")

    skipped = complete_action(
        bedtime_id,
        feedback={"source": "test", "event_type": "sleep_start", "event_at": "2026-04-28 00:10"},
        completed_at="2026-04-28 00:10",
    )

    skipped_ids = {action["id"] for action in skipped}
    actions = {action["id"]: action for action in get_actions(since="2026-04-27", until="2026-04-29")}
    assert early_next_day_id in skipped_ids
    assert actions[early_next_day_id]["status"] == "skipped_after_sleep"
    assert actions[next_evening_id]["status"] == "created"

def test_complete_sleep_record_does_not_auto_skip_later_sleep_reminders():
    from nudge.state import complete_action, get_actions, log_action

    record_id = log_action("reminder", "晨起称重 + 睡眠记录", "2026-04-27 06:40")
    bedtime_id = log_action("reminder", "22:30 睡觉", "2026-04-27 22:30")
    later_id = log_action("reminder", "不要熬夜", "2026-04-27 23:00")

    complete_action(record_id)

    by_id = {action["id"]: action for action in get_actions()}
    assert by_id[record_id]["status"] == "done"
    assert by_id[bedtime_id]["status"] == "created"
    assert by_id[later_id]["status"] == "created"



def test_shutdown_routine_auto_skips_later_sleep_reminders():
    from nudge.sleep_reminders import SLEEP_AFTER_SKIP_STATUS
    from nudge.state import complete_action, get_actions, log_action

    shutdown_id = log_action("reminder", "22:30 关机流程", "2026-04-29 22:30")
    prepare_id = log_action("reminder", "23:00 准备睡觉", "2026-04-29 23:00")
    latest_id = log_action("reminder", "23:30 最晚上床", "2026-04-29 23:30")

    skipped = complete_action(
        shutdown_id,
        feedback={"source": "test", "note": "已关机准备睡眠"},
        completed_at="2026-04-29 22:34",
    )

    skipped_ids = {action["id"] for action in skipped}
    actions = {action["id"]: action for action in get_actions(since="2026-04-29", until="2026-04-30")}
    assert prepare_id in skipped_ids
    assert latest_id in skipped_ids
    assert actions[prepare_id]["status"] == SLEEP_AFTER_SKIP_STATUS
    assert actions[latest_id]["status"] == SLEEP_AFTER_SKIP_STATUS

def test_complete_sleep_preparation_does_not_auto_skip_bedtime_reminder():
    from nudge.state import complete_action, get_actions, log_action

    prep_id = log_action("reminder", "22:00 准备睡觉", "2026-04-27 22:00")
    bedtime_id = log_action("reminder", "22:30 睡觉", "2026-04-27 22:30")
    later_id = log_action("reminder", "不要熬夜", "2026-04-27 23:00")

    complete_action(prep_id)

    by_id = {action["id"]: action for action in get_actions()}
    assert by_id[prep_id]["status"] == "done"
    assert by_id[bedtime_id]["status"] == "created"
    assert by_id[later_id]["status"] == "created"


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
