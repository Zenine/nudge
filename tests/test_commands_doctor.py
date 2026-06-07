import json
from datetime import datetime, timedelta

from click.testing import CliRunner
import pytest

import nudge.state as state
from nudge.commands.doctor import doctor_command, run_checks


def _check(payload: dict, name: str) -> dict:
    for check in payload["checks"]:
        if check["name"] == name:
            return check
    raise AssertionError(f"missing doctor check: {name}")


def _check_names(payload: dict) -> set[str]:
    return {check["name"] for check in payload["checks"]}


@pytest.fixture(autouse=True)
def restore_state_globals():
    original_state_dir = state.STATE_DIR
    original_db_path = state.DB_PATH
    original_legacy_json = state.LEGACY_JSON
    yield
    state.STATE_DIR = original_state_dir
    state.DB_PATH = original_db_path
    state.LEGACY_JSON = original_legacy_json


def _minimal_config(tmp_path):
    return {
        "state": {"dir": str(tmp_path / "state")},
        "llm": {"provider": "ollama", "model": "fake-local"},
    }


def test_doctor_payload_includes_read_only_local_health_checks(monkeypatch, tmp_path):
    config = _minimal_config(tmp_path)
    state.configure_state(config)
    state.enqueue_agent_command(request_id="dead-1", payload={"n": 1})
    state.enqueue_agent_command(request_id="stale-1", payload={"n": 2})
    old_started = (datetime.now() - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S")
    with state._db() as conn:
        conn.execute("UPDATE command_queue SET status = 'dead_letter' WHERE request_id = 'dead-1'")
        conn.execute(
            """
            UPDATE command_queue
            SET status = 'running', attempts = 2, started_at = ?
            WHERE request_id = 'stale-1'
            """,
            (old_started,),
        )

    monkeypatch.setattr("nudge.commands.doctor.load_config", lambda config_path=None: config)
    monkeypatch.setattr(
        "nudge.commands.doctor._check_llm",
        lambda config: state_check("PASS", "LLM", "provider=ollama"),
    )
    monkeypatch.setattr(
        "nudge.commands.doctor._check_calendar",
        lambda config: state_check("PASS", "Calendar", "ok"),
    )
    monkeypatch.setattr(
        "nudge.commands.doctor._check_reminders",
        lambda config: state_check("PASS", "Reminders", "ok"),
    )
    monkeypatch.setattr(
        "nudge.commands.doctor._check_notes_for_config",
        lambda config: state_check("PASS", "Notes", "ok"),
    )
    monkeypatch.setattr("nudge.commands.doctor._check_mail", lambda: state_check("PASS", "Mail", "ok"))
    monkeypatch.setattr(
        "nudge.commands.doctor._check_clock_for_config",
        lambda config: state_check("PASS", "Clock", "ok"),
    )
    monkeypatch.setattr("nudge.commands.doctor.log_doctor_checks", lambda checks, config=None: None)

    result = CliRunner().invoke(doctor_command, ["--json"], prog_name="nudge doctor")

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    sqlite_check = _check(payload, "SQLite")
    daemon_check = _check(payload, "Daemon")
    disk_check = _check(payload, "Disk")
    assert sqlite_check["status"] == "PASS"
    assert "integrity_check=ok" in sqlite_check["message"]
    assert daemon_check["status"] == "FAIL"
    assert "dead_letter=1" in daemon_check["message"]
    assert "stale_running=1" in daemon_check["message"]
    assert disk_check["status"] == "PASS"
    assert "free=" in disk_check["message"]
    assert "LLM Ping" not in _check_names(payload)


def test_doctor_llm_ping_is_explicit_and_uses_provider_call(monkeypatch, tmp_path):
    config = _minimal_config(tmp_path)
    calls = []

    class FakeProvider:
        base_url = "http://fake.local/v1"

        def call(self, system, user_message, model, max_tokens=1024, temperature=0):
            calls.append(
                {
                    "system": system,
                    "user_message": user_message,
                    "model": model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
            )
            return "pong"

    monkeypatch.setattr("nudge.commands.doctor.create_provider", lambda llm_config: FakeProvider())

    checks = run_checks(config=config, llm_ping=True)

    ping = next(check for check in checks if check.name == "LLM Ping")
    assert ping.status == "PASS"
    assert "fake-local" in ping.message
    assert calls == [
        {
            "system": "Nudge doctor connectivity check.",
            "user_message": "Reply with pong.",
            "model": "fake-local",
            "max_tokens": 8,
            "temperature": 0,
        }
    ]


def test_doctor_cli_llm_ping_flag_is_opt_in(monkeypatch):
    observed = {}

    def fake_run_checks(config_path=None, config=None, *, llm_ping=False):
        observed["llm_ping"] = llm_ping
        return []

    monkeypatch.setattr("nudge.commands.doctor.run_checks", fake_run_checks)
    monkeypatch.setattr("nudge.commands.doctor.load_config", lambda config_path=None: {})
    monkeypatch.setattr("nudge.commands.doctor.log_doctor_checks", lambda checks, config=None: None)

    result = CliRunner().invoke(
        doctor_command,
        ["--llm-ping", "--json"],
        prog_name="nudge doctor",
    )

    assert result.exit_code == 0, result.output
    assert observed == {"llm_ping": True}


def test_sqlite_integrity_check_does_not_create_missing_database(tmp_path):
    config = _minimal_config(tmp_path)
    db_path = tmp_path / "state" / "nudge.db"

    checks = run_checks(config=config)

    sqlite_check = next(check for check in checks if check.name == "SQLite")
    assert sqlite_check.status == "WARN"
    assert "not found" in sqlite_check.message
    assert not db_path.exists()


def state_check(status: str, name: str, message: str):
    from nudge.commands.doctor import CheckResult

    return CheckResult(status, name, message)
