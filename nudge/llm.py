"""LLM provider abstraction — supports Anthropic, OpenAI, and OpenAI-compatible APIs."""

import os
from pathlib import Path

from nudge.config import DEFAULT_LLM_CONFIG, DEFAULT_SECRETS_PATH

_PROVIDERS = {}  # provider_name -> class


class LLMError(Exception):
    """Raised when an LLM call fails."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        auth_error: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.auth_error = auth_error
        self.status_code = status_code


class LLMTransientError(LLMError):
    """Raised when an LLM call failed for a retryable transient reason."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message, retryable=True, status_code=status_code)


class LLMAuthenticationError(LLMError):
    """Raised when an LLM provider rejected credentials."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message, retryable=False, auth_error=True, status_code=status_code)


class LLMProvider:
    """Base class for LLM providers."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key
        self.base_url = base_url

    def call(self, system: str, user_message: str, model: str,
             max_tokens: int = 1024, temperature: float = 0) -> str:
        """Make an LLM call. Returns the response text."""
        raise NotImplementedError

    def __init_subclass__(cls, provider_name: str = None, **kwargs):
        super().__init_subclass__(**kwargs)
        if provider_name:
            _PROVIDERS[provider_name] = cls


class AnthropicProvider(LLMProvider, provider_name="anthropic"):
    """Anthropic Claude API."""

    def call(self, system, user_message, model, max_tokens=1024, temperature=0):
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )
            if not response.content:
                raise LLMError("LLM returned empty response")
            return response.content[0].text.strip()
        except LLMError:
            raise
        except anthropic.AuthenticationError:
            raise LLMAuthenticationError(
                "Invalid Anthropic API key. Set ANTHROPIC_API_KEY or configure in config.toml."
            )
        except anthropic.APIConnectionError:
            raise LLMTransientError("Cannot connect to Anthropic API. Check your network.")
        except anthropic.RateLimitError:
            raise LLMTransientError("Anthropic API rate limit exceeded. Try again later.")
        except Exception as exc:
            raise _llm_error_from_exception(exc) from exc


class OpenAICompatibleProvider(LLMProvider, provider_name="openai"):
    """OpenAI and any OpenAI-compatible API (DeepSeek, Moonshot, Together, etc.)."""

    def call(self, system, user_message, model, max_tokens=1024, temperature=0):
        from openai import OpenAI, APIConnectionError, AuthenticationError, RateLimitError
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
            )
            content = response.choices[0].message.content
            if not content:
                raise LLMError("LLM returned empty response")
            return content.strip()
        except LLMError:
            raise
        except AuthenticationError:
            raise LLMAuthenticationError(
                "Invalid API key. Check your config.toml [llm] section."
            )
        except APIConnectionError:
            raise LLMTransientError(
                f"Cannot connect to {self.base_url or 'OpenAI API'}. Check your network."
            )
        except RateLimitError:
            raise LLMTransientError("API rate limit exceeded. Try again later.")
        except Exception as exc:
            raise _llm_error_from_exception(exc) from exc


class OllamaProvider(LLMProvider, provider_name="ollama"):
    """Ollama local models — no API key needed."""

    def __init__(self, api_key=None, base_url=None):
        super().__init__(api_key=api_key, base_url=base_url or "http://localhost:11434/v1")

    def call(self, system, user_message, model, max_tokens=1024, temperature=0):
        from openai import OpenAI, APIConnectionError
        client = OpenAI(api_key="ollama", base_url=self.base_url)
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
            )
            content = response.choices[0].message.content
            if not content:
                raise LLMError("LLM returned empty response")
            return content.strip()
        except APIConnectionError:
            raise LLMTransientError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Is Ollama running? Try: ollama serve"
            )
        except Exception as exc:
            raise _llm_error_from_exception(exc) from exc


class DeepSeekProvider(OpenAICompatibleProvider, provider_name="deepseek"):
    """DeepSeek API using the OpenAI-compatible chat completions format."""

    DEFAULT_BASE_URL = "https://api.deepseek.com/v1"

    def __init__(self, api_key=None, base_url=None):
        super().__init__(api_key=api_key, base_url=base_url or self.DEFAULT_BASE_URL)


class QwenProvider(OpenAICompatibleProvider, provider_name="qwen"):
    """Alibaba Cloud DashScope / 通义千问 using the OpenAI-compatible endpoint."""

    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def __init__(self, api_key=None, base_url=None):
        super().__init__(api_key=api_key, base_url=base_url or self.DEFAULT_BASE_URL)


class DashScopeProvider(QwenProvider, provider_name="dashscope"):
    """Alias for QwenProvider; DashScope is the API platform for Qwen models."""


# ── Factory ──────────────────────────────────────────────────────

