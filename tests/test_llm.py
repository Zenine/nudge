"""Tests for nudge.llm module."""

import sys
from types import SimpleNamespace

import pytest

import nudge.llm as llm_module
from nudge.llm import (
    DEFAULT_LLM_CONFIG,
    LLMError,
    create_provider,
    get_model_for_task,
    AnthropicProvider,
    OpenAICompatibleProvider,
    OllamaProvider,
)


@pytest.fixture(autouse=True)
def isolated_llm_environment(monkeypatch, tmp_path):
    """Keep provider factory tests independent from this machine's real secrets."""
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "QWEN_API_KEY",
        "LLM_API_KEY",
        "EMAIL_SECRETS_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NUDGE_SECRETS_PATH", str(tmp_path / "missing-secrets.yaml"))


class TestCreateProvider:
    def test_default_is_qwen(self):
        provider = create_provider()
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_anthropic_explicit(self):
        provider = create_provider({"provider": "anthropic"})
        assert isinstance(provider, AnthropicProvider)

    def test_openai(self):
        provider = create_provider({"provider": "openai"})
        assert isinstance(provider, OpenAICompatibleProvider)

    def test_ollama(self):
        provider = create_provider({"provider": "ollama"})
        assert isinstance(provider, OllamaProvider)
        assert provider.base_url == "http://localhost:11434/v1"

    def test_ollama_custom_url(self):
        provider = create_provider({"provider": "ollama", "base_url": "http://myhost:11434/v1"})
        assert provider.base_url == "http://myhost:11434/v1"

    def test_ollama_does_not_read_backup_secrets(self, monkeypatch):
        def fail_if_called(_config=None):
            raise AssertionError("Ollama should not read API key secrets")

        monkeypatch.setattr(llm_module, "_load_backup_secrets", fail_if_called)

        provider = create_provider({"provider": "ollama"})

        assert provider.api_key == ""

    def test_unknown_provider_raises(self):
        with pytest.raises(LLMError, match="Unknown LLM provider"):
            create_provider({"provider": "nonexistent"})

    def test_api_key_from_config(self):
        provider = create_provider({"provider": "anthropic", "api_key": "test-key"})
        assert provider.api_key == "test-key"

    def test_base_url_passthrough(self):
        provider = create_provider({
            "provider": "openai",
            "base_url": "https://api.deepseek.com/v1"
        })
        assert provider.base_url == "https://api.deepseek.com/v1"

    def test_qwen_uses_dashscope_compatible_endpoint(self):
        provider = create_provider({"provider": "qwen"})
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_default_secrets_path_is_public_safe(self, monkeypatch):
        monkeypatch.delenv("NUDGE_SECRETS_PATH", raising=False)
        monkeypatch.delenv("EMAIL_SECRETS_PATH", raising=False)

        path = llm_module._get_secrets_path({})

        assert str(path).endswith(".config/nudge/secrets.yaml")
        assert "sync-drive" not in str(path)
        assert "niaite-email" not in str(path)

    def test_dashscope_alias_uses_qwen_provider_defaults(self):
        provider = create_provider({"provider": "dashscope"})
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_qwen_api_key_from_dashscope_env(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-env-key")
        provider = create_provider({"provider": "qwen"})
        assert provider.api_key == "dashscope-env-key"

    def test_qwen_api_key_from_qwen_env_fallback(self, monkeypatch):
        monkeypatch.setenv("QWEN_API_KEY", "qwen-env-key")
        provider = create_provider({"provider": "qwen"})
        assert provider.api_key == "qwen-env-key"

    def test_qwen_api_key_from_backup_secrets(self, monkeypatch, tmp_path):
        secrets_path = tmp_path / "secrets.yaml"
        secrets_path.write_text("dashscope_api_key: dashscope-secret-key\n", encoding="utf-8")
        monkeypatch.setenv("NUDGE_SECRETS_PATH", str(secrets_path))

        provider = create_provider({"provider": "qwen"})

        assert provider.api_key == "dashscope-secret-key"

    def test_qwen_api_key_from_qwen_secret_fallback(self, monkeypatch, tmp_path):
        secrets_path = tmp_path / "secrets.yaml"
        secrets_path.write_text("qwen_api_key: qwen-secret-key\n", encoding="utf-8")
        monkeypatch.setenv("NUDGE_SECRETS_PATH", str(secrets_path))

        provider = create_provider({"provider": "qwen"})

        assert provider.api_key == "qwen-secret-key"

    def test_config_api_key_wins_over_env_and_secrets(self, monkeypatch, tmp_path):
        secrets_path = tmp_path / "secrets.yaml"
        secrets_path.write_text("dashscope_api_key: dashscope-secret-key\n", encoding="utf-8")
        monkeypatch.setenv("NUDGE_SECRETS_PATH", str(secrets_path))
        monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-env-key")

        provider = create_provider({"provider": "qwen", "api_key": "config-key"})

        assert provider.api_key == "config-key"

    def test_openai_api_key_from_backup_secrets(self, monkeypatch, tmp_path):
        secrets_path = tmp_path / "secrets.yaml"
        secrets_path.write_text("openai_api_key: openai-secret-key\n", encoding="utf-8")
        monkeypatch.setenv("NUDGE_SECRETS_PATH", str(secrets_path))

        provider = create_provider({"provider": "openai"})

        assert provider.api_key == "openai-secret-key"

    def test_anthropic_api_key_from_backup_secrets(self, monkeypatch, tmp_path):
        secrets_path = tmp_path / "secrets.yaml"
        secrets_path.write_text("anthropic_api_key: anthropic-secret-key\n", encoding="utf-8")
        monkeypatch.setenv("NUDGE_SECRETS_PATH", str(secrets_path))

        provider = create_provider({"provider": "anthropic"})

        assert provider.api_key == "anthropic-secret-key"

    def test_deepseek_uses_default_openai_compatible_endpoint(self):
        provider = create_provider({"provider": "deepseek"})
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.base_url == "https://api.deepseek.com/v1"

    def test_deepseek_api_key_from_backup_secrets(self, monkeypatch, tmp_path):
        secrets_path = tmp_path / "secrets.yaml"
        secrets_path.write_text("deepseek_api_key: deepseek-secret-key\n", encoding="utf-8")
        monkeypatch.setenv("NUDGE_SECRETS_PATH", str(secrets_path))

        provider = create_provider({"provider": "deepseek"})

        assert provider.api_key == "deepseek-secret-key"


def test_diagnose_backup_secrets_missing(monkeypatch, tmp_path):
    path = tmp_path / "missing-secrets.yaml"
    monkeypatch.setenv("NUDGE_SECRETS_PATH", str(path))

    diag = llm_module.diagnose_backup_secrets({})

    assert diag.status == "missing"
    assert diag.path == path
    assert "not found" in diag.message
    assert str(path) not in diag.message


def test_diagnose_backup_secrets_loaded_without_leaking_values(monkeypatch, tmp_path):
    path = tmp_path / "secrets.yaml"
    path.write_text("dashscope_api_key: super-secret-value\n", encoding="utf-8")
    monkeypatch.setenv("NUDGE_SECRETS_PATH", str(path))

    diag = llm_module.diagnose_backup_secrets({})

    assert diag.status == "loaded"
    assert "1 key" in diag.message
    assert str(path) not in diag.message
    assert "super-secret-value" not in diag.message
    assert "super-secret-value" not in diag.hint


def test_diagnose_backup_secrets_unreadable_preserves_runtime_compat(monkeypatch, tmp_path):
    path = tmp_path / "secrets.yaml"
    monkeypatch.setenv("NUDGE_SECRETS_PATH", str(path))

    def raise_permission_error(self, encoding=None):
        if self == path:
            raise PermissionError("denied secret contents")
        return original_read_text(self, encoding=encoding)

    original_read_text = llm_module.Path.read_text
    monkeypatch.setattr(llm_module.Path, "read_text", raise_permission_error)

    diag = llm_module.diagnose_backup_secrets({})

    assert diag.status == "unreadable"
    assert "PermissionError" in diag.message
    assert str(path) not in diag.message
    assert "denied secret contents" not in diag.message
    assert llm_module._load_backup_secrets({}) == {}


def test_diagnose_backup_secrets_decode_error_preserves_runtime_compat(monkeypatch, tmp_path):
    path = tmp_path / "secrets.yaml"
    path.write_bytes(b"\xff\xfe\x00")
    monkeypatch.setenv("NUDGE_SECRETS_PATH", str(path))

    diag = llm_module.diagnose_backup_secrets({})

    assert diag.status == "decode_error"
    assert "UTF-8" in diag.message
    assert str(path) not in diag.message
    assert llm_module._load_backup_secrets({}) == {}


def test_openai_compatible_provider_passes_request_timeout_to_client(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
                    )
                )
            )

    fake_openai = SimpleNamespace(
        OpenAI=FakeOpenAI,
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        RateLimitError=type("RateLimitError", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    provider = OpenAICompatibleProvider(api_key="test", base_url="https://example.test/v1")
    assert provider.call("system", "message", "model", timeout=10.0, max_retries=0) == "ok"
    assert captured["timeout"] == 10.0
    assert captured["max_retries"] == 0


def test_anthropic_provider_passes_request_timeout_to_client(monkeypatch):
    captured = {}

    class FakeAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.messages = SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(content=[SimpleNamespace(text="ok")])
            )

    fake_anthropic = SimpleNamespace(
        Anthropic=FakeAnthropic,
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
        RateLimitError=type("RateLimitError", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    provider = AnthropicProvider(api_key="test")
    assert provider.call("system", "message", "model", timeout=10.0, max_retries=0) == "ok"
    assert captured["timeout"] == 10.0
    assert captured["max_retries"] == 0


def test_ollama_provider_disables_sdk_retries_for_bounded_call(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
                    )
                )
            )

    fake_openai = SimpleNamespace(
        OpenAI=FakeOpenAI,
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    provider = OllamaProvider()
    assert provider.call("system", "message", "model", timeout=10.0, max_retries=0) == "ok"
    assert captured["timeout"] == 10.0
    assert captured["max_retries"] == 0


class TestGetModelForTask:
    def test_defaults(self):
        assert get_model_for_task("fast") == DEFAULT_LLM_CONFIG["models"]["fast"]
        assert get_model_for_task("default") == DEFAULT_LLM_CONFIG["models"]["default"]
        assert get_model_for_task("strong") == DEFAULT_LLM_CONFIG["models"]["strong"]

    def test_custom_models(self):
        config = {
            "models": {
                "fast": "gpt-4o-mini",
                "default": "gpt-4o",
                "strong": "gpt-4o",
            }
        }
        assert get_model_for_task("fast", config) == "gpt-4o-mini"
        assert get_model_for_task("strong", config) == "gpt-4o"

    def test_unknown_task_falls_back_to_default(self):
        config = {"models": {"default": "my-model", "fast": "fast-model"}}
        assert get_model_for_task("unknown_task", config) == "my-model"

    def test_no_config(self):
        # Should not crash, uses defaults
        model = get_model_for_task("fast", None)
        assert model is not None
