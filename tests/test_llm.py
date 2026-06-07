import nudge.llm as llm


def test_get_max_tokens_for_task_defaults_to_1024():
    assert llm.get_max_tokens_for_task("default", {}) == 1024


def test_get_max_tokens_for_task_uses_llm_default_override():
    assert llm.get_max_tokens_for_task("default", {"max_tokens": 2048}) == 2048


def test_get_max_tokens_for_task_uses_task_override_before_default():
    config = {
        "max_tokens": 2048,
        "tasks": {
            "fast": {"max_tokens": 512},
        },
    }

    assert llm.get_max_tokens_for_task("fast", config) == 512


class StatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def test_llm_error_from_5xx_status_is_retryable_transient_error():
    error = llm._llm_error_from_exception(StatusError(503))

    assert isinstance(error, llm.LLMTransientError)
    assert error.retryable is True
    assert error.status_code == 503


def test_llm_error_from_auth_status_is_not_retryable():
    error = llm._llm_error_from_exception(StatusError(401))

    assert isinstance(error, llm.LLMAuthenticationError)
    assert error.retryable is False
    assert error.auth_error is True
