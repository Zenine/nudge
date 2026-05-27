"""Public-safe tests for configuration helpers."""

from pathlib import Path

from nudge.config import get_defaults, get_family_aliases, load_config, resolve_state_dir


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
