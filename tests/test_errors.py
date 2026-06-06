from nudge.errors import classify_llm_error


def test_classify_llm_error_invalid_json_remains_json_error():
    report = classify_llm_error("LLM returned invalid JSON after retry: not-json")

    assert report.code == "LLM_INVALID_JSON"


def test_classify_llm_error_schema_json_remains_json_error():
    report = classify_llm_error("JSON schema validation failed: missing type")

    assert report.code == "LLM_INVALID_JSON"


def test_classify_llm_error_does_not_treat_json_endpoint_network_error_as_invalid_json():
    report = classify_llm_error("Failed to call json endpoint: connection reset")

    assert report.code == "LLM_FAILED"


def test_classify_llm_error_does_not_treat_json_api_connection_reset_as_invalid_json():
    report = classify_llm_error("json api connection reset by peer")

    assert report.code == "LLM_FAILED"


def test_classify_llm_error_authentication_remains_api_key_error():
    report = classify_llm_error("OpenAI API key invalid for json endpoint")

    assert report.code == "LLM_API_KEY_ERROR"
