"""Public-safe tests for configuration helpers."""

from pathlib import Path

import pytest

import nudge.config as config
from nudge.config import (
    get_configured_calendar_names,
    get_defaults,
    get_family_aliases,
    get_family_routing,
    get_user_profile,
    load_config,
    resolve_state_dir,
)


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


def test_load_config_uses_nudge_config_env_when_no_explicit_path(monkeypatch, tmp_path):
    path = tmp_path / "private-config.toml"
    path.write_text(
        "\n".join(
            [
                "[llm]",
                'provider = "qwen"',
                'model = "qwen-plus"',
                'secrets_path = "~/private-secrets.yaml"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NUDGE_CONFIG", str(path))

    loaded = load_config()

    assert loaded["llm"]["provider"] == "qwen"
    assert loaded["llm"]["model"] == "qwen-plus"
    assert loaded["llm"]["secrets_path"] == "~/private-secrets.yaml"


def test_load_config_explicit_path_overrides_nudge_config_env(monkeypatch, tmp_path):
    env_path = tmp_path / "env-config.toml"
    env_path.write_text('[llm]\nprovider = "qwen"\n', encoding="utf-8")
    explicit_path = tmp_path / "explicit-config.toml"
    explicit_path.write_text('[llm]\nprovider = "ollama"\n', encoding="utf-8")
    monkeypatch.setenv("NUDGE_CONFIG", str(env_path))

    loaded = load_config(explicit_path)

    assert loaded["llm"]["provider"] == "ollama"


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


def test_load_config_missing_file():
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config("/nonexistent/path/config.toml")


def test_get_family_aliases_empty_config():
    all_aliases, alias_map = get_family_aliases({})
    assert all_aliases == []
    assert alias_map == {}


def test_get_family_members_includes_identity_fields():
    config = {
        "family": {
            "mom": {
                "display_name": "李梅",
                "role": "mom",
                "aliases": ["妈妈", "李梅", "梅梅"],
                "calendar": "个人",
                "reminder_list": "家庭",
            }
        }
    }

    from nudge.config import get_family_members, get_family_aliases

    members = get_family_members(config)
    assert members == [
        {
            "key": "mom",
            "name": "李梅",
            "display_name": "李梅",
            "role": "mom",
            "aliases": ["妈妈", "李梅", "梅梅"],
            "calendar": "个人",
            "reminder_list": "家庭",
        }
    ]

    all_aliases, alias_map = get_family_aliases(config)
    for alias in ["李梅", "梅梅", "妈妈"]:
        assert alias in all_aliases
        assert alias_map[alias]["member_key"] == "mom"
        assert alias_map[alias]["display_name"] == "李梅"


def test_get_family_members_falls_back_to_first_alias_for_name():
    from nudge.config import get_family_members

    config = {"family": {"dad": {"aliases": ["爸爸"], "reminder_list": "家庭"}}}

    assert get_family_members(config)[0]["name"] == "爸爸"
    assert get_family_members(config)[0]["display_name"] == "爸爸"


def test_get_configured_calendar_names_deduplicates_in_stable_order():
    config = {
        "general": {"default_calendar": "Family"},
        "calendars": {
            "workout": "个人",
            "work": "工作",
            "duplicate": "Family",
        },
        "family": {
            "dad": {"calendar": "Family"},
            "mom": {"calendar": "家庭"},
            "kid": {},
        },
    }

    assert get_configured_calendar_names(config) == ["Family", "个人", "工作", "家庭"]


def test_get_family_routing_defaults_when_missing():
    assert get_family_routing({}) == {
        "default": "all",
        "llm_fallback": False,
        "llm_confidence_threshold": 0.65,
        "display": {
            "title_prefix": True,
            "body_assignee_note": False,
        },
        "rules": [],
    }


def test_get_family_routing_treats_malformed_routing_as_empty_config():
    assert get_family_routing({"family": {"routing": "broken"}}) == {
        "default": "all",
        "llm_fallback": False,
        "llm_confidence_threshold": 0.65,
        "display": {
            "title_prefix": True,
            "body_assignee_note": False,
        },
        "rules": [],
    }


def test_get_family_routing_uses_default_threshold_when_invalid():
    assert get_family_routing({"family": {"routing": {"llm_confidence_threshold": "bad"}}})[
        "llm_confidence_threshold"
    ] == 0.65


def test_get_family_routing_reads_display_options():
    assert get_family_routing(
        {
            "family": {
                "routing": {
                    "display": {
                        "title_prefix": False,
                        "body_assignee_note": True,
                    }
                }
            }
        }
    )["display"] == {
        "title_prefix": False,
        "body_assignee_note": True,
    }
