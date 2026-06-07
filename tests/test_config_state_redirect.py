"""Regression tests for command-level --config state redirection."""

import json
import sqlite3
from datetime import date, timedelta

import pytest
from click.testing import CliRunner

import nudge.commands.dogfood as dogfood_command_module
import nudge.commands.review as review_command_module
import nudge.dogfood as dogfood_module
import nudge.state as state_module
from nudge.apple.calendar import make_calendar_external_id
from nudge.commands.daemon import daemon_command
from nudge.commands.dogfood import dogfood_command
from nudge.commands.habits import habits_command
from nudge.commands.health import health_command
from nudge.commands.review import review_command


@pytest.fixture(autouse=True)
def restore_state_globals(monkeypatch):
    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)
    original_state_dir = state_module.STATE_DIR
    original_db_path = state_module.DB_PATH
    original_legacy_json = state_module.LEGACY_JSON
    original_dogfood_state_dir = dogfood_module.STATE_DIR
    original_dogfood_command_state_dir = dogfood_command_module.STATE_DIR
    yield
    state_module.STATE_DIR = original_state_dir
    state_module.DB_PATH = original_db_path
    state_module.LEGACY_JSON = original_legacy_json
    dogfood_module.STATE_DIR = original_dogfood_state_dir
    dogfood_command_module.STATE_DIR = original_dogfood_command_state_dir


def _write_config(path, state_dir):
    path.write_text(
        "\n".join(
            [
                "[state]",
                f'dir = "{state_dir}"',
                "",
                "[general]",
                'default_calendar = "Private Calendar"',
            ]
        ),
        encoding="utf-8",
    )


def _use_default_state(default_state):
    state_module.configure_state({"state": {"dir": str(default_state)}})


def _count_rows(db_path, table):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_habits_log_config_writes_private_state_not_default(tmp_path):
    default_state = tmp_path / "default-state"
    private_state = tmp_path / "private-state"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, private_state)
    _use_default_state(default_state)

    result = CliRunner().invoke(
        habits_command,
        ["--config", str(config_path), "log", "reading"],
        prog_name="nudge habits",
    )

    assert result.exit_code == 0, result.output
    assert _count_rows(private_state / "nudge.db", "habit_logs") == 1
    assert not (default_state / "nudge.db").exists()


