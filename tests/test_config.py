"""Public-safe tests for configuration helpers."""

from pathlib import Path

import pytest

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


def test_resolve_state_dir_requires_explicit_state_dir_without_env(monkeypatch, tmp_path):
    # Fail closed: an unconfigured command must not silently create or read a
    # fallback SQLite, whether under the package, XDG, or a source checkout.
    pkg = tmp_path / "site-packages"
    pkg.mkdir()
    xdg = tmp_path / "xdg-data"
    monkeypatch.setattr(config, "PROJECT_ROOT", pkg)
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        resolve_state_dir({})

    message = str(excinfo.value)
    assert "NUDGE_STATE_DIR" in message
    assert "[state].dir" in message
    assert "--config" in message
    assert str(pkg / ".nudge") in message


def test_resolve_state_dir_rejects_existing_legacy_project_dir(monkeypatch, tmp_path):
    # A pre-existing source-tree .nudge is more dangerous than no data: stale or
    # empty results can look authoritative. Require explicit config instead.
    root = tmp_path / "checkout"
    (root / ".nudge").mkdir(parents=True)
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        resolve_state_dir({})

    assert str(root / ".nudge") in str(excinfo.value)
