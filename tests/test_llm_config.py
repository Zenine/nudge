from pathlib import Path

from nudge.commands import doctor
from nudge.config import DEFAULT_LLM_CONFIG, DEFAULT_SECRETS_PATH


def test_default_llm_provider_matches_bootstrap_dashscope_hint():
    assert DEFAULT_LLM_CONFIG["provider"] == "qwen"
    assert DEFAULT_LLM_CONFIG["model"] == "qwen-plus"
    assert DEFAULT_LLM_CONFIG["models"]["fast"] == "qwen-plus"
    assert DEFAULT_LLM_CONFIG["models"]["default"] == "qwen-plus"
    assert DEFAULT_LLM_CONFIG["models"]["strong"] == "qwen-plus"


def test_default_secrets_path_uses_deployment_user_private_config_dir():
    assert DEFAULT_SECRETS_PATH == Path.home() / ".config" / "nudge" / "secrets.yaml"


def test_doctor_uses_same_default_llm_provider(monkeypatch):
    class DummyProvider:
        api_key = "test-key"
        base_url = None

    monkeypatch.setattr(doctor, "create_provider", lambda config: DummyProvider())

    result = doctor._check_llm({})

    assert result.status == doctor.PASS
    assert "provider=qwen" in result.message
