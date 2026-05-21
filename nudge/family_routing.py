"""Family-group recipient routing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class FamilyRoutingResult:
    members: list[dict]
    metadata: dict


@dataclass(frozen=True)
class AssigneeExpansion:
    members: list[dict]
    valid_keys: list[str]
    invalid_assignees: list[object]
    empty_assignees: list[str]
    error: str | None = None

    @property
    def has_problem(self) -> bool:
        return bool(self.invalid_assignees or self.empty_assignees or self.error or not self.valid_keys)


LLMRouter = Callable[[dict, list[dict], dict], dict | None]


def resolve_family_recipients(
    action: dict,
    family_members: list[dict],
    routing: dict | None,
    llm_router: LLMRouter | None = None,
) -> FamilyRoutingResult:
    """Resolve recipients for one family-group action."""
    routing = routing if isinstance(routing, dict) else {}
    original_person = str(action.get("person") or "")
    member_by_key = {member.get("key"): member for member in family_members if member.get("key")}

    rule_result = _keyword_route(action, routing, member_by_key, original_person)
    if rule_result is not None:
        return rule_result

    llm_metadata: dict = {}
    if routing.get("llm_fallback") and llm_router is not None:
        llm_result, llm_metadata = _llm_route(action, family_members, routing, llm_router, member_by_key, original_person)
        if llm_result is not None:
            return llm_result

    expansion = _expand_assignees(routing.get("default", "all"), member_by_key)
    metadata = {
        "source": "default",
        "rule_id": None,
        "original_person": original_person,
        "assignees": expansion.valid_keys,
        "reason": "未命中关键词或 LLM 兜底，使用默认家庭路由。",
    }
    metadata.update(llm_metadata)
    if expansion.invalid_assignees or expansion.empty_assignees or expansion.error:
        metadata.update(_assignee_problem_metadata(expansion))
        metadata["source"] = "default_invalid"
        metadata["reason"] = _assignee_problem_reason(expansion, "default route")
        return FamilyRoutingResult(members=[], metadata=metadata)
    return FamilyRoutingResult(members=expansion.members, metadata=metadata)


def _keyword_route(action: dict, routing: dict, member_by_key: dict, original_person: str) -> FamilyRoutingResult | None:
    text = _action_text(action)
    rules = routing.get("rules", [])
    if not isinstance(rules, list):
        return None
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        keywords = rule.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [keywords]
        if not isinstance(keywords, (list, tuple, set)):
            continue
        for keyword in keywords:
            keyword_text = str(keyword).strip()
            if keyword_text and keyword_text in text:
                expansion = _expand_assignees(rule.get("assignees", []), member_by_key)
                if expansion.has_problem:
                    metadata = {
                        "source": "keyword_invalid",
                        "rule_id": rule.get("id"),
                        "original_person": original_person,
                        "assignees": expansion.valid_keys,
                        "reason": _assignee_problem_reason(expansion, "keyword rule"),
                    }
                    metadata.update(_assignee_problem_metadata(expansion))
                    return FamilyRoutingResult(members=[], metadata=metadata)
                return FamilyRoutingResult(
                    members=expansion.members,
                    metadata={
                        "source": "keyword",
                        "rule_id": rule.get("id"),
                        "original_person": original_person,
                        "assignees": expansion.valid_keys,
                        "reason": f"命中关键词：{keyword_text}",
                    },
                )
    return None


def _llm_route(
    action: dict,
    family_members: list[dict],
    routing: dict,
    llm_router: LLMRouter,
    member_by_key: dict,
    original_person: str,
) -> tuple[FamilyRoutingResult | None, dict]:
    try:
        suggestion = llm_router(action, family_members, routing)
    except Exception as exc:  # noqa: BLE001 - failures become routing metadata, not runtime failures.
        return None, {"llm_error": f"exception:{type(exc).__name__}"}

    if not isinstance(suggestion, dict):
        return None, {"llm_error": "non_dict_suggestion"}

    raw_confidence = suggestion.get("confidence")
    if isinstance(raw_confidence, bool):
        return None, {"llm_error": "invalid_confidence_type"}

    confidence = _float_or_none(raw_confidence)
    if confidence is None:
        return None, {"llm_error": "non_finite_confidence"}
    if confidence < 0 or confidence > 1:
        return None, {"llm_error": "out_of_range_confidence", "llm_confidence": confidence}

    threshold = _float_or_none(routing.get("llm_confidence_threshold", 0.65))
    if threshold is None:
        threshold = 0.65
    if confidence < threshold:
        return None, {"llm_error": "low_confidence", "llm_confidence": confidence}

    expansion = _expand_assignees(suggestion.get("assignees", []), member_by_key)
    if expansion.has_problem:
        metadata = {
            "llm_error": "invalid_assignees" if expansion.invalid_assignees else "no_valid_assignees",
            "llm_confidence": confidence,
        }
        metadata.update(_assignee_problem_metadata(expansion))
        return None, metadata

    return FamilyRoutingResult(
        members=expansion.members,
        metadata={
            "source": "llm",
            "rule_id": None,
            "original_person": original_person,
            "assignees": expansion.valid_keys,
            "confidence": confidence,
            "reason": str(suggestion.get("reason") or "LLM 路由建议。"),
        },
    ), {}


def _expand_assignees(assignees: object, member_by_key: dict) -> AssigneeExpansion:
    if assignees == "all":
        return AssigneeExpansion(list(member_by_key.values()), ["all"], [], [])

    if isinstance(assignees, str):
        raw_items = [assignees]
    elif isinstance(assignees, (list, tuple, set)):
        raw_items = list(assignees)
    else:
        return AssigneeExpansion([], [], [assignees], [], f"unsupported_type:{type(assignees).__name__}")

    valid_keys = []
    invalid_assignees = []
    empty_assignees = []
    include_all = False
    for item in raw_items:
        if not isinstance(item, str):
            invalid_assignees.append(item)
            continue
        key = item.strip()
        if not key:
            empty_assignees.append(item)
            continue
        if key == "all":
            include_all = True
            if "all" not in valid_keys:
                valid_keys.append("all")
            continue
        if key in member_by_key:
            if key not in valid_keys:
                valid_keys.append(key)
        else:
            invalid_assignees.append(key)

    if include_all:
        members = list(member_by_key.values())
    else:
        members = [member_by_key[key] for key in valid_keys]
    return AssigneeExpansion(members, valid_keys, invalid_assignees, empty_assignees)


def _assignee_problem_metadata(expansion: AssigneeExpansion) -> dict:
    metadata = {}
    if expansion.invalid_assignees:
        metadata["invalid_assignees"] = expansion.invalid_assignees
    if expansion.empty_assignees:
        metadata["empty_assignees"] = expansion.empty_assignees
    if expansion.error:
        metadata["assignee_error"] = expansion.error
    return metadata


def _assignee_problem_reason(expansion: AssigneeExpansion, context: str) -> str:
    if expansion.error:
        return expansion.error
    if expansion.invalid_assignees:
        return f"{context} has invalid assignees"
    if not expansion.valid_keys:
        return f"{context} has no valid assignees"
    if expansion.empty_assignees:
        return f"{context} has empty assignees"
    return f"{context} has invalid assignees"


def _action_text(action: dict) -> str:
    parts = []
    for key in ("summary", "name", "body", "notes", "location", "label", "title"):
        if action.get(key):
            parts.append(str(action[key]))
    return "\n".join(parts)


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number
