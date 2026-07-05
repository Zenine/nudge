"""Public-safe tests for configuration helpers."""

from pathlib import Path

import nudge.config as config
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


def test_resolve_state_dir_defaults_to_xdg_not_package_dir(monkeypatch, tmp_path):
    # A pip/pipx install roots PROJECT_ROOT at site-packages; the default state
    # dir must never fall inside the installed package. It must use XDG instead.
    pkg = tmp_path / "site-packages"
    pkg.mkdir()
    xdg = tmp_path / "xdg-data"
    monkeypatch.setattr(config, "PROJECT_ROOT", pkg)
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)

    resolved = resolve_state_dir({})

    assert resolved == xdg / "nudge"
    assert pkg not in resolved.parents


def test_resolve_state_dir_prefers_existing_legacy_project_dir(monkeypatch, tmp_path):
    # Back-compat: a source checkout that already has PROJECT_ROOT/.nudge keeps
    # using it so existing local data is never orphaned by the XDG change.
    root = tmp_path / "checkout"
    (root / ".nudge").mkdir(parents=True)
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)

    assert resolve_state_dir({}) == root / ".nudge"
