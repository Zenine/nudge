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
