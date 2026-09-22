"""Tests for dogfood CLI command."""

import json

from click.testing import CliRunner

import nudge.commands.dogfood as dogfood_command_module
from nudge.cli import cli
from nudge.commands.dogfood import dogfood_command
from nudge.commands.doctor import CheckResult, PASS


def test_dogfood_weekly_save_still_writes_report_with_json(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.commands.dogfood.get_actions", lambda since=None, until=None: [])
    monkeypatch.setattr("nudge.commands.dogfood.run_checks", lambda: [])
    monkeypatch.setattr(dogfood_command_module, "STATE_DIR", tmp_path)

    result = CliRunner().invoke(dogfood_command, ["weekly", "--save", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert (tmp_path / "dogfood" / f"{payload['report']['period']['iso_week']}.md").exists()


def test_dogfood_weekly_prints_report(monkeypatch):
    monkeypatch.setattr(
        "nudge.commands.dogfood.get_actions",
        lambda since=None, until=None: [
            {"type": "calendar_event", "summary": "A", "status": "done", "external_id": "Family::uid"},
        ],
    )
    monkeypatch.setattr("nudge.commands.dogfood.run_checks", lambda: [CheckResult(PASS, "Calendar", "ok")])

    result = CliRunner().invoke(dogfood_command, ["weekly", "--note", "本周跑通闭环"])

    assert result.exit_code == 0, result.output
    assert "Nudge Dogfood 周报" in result.output
    assert "本周跑通闭环" in result.output
    assert "真实 Calendar 写入：1" in result.output


def test_dogfood_weekly_save_writes_report(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.commands.dogfood.get_actions", lambda since=None, until=None: [])
    monkeypatch.setattr("nudge.commands.dogfood.run_checks", lambda: [])
    monkeypatch.setattr("nudge.commands.dogfood.STATE_DIR", tmp_path)

    result = CliRunner().invoke(dogfood_command, ["weekly", "--save"])

    assert result.exit_code == 0, result.output
    assert "已保存" in result.output
    assert (tmp_path / "dogfood").exists()


def test_root_cli_lists_dogfood_command(monkeypatch):
    monkeypatch.setattr("nudge.cli.load_config", lambda: {"llm": {"provider": "qwen"}})

    result = CliRunner().invoke(cli, ["--help"], prog_name="nudge")

    assert result.exit_code == 0
    assert "dogfood" in result.output


def test_dogfood_weekly_json_outputs_schema_version(monkeypatch):
    import json

    monkeypatch.setattr(
        "nudge.commands.dogfood.get_actions",
        lambda since=None, until=None: [
            {"type": "calendar_event", "summary": "A", "status": "done", "external_id": "Family::uid"},
        ],
    )
    monkeypatch.setattr("nudge.commands.dogfood.run_checks", lambda: [CheckResult(PASS, "Calendar", "ok")])

    result = CliRunner().invoke(dogfood_command, ["weekly", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["report"]["actions"]["calendar_writes"] == 1


def test_dogfood_weekly_export_json_writes_machine_readable_file(monkeypatch, tmp_path):
    import json

    monkeypatch.setattr("nudge.commands.dogfood.get_actions", lambda since=None, until=None: [])
    monkeypatch.setattr("nudge.commands.dogfood.run_checks", lambda: [])
    output = tmp_path / "dogfood.json"

    result = CliRunner().invoke(dogfood_command, ["weekly", "--export-json", str(output)])

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text())
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["report"]["actions"]["total"] == 0
    assert "已导出 JSON" in result.output
