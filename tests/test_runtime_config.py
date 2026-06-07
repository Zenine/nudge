"""Runtime config/state wiring tests."""

import os

from click.testing import CliRunner

import nudge.commands.agent as agent_command_module
import nudge.commands.dogfood as dogfood_command_module
import nudge.dogfood as dogfood_module
import nudge.state as state_module
from nudge.cli import cli


def _write_config(path, state_dir, calendar_name):
    path.write_text(
        "\n".join(
            [
                "[general]",
                f'default_calendar = "{calendar_name}"',
                "",
                "[state]",
                f'dir = "{state_dir}"',
            ]
        ),
        encoding="utf-8",
    )


def test_cli_env_config_configures_runtime_state(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    private_state = tmp_path / "private-state"
    _write_config(config_path, private_state, "Env Calendar")

    observed = {}

    def fake_run_checks(config_path=None, config=None):
        observed["config_path"] = config_path
        observed["config"] = config
        return []

    monkeypatch.setenv("NUDGE_CONFIG", str(config_path))
    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)
    monkeypatch.setattr("nudge.commands.doctor.run_checks", fake_run_checks)
    monkeypatch.setattr("nudge.commands.doctor.log_doctor_checks", lambda checks, config=None: None)

    result = CliRunner().invoke(cli, ["doctor", "--json"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    assert observed["config_path"] is None
    assert observed["config"] is None
    assert state_module.STATE_DIR == private_state
    assert agent_command_module.STATE_DIR == private_state
    assert agent_command_module.CONFIRMATION_SECRET_PATH == private_state / "agent_confirm_secret"
    assert dogfood_module.STATE_DIR == private_state
    assert dogfood_command_module.STATE_DIR == private_state


def test_cli_top_level_config_does_not_write_nudge_config_env(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    private_state = tmp_path / "private-state"
    _write_config(config_path, private_state, "Explicit Calendar")

    monkeypatch.delenv("NUDGE_CONFIG", raising=False)
    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)
    monkeypatch.setattr("nudge.commands.doctor.run_checks", lambda config_path=None, config=None: [])
    monkeypatch.setattr("nudge.commands.doctor.log_doctor_checks", lambda checks, config=None: None)

    result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "doctor", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert os.environ.get("NUDGE_CONFIG") is None
    assert state_module.STATE_DIR == private_state
    assert agent_command_module.STATE_DIR == private_state
