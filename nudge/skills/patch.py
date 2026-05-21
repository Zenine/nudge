"""Deterministic patch engine for Skill personalization and adaptation."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from nudge.skills.jsonlogic import evaluate, validate_rule


ALLOWED_PATCH_OPS = {
    "set",
    "add",
    "multiply",
    "clamp",
    "replace",
    "remove",
    "insert",
    "tag",
    "validate",
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


class PatchError(ValueError):
    """Raised when a Skill patch is unsafe or cannot be applied."""


@dataclass(frozen=True)
class PathToken:
    """One safe dot-path token."""

    name: str
    wildcard: bool = False
    index: int | None = None


def validate_path(path: str) -> list[PathToken]:
    """Parse and validate a safe Skill patch path."""
    if not isinstance(path, str) or not path:
        raise PatchError(f"Invalid patch path: {path!r}")
    if path.startswith("/") or ".." in path:
        raise PatchError(f"Dangerous patch path: {path}")

    tokens: list[PathToken] = []
    for raw in path.split("."):
        if not raw:
            raise PatchError(f"Invalid patch path: {path}")

        wildcard = False
        index: int | None = None
        name = raw
        if raw.endswith("[]"):
            wildcard = True
            name = raw[:-2]
        elif raw.endswith("]") and "[" in raw:
            name, index_text = raw[:-1].split("[", 1)
            if not name or not index_text.isdigit():
                raise PatchError(f"Invalid patch path: {path}")
            index = int(index_text)

        if not name or name in _DANGEROUS_PATH_PARTS or name.startswith("__"):
            raise PatchError(f"Dangerous patch path part: {name}")
        tokens.append(PathToken(name=name, wildcard=wildcard, index=index))

    return tokens


def _evaluation_data(target: Mapping[str, Any], context: Mapping[str, Any] | None, item: Any = None) -> dict:
    data = deepcopy(dict(target))
    if context:
        data.update(deepcopy(dict(context)))
    if item is not None:
        data["item"] = item
    return data


def _get_child(current: Any, token: PathToken) -> Any:
    if not isinstance(current, Mapping) or token.name not in current:
        raise PatchError(f"Path not found: {token.name}")
    value = current[token.name]
    if token.index is not None:
        if not isinstance(value, list) or token.index >= len(value):
            raise PatchError(f"List index not found: {token.name}[{token.index}]")
        return value[token.index]
    return value


def _ensure_child(current: MutableMapping[str, Any], token: PathToken, next_token: PathToken | None) -> Any:
    if token.name not in current:
        current[token.name] = [] if next_token and (next_token.wildcard or next_token.index is not None) else {}
    value = current[token.name]
    if token.index is not None:
        if not isinstance(value, list):
            raise PatchError(f"Path part is not a list: {token.name}")
        while len(value) <= token.index:
            value.append({})
        return value[token.index]
    return value


def _get_value(target: Mapping[str, Any], tokens: list[PathToken]) -> Any:
    current: Any = target
    for token in tokens:
        if token.wildcard:
            raise PatchError("Wildcard paths are only supported by replace/remove")
        current = _get_child(current, token)
    return current


def _set_value(target: MutableMapping[str, Any], tokens: list[PathToken], value: Any) -> None:
    if any(token.wildcard for token in tokens):
        raise PatchError("Wildcard paths are not supported by set")
    current: Any = target
    for index, token in enumerate(tokens[:-1]):
        if not isinstance(current, MutableMapping):
            raise PatchError(f"Cannot create child under non-object path part: {token.name}")
        current = _ensure_child(current, token, tokens[index + 1])

    last = tokens[-1]
    if not isinstance(current, MutableMapping):
        raise PatchError(f"Cannot set value under non-object path part: {last.name}")
    if last.index is not None:
        sequence = current.setdefault(last.name, [])
        if not isinstance(sequence, list):
            raise PatchError(f"Path part is not a list: {last.name}")
        while len(sequence) <= last.index:
            sequence.append(None)
        sequence[last.index] = value
    else:
        current[last.name] = value


def _ensure_list_at_path(target: MutableMapping[str, Any], tokens: list[PathToken]) -> list:
    if any(token.wildcard for token in tokens):
        raise PatchError("Wildcard paths are not supported by insert")
    current: Any = target
    for index, token in enumerate(tokens[:-1]):
        if not isinstance(current, MutableMapping):
            raise PatchError(f"Cannot create child under non-object path part: {token.name}")
        current = _ensure_child(current, token, tokens[index + 1])

    last = tokens[-1]
    if not isinstance(current, MutableMapping):
        raise PatchError(f"Cannot create list under non-object path part: {last.name}")
    if last.index is not None:
        raise PatchError("insert path must point to a list, not a list item")
    current.setdefault(last.name, [])
    if not isinstance(current[last.name], list):
        raise PatchError("Patch path must point to a list")
    return current[last.name]


def _iter_wildcard_items(current: Any, tokens: list[PathToken]):
    if not tokens:
        return
    token, rest = tokens[0], tokens[1:]
    value = _get_child(current, PathToken(token.name, index=token.index))
    if token.wildcard:
        if not isinstance(value, list):
            raise PatchError(f"Wildcard path part is not a list: {token.name}")
        for index, item in enumerate(value):
            if rest:
                yield from _iter_wildcard_items(item, rest)
            else:
                yield value, index, item
    else:
        if rest:
            yield from _iter_wildcard_items(value, rest)


def _matches_where(where: Any, target: Mapping[str, Any], context: Mapping[str, Any] | None, item: Any) -> bool:
    if where is None:
        return True
    validate_rule(where)
    return bool(evaluate(where, _evaluation_data(target, context, item=item)))


def _require_path(patch: Mapping[str, Any]) -> list[PathToken]:
    if "path" not in patch:
        raise PatchError(f"Patch op {patch.get('op')} requires path")
    return validate_path(patch["path"])


def apply_patch(target: MutableMapping[str, Any], patch: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> None:
    """Apply one deterministic patch in-place."""
    op = patch.get("op")
    if op not in ALLOWED_PATCH_OPS:
        raise PatchError(f"Unsupported patch op: {op}")

    if op == "tag":
        tag = patch.get("value")
        if not isinstance(tag, str) or not tag:
            raise PatchError("tag patch requires a non-empty string value")
        tags = target.setdefault("_tags", [])
        if not isinstance(tags, list):
            raise PatchError("_tags must be a list")
        if tag not in tags:
            tags.append(tag)
        return

    if op == "validate":
        rule = patch.get("rule") or patch.get("when")
        if rule is None:
            raise PatchError("validate patch requires rule")
        validate_rule(rule)
        if not bool(evaluate(rule, _evaluation_data(target, context))):
            raise PatchError(str(patch.get("message") or "Skill validation patch failed"))
        return

    tokens = _require_path(patch)

    if op == "set":
        _set_value(target, tokens, deepcopy(patch.get("value")))
    elif op == "add":
        value = _get_value(target, tokens)
        delta = patch.get("value")
        if not isinstance(value, (int, float)) or not isinstance(delta, (int, float)):
            raise PatchError("add patch requires numeric current value and numeric value")
        _set_value(target, tokens, value + delta)
    elif op == "multiply":
        value = _get_value(target, tokens)
        multiplier = patch.get("value")
        if not isinstance(value, (int, float)) or not isinstance(multiplier, (int, float)):
            raise PatchError("multiply patch requires numeric current value and numeric value")
        _set_value(target, tokens, value * multiplier)
    elif op == "clamp":
        value = _get_value(target, tokens)
        if not isinstance(value, (int, float)):
            raise PatchError("clamp patch requires numeric current value")
        if "min" in patch:
            value = max(value, patch["min"])
        if "max" in patch:
            value = min(value, patch["max"])
        _set_value(target, tokens, value)
    elif op == "insert":
        sequence = _ensure_list_at_path(target, tokens)
        item = deepcopy(patch.get("value"))
        position = patch.get("position", "end")
        if position == "start":
            sequence.insert(0, item)
        else:
            sequence.append(item)
    elif op == "replace":
        where = patch.get("where")
        replacement = deepcopy(patch.get("value"))
        for sequence, index, item in _iter_wildcard_items(target, tokens):
            if _matches_where(where, target, context, item):
                sequence[index] = deepcopy(replacement)
    elif op == "remove":
        where = patch.get("where")
        grouped: dict[int, tuple[list, list[int]]] = {}
        for sequence, index, item in _iter_wildcard_items(target, tokens):
            if _matches_where(where, target, context, item):
                key = id(sequence)
                grouped.setdefault(key, (sequence, []))[1].append(index)
        for sequence, indices in grouped.values():
            for index in sorted(indices, reverse=True):
                del sequence[index]


def apply_patches(
    target: Mapping[str, Any],
    patches: list[Mapping[str, Any]],
    context: Mapping[str, Any] | None = None,
) -> dict:
    """Return a deep-copied target with deterministic Skill patches applied."""
    result = deepcopy(dict(target))
    for patch in patches:
        apply_patch(result, patch, context=context)
    return result
