"""High-level deterministic Skill execution helpers."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from nudge.skills.jsonlogic import evaluate, validate_rule
from nudge.skills.patch import apply_patches
from nudge.skills.schema import validate_skill


@dataclass(frozen=True)
class SkillExecutionResult:
    """Result from applying deterministic Skill rules."""

    skill: dict
    applied_rules: list[str]


def _rule_data(skill: Mapping[str, Any], context: Mapping[str, Any]) -> dict:
    data = deepcopy(dict(skill))
    data.update(deepcopy(dict(context)))
    return data


def _apply_rule_blocks(
    skill: Mapping[str, Any],
    blocks: list[Mapping[str, Any]],
    trigger_key: str,
    context: Mapping[str, Any],
) -> SkillExecutionResult:
    current = deepcopy(dict(skill))
    applied: list[str] = []
    for block in blocks:
        trigger = block[trigger_key]
        validate_rule(trigger)
        if evaluate(trigger, _rule_data(current, context)):
            current = apply_patches(current, block["apply"], context=context)
            applied.append(str(block["id"]))
    return SkillExecutionResult(skill=current, applied_rules=applied)


def personalize_skill(skill: Mapping[str, Any], context: Mapping[str, Any]) -> SkillExecutionResult:
    """Apply matching `personalization` rules to a Skill."""
    validated = validate_skill(skill)
    blocks = validated.get("personalization") or []
    return _apply_rule_blocks(validated, blocks, "when", context)


def apply_adaptations(skill: Mapping[str, Any], context: Mapping[str, Any]) -> SkillExecutionResult:
    """Apply matching `adaptation` rules to a Skill or personalized Skill."""
    validated = validate_skill(skill)
    blocks = validated.get("adaptation") or []
    return _apply_rule_blocks(validated, blocks, "trigger", context)