def test_health_import_apply_config_writes_private_state_not_default(tmp_path):
    default_state = tmp_path / "default-state"
    private_state = tmp_path / "private-state"
    config_path = tmp_path / "config.toml"
    export = tmp_path / "health-export.json"
    _write_config(config_path, private_state)
    _use_default_state(default_state)
    export.write_text(
        json.dumps(
            {
                "metrics": {
                    "steps": [
                        {"date": "2026-06-01", "value": 100, "source": "Watch"},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        health_command,
        ["import", str(export), "--apply", "--config", str(config_path), "--json"],
        prog_name="nudge health",
    )

    assert result.exit_code == 0, result.output
    assert _count_rows(private_state / "nudge.db", "health_imports") == 1
    assert _count_rows(private_state / "nudge.db", "health_daily_summary") == 1
    assert not (default_state / "nudge.db").exists()


def test_daemon_config_redirects_enqueue_queue_status_recover_retry_and_health(tmp_path):
    default_state = tmp_path / "default-state"
    private_state = tmp_path / "private-state"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, private_state)
    _use_default_state(default_state)
    runner = CliRunner()
    request = {"request_id": "queue-1", "source": "test-suite", "dry_run": True, "actions": []}

    enqueue = runner.invoke(
        daemon_command,
        ["enqueue", "--config", str(config_path), "--json"],
        input=json.dumps(request),
        prog_name="nudge daemon",
    )
    queue = runner.invoke(
        daemon_command,
        ["queue", "--config", str(config_path), "--json"],
        prog_name="nudge daemon",
    )
    status = runner.invoke(
        daemon_command,
        ["status", "--config", str(config_path), "--json"],
        prog_name="nudge daemon",
    )

    assert enqueue.exit_code == 0, enqueue.output
    assert queue.exit_code == 0, queue.output
    assert status.exit_code == 0, status.output
    assert json.loads(queue.output)["count"] == 1
    assert json.loads(status.output)["queued"] == 1

    with sqlite3.connect(private_state / "nudge.db") as conn:
        conn.execute(
            """
            UPDATE command_queue
            SET status = 'running',
                attempts = 1,
                started_at = datetime('now', '-90 minutes')
            WHERE request_id = 'queue-1'
            """
        )

    recover = runner.invoke(
        daemon_command,
        ["recover", "--config", str(config_path), "--stale-minutes", "1", "--json"],
        prog_name="nudge daemon",
    )
    assert recover.exit_code == 0, recover.output
    assert json.loads(recover.output)["requeued_count"] == 1

    with sqlite3.connect(private_state / "nudge.db") as conn:
        conn.execute("UPDATE command_queue SET status = 'failed' WHERE request_id = 'queue-1'")

    retry = runner.invoke(
        daemon_command,
        ["retry", "--config", str(config_path), "--request-id", "queue-1", "--json"],
        prog_name="nudge daemon",
    )
    health = runner.invoke(
        daemon_command,
        ["health", "--config", str(config_path), "--json"],
        prog_name="nudge daemon",
    )

    assert retry.exit_code == 0, retry.output
    assert health.exit_code == 0, health.output
    assert json.loads(retry.output)["item"]["status"] == "queued"
    assert json.loads(health.output)["queue"]["queued"] == 1
    assert _count_rows(private_state / "nudge.db", "command_queue") == 1
    assert not (default_state / "nudge.db").exists()


def test_daemon_run_config_reads_private_queue_not_default(monkeypatch, tmp_path):
    default_state = tmp_path / "default-state"
    private_state = tmp_path / "private-state"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, private_state)
    config = state_module.load_config(config_path)
    state_module.configure_state(config)
    state_module.enqueue_agent_command(
        payload={"request_id": "run-1", "source": "test-suite", "actions": []},
        request_id="run-1",
        max_queue_depth=100,
    )
    _use_default_state(default_state)

    monkeypatch.setattr(
        "nudge.commands.daemon.apply_agent_request",
        lambda *, request, config: ({"ok": True, "request_id": request["request_id"], "actions": []}, 0),
    )

    result = CliRunner().invoke(
        daemon_command,
        ["run", "--config", str(config_path), "--once"],
        prog_name="nudge daemon",
    )

    assert result.exit_code == 0, result.output
    with sqlite3.connect(private_state / "nudge.db") as conn:
        row = conn.execute("SELECT status FROM command_queue WHERE request_id = 'run-1'").fetchone()
    assert row[0] == "succeeded"
    assert not (default_state / "nudge.db").exists()


def test_dogfood_weekly_save_config_reads_and_saves_private_state(monkeypatch, tmp_path):
    default_state = tmp_path / "default-state"
    private_state = tmp_path / "private-state"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, private_state)
    config = state_module.load_config(config_path)
    state_module.configure_state(config)
    state_module.log_action(
        action_type="calendar_event",
        summary="Private dogfood action",
        scheduled_at=date.today().isoformat() + " 09:00",
        status="created",
    )
    _use_default_state(default_state)
    monkeypatch.setattr(dogfood_command_module, "run_checks", lambda: [])

    result = CliRunner().invoke(
        dogfood_command,
        ["weekly", "--config", str(config_path), "--save"],
        prog_name="nudge dogfood",
    )

    assert result.exit_code == 0, result.output
    saved_reports = list((private_state / "dogfood").glob("*.md"))
    assert saved_reports
    assert "Private dogfood action" in saved_reports[0].read_text(encoding="utf-8")
    assert not (default_state / "nudge.db").exists()
    assert not (default_state / "dogfood").exists()


def test_review_weekly_adapt_apply_config_writes_private_state_not_default(monkeypatch, tmp_path):
    default_state = tmp_path / "default-state"
    private_state = tmp_path / "private-state"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, private_state)
    config = state_module.load_config(config_path)
    state_module.configure_state(config)
    today = date.today()
    action_id = state_module.log_action(
        action_type="calendar_event",
        summary="Deep work",
        scheduled_at=(today - timedelta(days=1)).isoformat() + " 09:00",
        external_id=make_calendar_external_id("Private Calendar", "event-1"),
        status="created",
    )
    _use_default_state(default_state)
    monkeypatch.setattr(
        review_command_module,
        "suggest_adaptation",
        lambda actions, habit_streaks: [
                {
                    "type": "delete",
                    "title": "Remove stale event",
                    "reason": "No longer useful",
                    "action_id": action_id,
                }
            ],
    )
    monkeypatch.setattr("nudge.adapt.delete_event_by_uid", lambda uid: (True, "deleted"))

    result = CliRunner().invoke(
        review_command,
        ["weekly", "--config", str(config_path), "--adapt", "--apply"],
        input="y\n",
        prog_name="nudge review",
    )

    assert result.exit_code == 0, result.output
    with sqlite3.connect(private_state / "nudge.db") as conn:
        row = conn.execute("SELECT status, feedback FROM actions WHERE id = ?", (action_id,)).fetchone()
    assert row[0] == "deleted"
    assert "review weekly --adapt" in row[1]
    assert not (default_state / "nudge.db").exists()
