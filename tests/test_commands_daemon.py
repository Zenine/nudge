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