# Env var names per provider, in priority order.
_PROVIDER_ENV_KEYS = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "qwen": ("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
    "dashscope": ("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
}

# Top-level keys accepted in secrets.yaml, in priority order. Keys are matched
# case-insensitively after parsing. The parser only supports simple
# "key: value" entries so we do not need to add PyYAML as a runtime dependency.
_PROVIDER_SECRET_KEYS = {
    "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
    "deepseek": ("deepseek_api_key", "DEEPSEEK_API_KEY"),
    "qwen": (
        "dashscope_api_key",
        "qwen_api_key",
        "DASHSCOPE_API_KEY",
        "QWEN_API_KEY",
    ),
    "dashscope": (
        "dashscope_api_key",
        "qwen_api_key",
        "DASHSCOPE_API_KEY",
        "QWEN_API_KEY",
    ),
}


def _strip_yaml_scalar(value: str) -> str:
    """Extract a simple one-line YAML scalar value.

    This intentionally supports only the secrets.yaml style used by local
    projects: top-level ``key: value`` pairs. Complex YAML is ignored rather than
    requiring a new dependency or risking surprising parsing behavior.
    """
    value = value.strip()
    if not value or value in {"|", ">"}:
        return ""

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()

    # Treat " #..." as a comment delimiter for unquoted scalars.
    comment_index = value.find(" #")
    if comment_index != -1:
        value = value[:comment_index]
    return value.strip()


def _get_secrets_path(config: dict | None = None) -> Path:
    """Resolve the local secrets.yaml path without ever creating it."""
    config = config or {}
    configured = config.get("secrets_path")
    if configured:
        return Path(os.path.expanduser(str(configured)))

    for env_key in ("NUDGE_SECRETS_PATH", "EMAIL_SECRETS_PATH"):
        env_path = os.environ.get(env_key)
        if env_path:
            return Path(os.path.expanduser(env_path))

    return DEFAULT_SECRETS_PATH


def _load_backup_secrets(config: dict | None = None) -> dict[str, str]:
    """Load simple key/value secrets from the shared local backup file.

    Missing, unreadable, or complex files produce an empty dict. Secret values
    must never be logged or surfaced to CLI output.
    """
    path = _get_secrets_path(config)
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}

    secrets = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or key.startswith("#"):
            continue
        value = _strip_yaml_scalar(value)
        if value:
            secrets[key.lower()] = value
    return secrets


def _resolve_api_key(provider_name: str, config: dict) -> str:
    """Resolve API key using config > provider env > secrets file > generic env."""
    if config.get("api_key"):
        return config["api_key"]

    if provider_name not in _PROVIDER_ENV_KEYS:
        return ""

    for env_key in _PROVIDER_ENV_KEYS.get(provider_name, ()):
        value = os.environ.get(env_key)
        if value:
            return value

    secrets = _load_backup_secrets(config)
    for secret_key in _PROVIDER_SECRET_KEYS.get(provider_name, ()):
        value = secrets.get(secret_key.lower())
        if value:
            return value

    return os.environ.get("LLM_API_KEY", "") or secrets.get("llm_api_key", "")


def create_provider(config: dict | None = None) -> LLMProvider:
    """Create an LLM provider from config.

    Config shape (from config.toml [llm]):
        provider = "qwen"       # or "dashscope", "openai", "anthropic", "deepseek", "ollama"
        api_key = "..."         # optional, prefer env var / secrets.yaml
        base_url = "..."        # optional, for custom endpoints
        model = "qwen-plus"     # optional default model
    """
    if config is None:
        config = {}

    provider_name = config.get("provider", DEFAULT_LLM_CONFIG["provider"])
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise LLMError(
            f"Unknown LLM provider: '{provider_name}'. "
            f"Available: {', '.join(_PROVIDERS.keys())}"
        )

    api_key = _resolve_api_key(provider_name, config)
    base_url = config.get("base_url")

    return provider_cls(api_key=api_key, base_url=base_url)


def _llm_error_from_exception(exc: Exception) -> LLMError:
    """Convert SDK exceptions with HTTP status metadata into LLMError."""
    status_code = _status_code_from_exception(exc)
    message = str(exc) or exc.__class__.__name__
    if status_code in (401, 403):
        return LLMAuthenticationError(message, status_code=status_code)
    if status_code is not None and status_code >= 500:
        return LLMTransientError(message, status_code=status_code)
    return LLMError(message, status_code=status_code)


def _status_code_from_exception(exc: Exception) -> int | None:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def get_model_for_task(task: str, config: dict | None = None) -> str:
    """Get the model name for a specific task type.

    Task types: 'default', 'fast', 'strong'
    - fast: simple tasks (parsing input, check-in, coaching messages)
    - strong: complex tasks (plan generation, evaluation, personalization)
    - default: everything else (briefing, chat)
    """
    if config is None:
        config = {}
    models = config.get("models", DEFAULT_LLM_CONFIG["models"])
    return models.get(task, models.get("default", DEFAULT_LLM_CONFIG["models"]["default"]))


def get_max_tokens_for_task(task: str, config: dict | None = None) -> int:
    """Get max_tokens for a task, using task override before LLM default."""
    if config is None:
        config = {}

    default = _positive_int_or_default(
        config.get("max_tokens"),
        DEFAULT_LLM_CONFIG["max_tokens"],
    )
    task_config = _get_task_config(task, config)
    return _positive_int_or_default(task_config.get("max_tokens"), default)


def get_retries_for_task(task: str, config: dict | None = None) -> int:
    """Get retry count for a task."""
    if config is None:
        config = {}

    default = _non_negative_int_or_default(
        config.get("retries"),
        DEFAULT_LLM_CONFIG["retries"],
    )
    task_config = _get_task_config(task, config)
    return _non_negative_int_or_default(task_config.get("retries"), default)


def get_retry_backoff_seconds_for_task(task: str, config: dict | None = None) -> float:
    """Get initial retry backoff seconds for a task."""
    if config is None:
        config = {}

    default = _positive_float_or_default(
        config.get("retry_backoff_seconds"),
        DEFAULT_LLM_CONFIG["retry_backoff_seconds"],
    )
    task_config = _get_task_config(task, config)
    return _positive_float_or_default(task_config.get("retry_backoff_seconds"), default)


def _get_task_config(task: str, config: dict) -> dict:
    tasks = config.get("tasks", DEFAULT_LLM_CONFIG["tasks"])
    if not isinstance(tasks, dict):
        return {}
    task_config = tasks.get(task, {})
    return task_config if isinstance(task_config, dict) else {}


def _positive_int_or_default(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _non_negative_int_or_default(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _positive_float_or_default(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
