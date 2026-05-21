"""Skill Spec v0.1 loading and validation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only in unprepared envs
    yaml = None

from nudge.skills.jsonlogic import JsonLogicError, validate_rule
from nudge.skills.patch import ALLOWED_PATCH_OPS, PatchError, validate_path


SUPPORTED_SCHEMA_VERSION = "0.1"
CHOICE_TYPES = {"single_choice", "multi_choice"}
ASSESSMENT_TYPES = CHOICE_TYPES | {"number", "text", "boolean"}
DANGEROUS_FIELD_NAMES = {
    "bash",
    "code",
    "command",
    "exec",
    "javascript",
    "python",
    "runtime",
    "script",
    "shell",
}


@dataclass(frozen=True)
class ValidationIssue:
    """One schema validation issue."""

    path: str
    message: str


class SkillValidationError(ValueError):
    """Raised when a Skill document fails validation."""

    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("\n".join(f"{issue.path}: {issue.message}" for issue in issues))


def _issue(issues: list[ValidationIssue], path: str, message: str) -> None:
    issues.append(ValidationIssue(path=path, message=message))


def load_skill_file(path: str | Path) -> dict:
    """Load a Skill YAML or JSON file into a mapping."""
    source = Path(path)
    text = source.read_text()
    try:
        if source.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            if yaml is None:
                raise SkillValidationError(
                    [ValidationIssue("file", "PyYAML is required to load YAML Skill files")]
                )
            data = yaml.safe_load(text)
    except SkillValidationError:
        raise
    except Exception as exc:
        raise SkillValidationError([ValidationIssue("file", f"Cannot parse Skill file: {exc}")])

    if not isinstance(data, dict):
        raise SkillValidationError([ValidationIssue("file", "Skill file must contain an object")])
    return data


def _require_mapping(skill: Mapping[str, Any], key: str, issues: list[ValidationIssue]) -> Mapping[str, Any] | None:
    value = skill.get(key)
    if not isinstance(value, Mapping):
        _issue(issues, key, "required object is missing")
        return None
    return value


def _require_list(skill: Mapping[str, Any], key: str, issues: list[ValidationIssue]) -> list | None:
    value = skill.get(key)
    if not isinstance(value, list) or not value:
        _issue(issues, key, "required non-empty list is missing")
        return None
    return value


def _check_required_scalar(mapping: Mapping[str, Any], base_path: str, keys: list[str], issues: list[ValidationIssue]) -> None:
    for key in keys:
        if not mapping.get(key):
            _issue(issues, f"{base_path}.{key}", "required value is missing")


def _check_dangerous_fields(value: Any, path: str, issues: list[ValidationIssue]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in DANGEROUS_FIELD_NAMES:
                _issue(issues, key_path, "code execution fields are not allowed in Skill specs")
            _check_dangerous_fields(child, key_path, issues)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_dangerous_fields(child, f"{path}[{index}]", issues)


def _check_jsonlogic(rule: Any, path: str, issues: list[ValidationIssue]) -> None:
    try:
        validate_rule(rule)
    except JsonLogicError as exc:
        _issue(issues, path, str(exc))


def _check_patch(patch: Any, path: str, issues: list[ValidationIssue]) -> None:
    if not isinstance(patch, Mapping):
        _issue(issues, path, "patch must be an object")
        return

    op = patch.get("op")
    if op not in ALLOWED_PATCH_OPS:
        _issue(issues, f"{path}.op", f"unsupported patch op: {op}")
        return

    if op not in {"tag", "validate"}:
        if "path" not in patch:
            _issue(issues, f"{path}.path", "patch op requires path")
        else:
            try:
                validate_path(patch["path"])
            except PatchError as exc:
                _issue(issues, f"{path}.path", str(exc))

    if op == "validate":
        rule = patch.get("rule") or patch.get("when")
        if rule is None:
            _issue(issues, f"{path}.rule", "validate patch requires rule")
        else:
            _check_jsonlogic(rule, f"{path}.rule", issues)

    if "where" in patch:
        _check_jsonlogic(patch["where"], f"{path}.where", issues)


def _check_rule_block(block: Any, path: str, trigger_key: str, issues: list[ValidationIssue]) -> None:
    if not isinstance(block, Mapping):
        _issue(issues, path, "rule block must be an object")
        return

    if not block.get("id"):
        _issue(issues, f"{path}.id", "rule id is required")

    if trigger_key not in block:
        _issue(issues, f"{path}.{trigger_key}", f"{trigger_key} is required")
    else:
        _check_jsonlogic(block[trigger_key], f"{path}.{trigger_key}", issues)

    apply = block.get("apply")
    if not isinstance(apply, list) or not apply:
        _issue(issues, f"{path}.apply", "apply must be a non-empty list")
    else:
        for index, patch in enumerate(apply):
            _check_patch(patch, f"{path}.apply[{index}]", issues)


def collect_validation_issues(skill: Mapping[str, Any]) -> list[ValidationIssue]:
    """Collect all Skill Spec v0.1 validation issues."""
    issues: list[ValidationIssue] = []
    if not isinstance(skill, Mapping):
        return [ValidationIssue("skill", "Skill must be an object")]

    if skill.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        _issue(issues, "schema_version", f"must be {SUPPORTED_SCHEMA_VERSION!r}")
    if skill.get("kind") != "skill":
        _issue(issues, "kind", "must be 'skill'")

    metadata = _require_mapping(skill, "metadata", issues)
    if metadata is not None:
        _check_required_scalar(metadata, "metadata", ["id", "title", "version", "creator", "category"], issues)

    _require_mapping(skill, "audience", issues)

    assessment = _require_list(skill, "assessment", issues)
    if assessment is not None:
        for index, item in enumerate(assessment):
            item_path = f"assessment[{index}]"
            if not isinstance(item, Mapping):
                _issue(issues, item_path, "assessment item must be an object")
                continue
            _check_required_scalar(item, item_path, ["id", "question", "type"], issues)
            item_type = item.get("type")
            if item_type and item_type not in ASSESSMENT_TYPES:
                _issue(issues, f"{item_path}.type", f"unsupported assessment type: {item_type}")
            if item_type in CHOICE_TYPES and (not isinstance(item.get("options"), list) or not item["options"]):
                _issue(issues, f"{item_path}.options", "choice assessment requires options")

    _require_mapping(skill, "plan_template", issues)
    tracking = _require_mapping(skill, "tracking", issues)
    if tracking is not None:
        metrics = tracking.get("metrics")
        if not isinstance(metrics, list) or not metrics:
            _issue(issues, "tracking.metrics", "required non-empty list is missing")
        else:
            for index, metric in enumerate(metrics):
                metric_path = f"tracking.metrics[{index}]"
                if not isinstance(metric, Mapping):
                    _issue(issues, metric_path, "metric must be an object")
                    continue
                _check_required_scalar(metric, metric_path, ["id", "type"], issues)

    for index, block in enumerate(skill.get("personalization") or []):
        _check_rule_block(block, f"personalization[{index}]", "when", issues)

    for index, block in enumerate(skill.get("adaptation") or []):
        _check_rule_block(block, f"adaptation[{index}]", "trigger", issues)

    _check_dangerous_fields(skill, "", issues)
    return issues


def validate_skill(skill: Mapping[str, Any]) -> dict:
    """Validate and return a Skill mapping, or raise SkillValidationError."""
    issues = collect_validation_issues(skill)
    if issues:
        raise SkillValidationError(issues)
    return dict(skill)
