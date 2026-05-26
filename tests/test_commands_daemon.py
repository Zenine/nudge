"""Tests for daemon CLI contracts."""

from __future__ import annotations

import json

from click.testing import CliRunner

from nudge.cli import cli


def test_daemon_enqueue_reads_request_from_file(monkeypatch, tmp_path):
    import nudge.commands.daemon as daemon

    enqueued = []
    monkeypatch.setattr(
        daemon,
        "enqueue_agent_command",
        lambda **kwargs: enqueued.append(kwargs) or "queued-file-input",
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "request_id": "file-input",
                "source": "contract-test",
                "actions": [{"type": "reminder.create", "name": "x", "due_date": "2026-05-27"}],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["daemon", "enqueue", "--file", str(request_path), "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["request_id"] == "queued-file-input"
    assert enqueued[0]["payload"]["request_id"] == "file-input"
    assert enqueued[0]["request_type"] == "agent.apply"


def test_daemon_run_logs_startup_code_revision(monkeypatch, tmp_path):
    import nudge.commands.daemon as daemon

    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(["[state]", f'dir = "{state_dir}"', ""]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        daemon,
        "_repo_code_state",
        lambda: {"repo_root": "/repo/nudge-public", "revision": "abc123", "dirty": False},
    )
    monkeypatch.setattr(
        daemon,
        "recover_stale_running_commands",
        lambda **_kwargs: {"requeued_count": 0, "dead_lettered_count": 0},
    )
    monkeypatch.setattr(daemon, "claim_next_queued_command", lambda: None)

    result = CliRunner().invoke(
        cli,
        [
            "daemon",
            "run",
            "--config",
            str(config_path),
            "--once",
            "--sleep-ms",
            "250",
        ],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    log_path = state_dir / "logs" / "nudge-runtime.jsonl"
    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["level"] == "INFO"
    assert entry["source"] == "daemon.run"
    assert entry["message"] == "daemon started"
    assert entry["revision"] == "abc123"
    assert entry["dirty"] is False
    assert entry["repo_root"] == "/repo/nudge-public"
    assert entry["config_path"] == str(config_path)
    assert entry["run_once"] is True
    assert entry["sleep_ms"] == 250
