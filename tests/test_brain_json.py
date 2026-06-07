import json

import pytest

import nudge.brain as brain
import nudge.llm as llm
from nudge.brain import PARSE_SYSTEM, parse_json_response


def test_parse_system_documents_note_action_schema():
    assert '"type": "note"' in PARSE_SYSTEM
    assert '"title": "Note title"' in PARSE_SYSTEM
    assert '"body": "Note body"' in PARSE_SYSTEM
    assert "Only return valid JSON array" in PARSE_SYSTEM


def test_parse_json_response_accepts_bare_json_array():
    assert parse_json_response('[{"type": "reminder", "name": "买牛奶"}]') == [
        {"type": "reminder", "name": "买牛奶"}
    ]


def test_parse_json_response_accepts_json_markdown_fence():
    raw = """```json
[{"type": "alarm", "time": "07:30"}]
```"""

    assert parse_json_response(raw) == [{"type": "alarm", "time": "07:30"}]


@pytest.mark.parametrize(
    "raw",
    [
        """```json
{"status": "done"}
```

""",
        """```json
{"status": "done"}
```

解析完成。""",
    ],
)
def test_parse_json_response_accepts_text_after_json_markdown_fence(raw):
    assert parse_json_response(raw) == {"status": "done"}


def test_parse_json_response_uses_first_json_fence_when_multiple_blocks_exist():
    raw = """```json
{"status": "done"}
```

```text
ignored
```"""

    assert parse_json_response(raw) == {"status": "done"}


def test_parse_json_response_keeps_invalid_json_decode_error():
    raw = """```json
{"status": "done",
```

说明文字不应吞掉真正的 JSON 错误。"""

    with pytest.raises(json.JSONDecodeError):
        parse_json_response(raw)


class RecordingProvider:
    def __init__(self, failures=None):
        self.failures = list(failures or [])
        self.calls = []

    def call(self, system, user_message, model, max_tokens=1024, temperature=0):
        self.calls.append(
            {
                "system": system,
                "user_message": user_message,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if self.failures:
            raise self.failures.pop(0)
        return "ok"


def test_call_passes_task_max_tokens_to_provider(monkeypatch):
    provider = RecordingProvider()
    monkeypatch.setattr(brain, "_provider", provider)
    monkeypatch.setattr(
        brain,
        "_llm_config",
        {
            "models": {"default": "default-model", "fast": "fast-model"},
            "max_tokens": 2048,
            "tasks": {"fast": {"max_tokens": 512}},
        },
    )

    assert brain._call("system", "message", task="fast") == "ok"

    assert provider.calls == [
        {
            "system": "system",
            "user_message": "message",
            "model": "fast-model",
            "max_tokens": 512,
            "temperature": 0,
        }
    ]


def test_call_retries_transient_llm_error_with_injected_sleeper(monkeypatch):
    provider = RecordingProvider([llm.LLMTransientError("temporary 503")])
    sleeps = []
    monkeypatch.setattr(brain, "_provider", provider)
    monkeypatch.setattr(brain, "_llm_config", {"retries": 1, "retry_backoff_seconds": 0.25})

    assert brain._call("system", "message", sleeper=sleeps.append) == "ok"

    assert len(provider.calls) == 2
    assert sleeps == [0.25]


def test_call_does_not_retry_authentication_error(monkeypatch):
    provider = RecordingProvider([llm.LLMAuthenticationError("invalid api key")])
    sleeps = []
    monkeypatch.setattr(brain, "_provider", provider)
    monkeypatch.setattr(brain, "_llm_config", {"retries": 3, "retry_backoff_seconds": 0.01})

    with pytest.raises(llm.LLMAuthenticationError):
        brain._call("system", "message", sleeper=sleeps.append)

    assert len(provider.calls) == 1
    assert sleeps == []
