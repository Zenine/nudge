import json
import sqlite3

import pytest
from click.testing import CliRunner

import nudge.state as state_module
from nudge.commands.daemon import daemon_command


@pytest.fixture(autouse=True)
def isolate_daemon_state(monkeypatch, tmp_path):
    original_state_dir = state_module.STATE_DIR
    original_db_path = state_module.DB_PATH
    original_legacy_json = state_module.LEGACY_JSON
    state_dir = tmp_path / "state"
    monkeypatch.setenv("NUDGE_STATE_DIR", str(state_dir))
    state_module.configure_state({"state": {"dir": str(state_dir)}})
    yield state_dir
    state_module.STATE_DIR = original_state_dir
    state_module.DB_PATH = original_db_path
    state_module.LEGACY_JSON = original_legacy_json


def _rows(table: str) -> list[dict]:
    with sqlite3.connect(state_module.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def _queue_row(request_id: str) -> dict:
    with sqlite3.connect(state_module.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM command_queue WHERE request_id = ?", (request_id,)).fetchone()
    assert row is not None
    return dict(row)


def _enqueue(payload: dict, *, request_type: str = "agent.apply", request_id: str = "req-1") -> None:
    state_module.enqueue_agent_command(
        payload=payload,
        request_type=request_type,
        source=payload.get("source"),
        request_id=request_id,
        max_queue_depth=100,
    )


def test_daemon_run_once_ignores_invalid_sleep_ms_env(monkeypatch):
    logged_start = {}

    monkeypatch.setenv("NUDGE_DAEMON_SLEEP_MS", "not-a-number")
    monkeypatch.setattr(
        "nudge.commands.daemon.recover_stale_running_commands",
        lambda *, stale_minutes, max_attempts: {"requeued_count": 0, "dead_lettered_count": 0},
    )
    monkeypatch.setattr("nudge.commands.daemon.claim_next_queued_command", lambda: None)
    monkeypatch.setattr(
        "nudge.commands.daemon._log_daemon_start",
        lambda **kwargs: logged_start.update(kwargs),
    )

    result = CliRunner().invoke(daemon_command, ["run", "--once"], prog_name="nudge daemon")

    assert result.exit_code == 0
    assert result.exception is None
    assert logged_start["sleep_ms"] == 3000


def test_daemon_enqueue_stores_structured_request_from_stdin():
    request = {
        "request_id": "enqueue-1",
        "source": "test-suite",
        "dry_run": True,
        "actions": [],
    }

    result = CliRunner().invoke(
        daemon_command,
        ["enqueue", "--json"],
        input=json.dumps(request),
        prog_name="nudge daemon",
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["ok"] is True
    assert output["request_id"] == "enqueue-1"
    row = _queue_row("enqueue-1")
    assert row["status"] == "queued"
    assert row["request_type"] == "agent.apply"
    assert json.loads(row["payload"])["source"] == "test-suite"


def test_daemon_run_once_marks_success_and_logs_run(monkeypatch):
    calls = []

    def fake_apply_agent_request(*, request, config):
        calls.append(request)
        return {"ok": True, "request_id": request["request_id"], "actions": []}, 0

    _enqueue(
        {"request_id": "success-1", "source": "test-suite", "actions": []},
        request_id="success-1",
    )
    monkeypatch.setattr("nudge.commands.daemon.apply_agent_request", fake_apply_agent_request)
    monkeypatch.setattr("nudge.commands.daemon.load_config", lambda: {})

    result = CliRunner().invoke(daemon_command, ["run", "--once"], prog_name="nudge daemon")

    assert result.exit_code == 0
    assert calls == [{"request_id": "success-1", "source": "test-suite", "actions": []}]
    row = _queue_row("success-1")
    assert row["status"] == "succeeded"
    assert row["last_exit_code"] == 0
    runs = _rows("daemon_runs")
    assert len(runs) == 1
    assert runs[0]["request_id"] == "success-1"
    assert runs[0]["status"] == "succeeded"


def test_daemon_run_once_marks_non_object_payload_failed_and_logs_run():
    state_module.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(state_module.DB_PATH) as conn:
        state_module._init_tables(conn)
        conn.execute(
            """
            INSERT INTO command_queue (request_id, source, request_type, payload, status, last_payload_size)
            VALUES (?, ?, ?, ?, 'queued', ?)
            """,
            ("invalid-payload-1", "test-suite", "agent.apply", json.dumps(["not", "object"]), 16),
        )

    result = CliRunner().invoke(daemon_command, ["run", "--once"], prog_name="nudge daemon")

    assert result.exit_code == 0
    row = _queue_row("invalid-payload-1")
    assert row["status"] == "failed"
    assert row["last_exit_code"] == 1
    assert "request payload must be object" in row["last_error"]
    runs = _rows("daemon_runs")
    assert len(runs) == 1
    assert runs[0]["request_id"] == "invalid-payload-1"
    assert runs[0]["status"] == "failed"
    assert "PAYLOAD_INVALID" in runs[0]["output_json"]


def test_daemon_loop_isolates_single_command_exception(monkeypatch):
    calls = []

    def fake_apply_agent_request(*, request, config):
        calls.append(request["request_id"])
        if request["request_id"] == "raise-1":
            raise RuntimeError("boom")
        return {"ok": True, "request_id": request["request_id"], "actions": []}, 0

    _enqueue({"request_id": "raise-1", "source": "test-suite", "actions": []}, request_id="raise-1")
    _enqueue({"request_id": "after-raise", "source": "test-suite", "actions": []}, request_id="after-raise")
    monkeypatch.setattr("nudge.commands.daemon.apply_agent_request", fake_apply_agent_request)
    monkeypatch.setattr("nudge.commands.daemon.load_config", lambda: {})

    result = CliRunner().invoke(
        daemon_command,
        ["run", "--max-empty-cycles", "1", "--sleep-ms", "250"],
        prog_name="nudge daemon",
    )

    assert result.exit_code == 0
    assert calls == ["raise-1", "after-raise"]
    assert _queue_row("raise-1")["status"] == "failed"
    assert _queue_row("after-raise")["status"] == "succeeded"
    assert [row["status"] for row in _rows("daemon_runs")] == ["failed", "succeeded"]


def test_daemon_run_once_records_failure_queue_state_and_runtime_log(monkeypatch):
    def fake_apply_action_status(*, request):
        return {
            "ok": False,
            "request_id": request["request_id"],
            "errors": [{"code": "ACTION_STATUS_INVALID", "message": "missing action_id"}],
        }, 1

    _enqueue(
        {"request_id": "status-fail-1", "source": "test-suite", "status": "done"},
        request_type="agent.status",
        request_id="status-fail-1",
    )
    monkeypatch.setattr("nudge.commands.daemon.apply_action_status", fake_apply_action_status)

    result = CliRunner().invoke(daemon_command, ["run", "--once"], prog_name="nudge daemon")

    assert result.exit_code == 0
    row = _queue_row("status-fail-1")
    assert row["status"] == "failed"
    assert row["last_exit_code"] == 1
    assert row["last_error"] == "missing action_id"
    runs = _rows("daemon_runs")
    assert len(runs) == 1
    assert runs[0]["request_id"] == "status-fail-1"
    assert runs[0]["status"] == "failed"
    assert "ACTION_STATUS_INVALID" in runs[0]["output_json"]
