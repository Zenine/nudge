import pytest

from nudge.skills.jsonlogic import JsonLogicError, evaluate, validate_rule


def test_evaluate_common_operators_with_nested_vars_and_arrays():
    data = {
        "metrics": {"effort": 8, "sleep": 7},
        "tags": ["strength", "recovery"],
        "items": [{"name": "warmup"}, {"name": "main"}],
    }

    rule = {
        "and": [
            {">=": [{"var": "metrics.effort"}, 7]},
            {"<": [{"var": "metrics.sleep"}, 8]},
            {"in": ["strength", {"var": "tags"}]},
            {"==": [{"var": "items[1].name"}, "main"]},
            {"!": {"missing": ["metrics.effort", "items[0].name"]}},
        ]
    }

    assert evaluate(rule, data) is True


def test_missing_and_missing_some_handle_defaults_and_missing_fields():
    data = {"profile": {"name": "Ada"}, "scores": [10]}

    assert evaluate({"var": ["profile.age", 42]}, data) == 42
    assert evaluate({"missing": ["profile.name", "profile.age", "scores[1]"]}, data) == [
        "profile.age",
        "scores[1]",
    ]
    assert evaluate({"missing_some": [1, ["profile.name", "profile.age"]]}, data) == []
    assert evaluate({"missing_some": [2, ["profile.name", "profile.age"]]}, data) == ["profile.age"]


def test_type_mismatches_are_safe_false_or_defaults():
    data = {"value": "8", "items": "not-a-list"}

    assert evaluate({">": [{"var": "value"}, 7]}, data) is False
    assert evaluate({"in": ["x", 123]}, data) is False
    assert evaluate({"var": ["items[0].name", "fallback"]}, data) == "fallback"


@pytest.mark.parametrize(
    "rule",
    [
        {"var": "__class__"},
        {"missing": ["safe", "__dict__"]},
        {"missing_some": [1, ["safe", "constructor.prototype"]]},
    ],
)
def test_validate_rule_rejects_dangerous_paths_in_all_path_operators(rule):
    with pytest.raises(JsonLogicError):
        validate_rule(rule)


@pytest.mark.parametrize(
    "rule",
    [
        {"missing": ["safe", 1]},
        {"missing_some": [True, ["safe"]]},
        {"missing_some": [1, "safe"]},
        {"missing_some": [-1, ["safe"]]},
    ],
)
def test_validate_rule_rejects_invalid_missing_arguments(rule):
    with pytest.raises(JsonLogicError):
        validate_rule(rule)


def test_evaluate_comparison_and_var_lookup():
    data = {"assessment": {"current_frequency": "never"}}

    assert evaluate({"==": [{"var": "assessment.current_frequency"}, "never"]}, data) is True
    assert evaluate({"!=": [{"var": "assessment.current_frequency"}, "never"]}, data) is False


def test_evaluate_logical_and_collection_operators():
    data = {
        "assessment": {"injuries": ["lower_back"], "daily_minutes": 60},
        "history": {"completion_rate_14d": 0.85},
    }

    rule = {
        "and": [
            {"in": ["lower_back", {"var": "assessment.injuries"}]},
            {">=": [{"var": "assessment.daily_minutes"}, 45]},
            {"<": [{"var": "history.completion_rate_14d"}, 0.9]},
        ]
    }

    assert evaluate(rule, data) is True


def test_evaluate_missing_and_missing_some():
    data = {"assessment": {"baseline": "zero"}}

    assert evaluate({"missing": ["assessment.baseline", "assessment.goal"]}, data) == [
        "assessment.goal"
    ]
    assert evaluate({"missing_some": [2, ["assessment.baseline", "assessment.goal"]]}, data) == [
        "assessment.goal"
    ]
    assert evaluate({"missing_some": [1, ["assessment.baseline", "assessment.goal"]]}, data) == []


def test_evaluate_rejects_unknown_operator():
    with pytest.raises(JsonLogicError) as exc_info:
        evaluate({"eval": "assessment.baseline == 'zero'"}, {"assessment": {"baseline": "zero"}})

    assert "eval" in str(exc_info.value)


def test_evaluate_rejects_dangerous_var_path():
    with pytest.raises(JsonLogicError) as exc_info:
        evaluate({"var": "__class__.__mro__"}, {})

    assert "__class__" in str(exc_info.value)


def test_evaluate_missing_some_rejects_bool_minimum():
    # ``isinstance(True, int)`` is True, so a bare int check let a boolean pass
    # as minimum_required. It must be rejected as a bad argument shape.
    with pytest.raises(JsonLogicError):
        evaluate({"missing_some": [True, ["assessment.baseline"]]}, {"assessment": {}})
