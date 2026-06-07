"""Quality gates for the public config example."""

import json
import os
import subprocess
from pathlib import Path

from nudge.config import load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_EXAMPLE = PROJECT_ROOT / "config.example.toml"


def test_config_example_loads_and_documents_runtime_sections():
    config = load_config(CONFIG_EXAMPLE)

    assert config["state"]["dir"] == "~/.local/share/nudge"
    assert config["llm"]["provider"] == "ollama"
    assert config["llm"]["max_tokens"] > 0
    assert config["llm"]["retries"] >= 0
    assert config["llm"]["retry_backoff_seconds"] > 0
    assert config["llm"]["models"]["fast"]
    assert config["llm"]["models"]["default"]
    assert config["llm"]["models"]["strong"]
    assert config["llm"]["tasks"]["fast"]["max_tokens"] > 0
    assert config["llm"]["tasks"]["strong"]["max_tokens"] > 0
    assert config["apple"]["calendar"]["backend"] == "native"
    assert config["apple"]["reminders"]["backend"] == "native"
    assert config["apple"]["notes"]["backend"] == "native"
    assert config["apple"]["clock"]["backend"] == "shortcuts"
    assert config["apple"]["clock"]["shortcut_name"]
    assert config["daemon"]["sleep_ms"] > 0
    assert config["daemon"]["stale_minutes"] > 0
    assert config["daemon"]["max_attempts"] > 0


def test_config_example_does_not_contain_private_paths_or_real_secrets():
    text = CONFIG_EXAMPLE.read_text(encoding="utf-8")
    config = load_config(CONFIG_EXAMPLE)

    forbidden_fragments = [
        "/Users/",
        "百" + "度同步盘",
        "DB" + "_backup",
        "nudge" + "-private",
        "sk-",
        "xoxb-",
        "ghp_",
        "AIza",
    ]
    assert not any(fragment in text for fragment in forbidden_fragments)
    assert "api_key" not in config.get("llm", {})
    assert "secrets_path" not in config.get("llm", {})


def test_config_example_doctor_json_is_read_only_by_default(tmp_path):
    env = os.environ.copy()
    env.pop("NUDGE_CONFIG", None)
    env.pop("NUDGE_STATE_DIR", None)
    env.pop("NUDGE_SECRETS_PATH", None)
    env.pop("EMAIL_SECRETS_PATH", None)
    env["HOME"] = str(tmp_path / "home")

    result = subprocess.run(
        [
            str(PROJECT_ROOT / "bin" / "nudge"),
            "--config",
            str(CONFIG_EXAMPLE),
            "doctor",
            "--json",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.stdout.strip(), result.stderr
    payload = json.loads(result.stdout)
    assert "checks" in payload
    assert not (tmp_path / "home").exists()
