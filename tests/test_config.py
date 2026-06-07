"""Public-safe tests for configuration helpers."""

from pathlib import Path

import pytest
from click.testing import CliRunner

import nudge.commands.agent as agent_command_module
import nudge.commands.dogfood as dogfood_command_module
import nudge.dogfood as dogfood_module
import nudge.state as state_module
from nudge.cli import cli
from nudge.config import get_defaults, get_family_aliases, load_config, resolve_state_dir


@pytest.fixture(autouse=True)
def restore_state_globals():
    original_state_dir = state_module.STATE_DIR
    original_db_path = state_module.DB_PATH
    original_legacy_json = state_module.LEGACY_JSON
    original_agent_state_dir = agent_command_module.STATE_DIR
    original_agent_secret = agent_command_module.CONFIRMATION_SECRET_PATH
    original_dogfood_state_dir = dogfood_module.STATE_DIR
    original_dogfood_command_state_dir = dogfood_command_module.STATE_DIR
    yield
    state_module.STATE_DIR = original_state_dir
    state_module.DB_PATH = original_db_path
    state_module.LEGACY_JSON = original_legacy_json
    agent_command_module.STATE_DIR = original_agent_state_dir
    agent_command_module.CONFIRMATION_SECRET_PATH = original_agent_secret
    dogfood_module.STATE_DIR = original_dogfood_state_dir
    dogfood_command_module.STATE_DIR = original_dogfood_command_state_dir


def test_load_config_reads_explicit_public_safe_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                "[general]",
                'default_calendar = "Personal"',
                'default_reminder_list = "Tasks"',
                "",
                "[llm]",
                'provider = "qwen"',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(Path(path))

    assert config["general"]["default_calendar"] == "Personal"
    assert config["llm"]["provider"] == "qwen"


def test_load_config_uses_nudge_config_when_no_explicit_path(monkeypatch, tmp_path):
    public_config = tmp_path / "public.toml"
    private_config = tmp_path / "private" / "config.toml"
    private_config.parent.mkdir()
    public_config.write_text('[general]\ndefault_calendar = "Public"\n', encoding="utf-8")
    private_config.write_text('[general]\ndefault_calendar = "Private"\n', encoding="utf-8")

    monkeypatch.setenv("NUDGE_CONFIG", str(private_config))

    assert load_config()["general"]["default_calendar"] == "Private"
    assert load_config(public_config)["general"]["default_calendar"] == "Public"


def test_relative_state_dir_resolves_from_config_directory(monkeypatch, tmp_path):
    private_dir = tmp_path / "private-overlay"
    private_dir.mkdir()
    config_path = private_dir / "config.toml"
    config_path.write_text('[state]\ndir = "state"\n', encoding="utf-8")
    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)

    config = load_config(config_path)

    assert resolve_state_dir(config) == private_dir / "state"


def test_top_level_config_option_loads_config_for_subcommand(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[general]",
                'default_calendar = "CLI Top Level"',
                "",
                "[state]",
                'dir = "state"',
            ]
        ),
        encoding="utf-8",
    )
    observed = {}

    def fake_run_checks(config_path=None, config=None):
        config = config or load_config(config_path)
        observed["config_path"] = config_path
        observed["default_calendar"] = config["general"]["default_calendar"]
        return []

    monkeypatch.delenv("NUDGE_CONFIG", raising=False)
    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)
    monkeypatch.setattr("nudge.commands.doctor.run_checks", fake_run_checks)
    monkeypatch.setattr("nudge.commands.doctor.log_doctor_checks", lambda checks, config=None: None)

    result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "doctor", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert observed == {
        "config_path": str(config_path),
        "default_calendar": "CLI Top Level",
    }
    assert state_module.STATE_DIR == tmp_path / "state"
    assert agent_command_module.STATE_DIR == tmp_path / "state"
    assert dogfood_module.STATE_DIR == tmp_path / "state"
    assert dogfood_command_module.STATE_DIR == tmp_path / "state"


def test_top_level_config_option_reports_missing_explicit_config(monkeypatch, tmp_path):
    missing_config = tmp_path / "missing.toml"

    monkeypatch.delenv("NUDGE_CONFIG", raising=False)
    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)

    result = CliRunner().invoke(
        cli,
        ["--config", str(missing_config), "doctor", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code != 0
    assert f"Config file not found: {missing_config}" in result.output


def test_top_level_config_option_preserves_message_routing(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[general]",
                'default_calendar = "Routed Calendar"',
                'default_reminder_list = "Routed Tasks"',
                "",
                "[llm]",
                'provider = "qwen"',
            ]
        ),
        encoding="utf-8",
    )
    observed = {}

    def fake_parse_actions(message, aliases):
        observed["message"] = message
        observed["aliases"] = aliases
        return []

    monkeypatch.delenv("NUDGE_CONFIG", raising=False)
    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)
    monkeypatch.setattr("nudge.commands.do.parse_actions", fake_parse_actions)
    monkeypatch.setattr(
        "nudge.commands.do.resolve_apple_backends",
        lambda config: None,
    )

    result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "--dry-run", "Project sync tomorrow"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert observed == {
        "message": "Project sync tomorrow",
        "aliases": [],
    }


def test_top_level_config_equals_form_preserves_message_routing(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[general]",
                'default_calendar = "Equals Calendar"',
                'default_reminder_list = "Equals Tasks"',
                "",
                "[llm]",
                'provider = "qwen"',
            ]
        ),
        encoding="utf-8",
    )
    observed = {}

    def fake_parse_actions(message, aliases):
        observed["message"] = message
        observed["aliases"] = aliases
        return []

    monkeypatch.delenv("NUDGE_CONFIG", raising=False)
    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)
    monkeypatch.setattr("nudge.commands.do.parse_actions", fake_parse_actions)
    monkeypatch.setattr(
        "nudge.commands.do.resolve_apple_backends",
        lambda config: None,
    )

    result = CliRunner().invoke(
        cli,
        [f"--config={config_path}", "--dry-run", "Project sync tomorrow"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert observed == {
        "message": "Project sync tomorrow",
        "aliases": [],
    }


def test_get_defaults_uses_public_safe_values():
    defaults = get_defaults(
        {
            "general": {
                "default_calendar": "Personal",
                "default_reminder_list": "Tasks",
            }
        }
    )

    assert defaults == {
        "default_calendar": "Personal",
        "default_reminder_list": "Tasks",
    }


def test_get_family_aliases_handles_empty_public_config():
    all_aliases, alias_map = get_family_aliases({})

    assert all_aliases == []
    assert alias_map == {}
