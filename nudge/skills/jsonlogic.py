"""Safe JSONLogic subset for deterministic Skill rules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


ALLOWED_OPERATORS = {
    "==",
    "!=",
    ">",
    ">=",
    "<",
    "<=",
    "and",
    "or",
    "!",
    "in",
    "var",
    "missing",
    "missing_some",
}

_DANGEROUS_PATH_PARTS = {
    "__class__",
    "__dict__",
    "__globals__",
    "__mro__",
    "__proto__",
    "constructor",
    "prototype",
}
_MISSING = object()


class JsonLogicError(ValueError):
    """Raised when a rule is invalid or cannot be evaluated safely."""


@dataclass(frozen=True)
class _PathPart:
    name: str
    index: int | None = None


def _path_parts(path: str) -> list[_PathPart]:
    if not isinstance(path, str) or not path:
        raise JsonLogicError(f"Invalid var path: {path!r}")
    if path.startswith("/") or ".." in path:
        raise JsonLogicError(f"Dangerous var path: {path}")

    parts: list[_PathPart] = []
    for raw in path.split("."):
        if not raw:
            raise JsonLogicError(f"Invalid var path: {path}")

        name = raw
        index: int | None = None
        if raw.endswith("]") and "[" in raw:
            name, index_text = raw[:-1].split("[", 1)
            if not name or not index_text.isdigit():
                raise JsonLogicError(f"Invalid var path: {path}")
            index = int(index_text)

        if name in _DANGEROUS_PATH_PARTS or name.startswith("__"):
            raise JsonLogicError(f"Dangerous var path part: {name}")
        parts.append(_PathPart(name=name, index=index))
    return parts


def _resolve_var(path: str, data: Mapping[str, Any], default: Any = _MISSING) -> Any:
    current: Any = data
    for part in _path_parts(path):
        if isinstance(current, Mapping):
            if part.name not in current:
                return default
            current = current[part.name]
        else:
            return default

        if part.index is not None:
            if not isinstance(current, Sequence) or isinstance(current, (str, bytes)):
                return default
            if part.index >= len(current):
                return default
            current = current[part.index]
    return current


def _as_args(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [value]


def _compare(op: str, args: list[Any], data: Mapping[str, Any]) -> bool:
    if len(args) != 2:
        raise JsonLogicError(f"Operator {op} expects exactly 2 arguments")
    left = evaluate(args[0], data)
    right = evaluate(args[1], data)
    try:
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
    except TypeError:
        return False
    raise JsonLogicError(f"Unsupported operator: {op}")


def _missing(paths: Any, data: Mapping[str, Any]) -> list[str]:
    if isinstance(paths, str):
        candidates = [paths]
    elif isinstance(paths, list):
        candidates = paths
    else:
        raise JsonLogicError("missing expects a string or list of strings")

    missing = []
    for candidate in candidates:
        if not isinstance(candidate, str):
            raise JsonLogicError("missing paths must be strings")
        if _resolve_var(candidate, data, _MISSING) is _MISSING:
            missing.append(candidate)
    return missing


def _validate_missing_paths(paths: Any) -> None:
    if isinstance(paths, str):
        _path_parts(paths)
        return
    if not isinstance(paths, list):
        raise JsonLogicError("missing expects a string or list of strings")
    for path in paths:
        if not isinstance(path, str):
            raise JsonLogicError("missing paths must be strings")
        _path_parts(path)


def _validate_missing_some_args(args: list[Any]) -> None:
    if len(args) != 2 or not isinstance(args[0], int) or isinstance(args[0], bool):
        raise JsonLogicError("missing_some expects [minimum_required, paths]")
    if args[0] < 0:
        raise JsonLogicError("missing_some minimum_required must be non-negative")
    if not isinstance(args[1], list):
        raise JsonLogicError("missing_some paths must be a list of strings")
    _validate_missing_paths(args[1])


def evaluate(rule: Any, data: Mapping[str, Any]) -> Any:
    """Evaluate a JSONLogic rule using a deliberately small safe subset."""
    if not isinstance(rule, Mapping):
        if isinstance(rule, list):
            return [evaluate(item, data) for item in rule]
        return rule

    if len(rule) != 1:
        raise JsonLogicError("JSONLogic rule must contain exactly one operator")

    op, raw_args = next(iter(rule.items()))
    if op not in ALLOWED_OPERATORS:
        raise JsonLogicError(f"Unsupported JSONLogic operator: {op}")

    if op == "var":
        if isinstance(raw_args, list):
            if not raw_args:
                raise JsonLogicError("var expects a path")
            path = raw_args[0]
            default = raw_args[1] if len(raw_args) > 1 else None
        else:
            path = raw_args
            default = None
        if not isinstance(path, str):
            raise JsonLogicError("var path must be a string")
        return _resolve_var(path, data, default)

    args = _as_args(raw_args)

    if op in {"==", "!=", ">", ">=", "<", "<="}:
        return _compare(op, args, data)
    if op == "and":
        return all(bool(evaluate(arg, data)) for arg in args)
    if op == "or":
        return any(bool(evaluate(arg, data)) for arg in args)
    if op == "!":
        if len(args) != 1:
            raise JsonLogicError("! expects exactly 1 argument")
        return not bool(evaluate(args[0], data))
    if op == "in":
        if len(args) != 2:
            raise JsonLogicError("in expects exactly 2 arguments")
        needle = evaluate(args[0], data)
        haystack = evaluate(args[1], data)
        if haystack is None:
            return False
        try:
            return needle in haystack
        except TypeError:
            return False
    if op == "missing":
        return _missing(raw_args, data)
    if op == "missing_some":
        _validate_missing_some_args(args)
        required = args[0]
        missing = _missing(args[1], data)
        total = len(args[1])
        present = total - len(missing)
        return [] if present >= required else missing

    raise JsonLogicError(f"Unsupported JSONLogic operator: {op}")


def validate_rule(rule: Any) -> None:
    """Validate operator names and dangerous var paths without requiring data."""
    if isinstance(rule, list):
        for item in rule:
            validate_rule(item)
        return
    if not isinstance(rule, Mapping):
        return
    if len(rule) != 1:
        raise JsonLogicError("JSONLogic rule must contain exactly one operator")

    op, raw_args = next(iter(rule.items()))
    if op not in ALLOWED_OPERATORS:
        raise JsonLogicError(f"Unsupported JSONLogic operator: {op}")

    if op == "var":
        path = raw_args[0] if isinstance(raw_args, list) and raw_args else raw_args
        if not isinstance(path, str):
            raise JsonLogicError("var path must be a string")
        _path_parts(path)
        return
    if op == "missing":
        _validate_missing_paths(raw_args)
        return
    if op == "missing_some":
        _validate_missing_some_args(_as_args(raw_args))
        return

    for arg in _as_args(raw_args):
        validate_rule(arg)
