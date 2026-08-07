"""Tests for dogfood CLI command."""

import json

from click.testing import CliRunner

import nudge.commands.dogfood as dogfood_command_module
from nudge.commands.dogfood import dogfood_command


def test_dogfood_weekly_save_still_writes_report_with_json(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.commands.dogfood.get_actions", lambda since=None, until=None: [])
    monkeypatch.setattr("nudge.commands.dogfood.run_checks", lambda: [])
    monkeypatch.setattr(dogfood_command_module, "STATE_DIR", tmp_path)

    result = CliRunner().invoke(dogfood_command, ["weekly", "--save", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert (tmp_path / "dogfood" / f"{payload['report']['period']['iso_week']}.md").exists()
