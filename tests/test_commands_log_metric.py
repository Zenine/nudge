"""Tests for explicit metric pairs on nudge log/check-in."""

import json

from click.testing import CliRunner

import nudge.state as state
from nudge.commands.log import check_in_command, log_command
from nudge.state import get_action, log_action


def _isolate_state(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")


def test_log_done_with_metric_stores_feedback_metrics(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    action_id = log_action("calendar_event", "Deep work", status="pending")

    result = CliRunner().invoke(
        log_command,
        [
            "done",
            "--id",
            action_id,
            "--metric",
            "effort=8",
            "--metric",
            "rpe=7.5",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    action = get_action(action_id)
    assert action is not None
    assert action["status"] == "done"
    feedback = json.loads(action["feedback"])
    assert feedback["metrics"] == {"effort": 8.0, "rpe": 7.5}


def test_log_done_json_bad_metric_outputs_versioned_payload(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)

    result = CliRunner().invoke(log_command, ["done", "--json", "--metric", "effort=high"])

    assert result.exit_code == 1
    assert "Error:" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert "--metric" in payload["error"]


def test_check_in_done_json_bad_metric_outputs_versioned_payload(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)

    result = CliRunner().invoke(check_in_command, ["done", "--json", "--metric", "effort=high"])

    assert result.exit_code == 1
    assert "Error:" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert "--metric" in payload["error"]


def test_log_metric_rejects_bad_pairs(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    for bad in ("effort", "=8", "effort=high"):
        result = CliRunner().invoke(log_command, ["done", "--metric", bad])

        assert result.exit_code != 0
        assert "--metric" in result.output


def test_log_metric_rejects_duplicate_keys(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    action_id = log_action("calendar_event", "Deep work", status="pending")

    result = CliRunner().invoke(
        log_command,
        ["done", "--id", action_id, "--metric", "effort=8", "--metric", "effort=9"],
    )

    assert result.exit_code != 0
    assert "--metric" in result.output
    assert "effort" in result.output


def test_log_parse_rejects_metric_flag(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)

    result = CliRunner().invoke(log_command, ["parse", "做完了", "--metric", "effort=8"])

    assert result.exit_code != 0
    assert "parse" in result.output
