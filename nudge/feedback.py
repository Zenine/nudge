"""Shared feedback schema helpers for local action status writeback."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

FEEDBACK_SCHEMA_VERSION = "nudge.feedback.v1"
STATUS_REASONS = {
    "too_hard",
    "no_time",
    "conflict",
    "low_energy",
    "forgot",
    "unclear",
    "not_important",
    "waiting_on_other",
}
STATUS_NEXT_ACTIONS = {"keep", "reduce", "split", "reschedule", "cancel"}
STATUS_ALLOWED = {"done", "skipped", "partial", "deferred", "blocked"}
UNFINISHED_STATUSES = {"skipped", "partial", "deferred", "blocked"}
KNOWN_SOURCE_TYPES = {"subjective", "objective", "agent", "system", "unknown"}


def build_feedback(
    *,
    source: str | None = None,
    channel: str | None = None,
    source_type: str | None = None,
    note: str | None = None,
    reason: str | None = None,
    next_action: str | None = None,
    metrics: dict[str, Any] | None = None,
    raw_text: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a canonical feedback payload while preserving caller metadata."""
    feedback: dict[str, Any] = dict(extra or {})
    feedback["schema_version"] = FEEDBACK_SCHEMA_VERSION

    if source:
        feedback["source"] = source
    inferred_channel = channel or _infer_channel(source)
    if inferred_channel:
        feedback["channel"] = inferred_channel
    normalized_type = _normalize_source_type(source_type) or _infer_source_type(source, inferred_channel)
    feedback["source_type"] = normalized_type

    if note is not None:
        feedback["note"] = str(note)
    normalized_reason = _normalize_choice(reason, STATUS_REASONS)
    if normalized_reason:
        feedback["reason"] = normalized_reason
    normalized_next_action = _normalize_choice(next_action, STATUS_NEXT_ACTIONS)
    if normalized_next_action:
        feedback["next_action"] = normalized_next_action
    if metrics:
        feedback["metrics"] = metrics
    if raw_text is not None:
        feedback["raw_text"] = str(raw_text)
    return feedback


def normalize_feedback(raw_feedback: object) -> dict[str, Any]:
    """Parse legacy or canonical feedback into the canonical reporting shape."""
    feedback = _feedback_dict(raw_feedback)
    if not feedback:
        return {}

    normalized = dict(feedback)
    normalized["schema_version"] = str(normalized.get("schema_version") or FEEDBACK_SCHEMA_VERSION)
    source = _clean_string(normalized.get("source"))
    channel = _clean_string(normalized.get("channel")) or _infer_channel(source)
    source_type = _normalize_source_type(normalized.get("source_type")) or _infer_source_type(source, channel)
    if source:
        normalized["source"] = source
    if channel:
        normalized["channel"] = channel
    normalized["source_type"] = source_type
    reason = _normalize_choice(normalized.get("reason"), STATUS_REASONS)
    if reason:
        normalized["reason"] = reason
    else:
        normalized.pop("reason", None)
    next_action = _normalize_choice(normalized.get("next_action"), STATUS_NEXT_ACTIONS)
    if next_action:
        normalized["next_action"] = next_action
    else:
        normalized.pop("next_action", None)
    if not isinstance(normalized.get("metrics"), dict):
        normalized.pop("metrics", None)
    return normalized


def feedback_source_summary(actions: list[dict]) -> dict[str, Any]:
    """Count feedback source types and channels across action rows."""
    type_counts: Counter[str] = Counter()
    channel_counts: Counter[str] = Counter()
    total = 0
    for action in actions:
        feedback = normalize_feedback(action.get("feedback"))
        if not feedback:
            continue
        total += 1
        source_type = str(feedback.get("source_type") or "unknown")
        channel = str(feedback.get("channel") or "unknown")
        type_counts[source_type] += 1
        channel_counts[channel] += 1
    return {
        "total": total,
        "by_type": dict(type_counts),
        "by_channel": dict(channel_counts),
    }


def format_feedback_source_summary(summary: dict[str, Any]) -> str:
    """Render compact source-type counts for CLI reports."""
    by_type = summary.get("by_type") or {}
    return (
        f"subjective={by_type.get('subjective', 0)} "
        f"objective={by_type.get('objective', 0)} "
        f"agent={by_type.get('agent', 0)} "
        f"unknown={by_type.get('unknown', 0)}"
    )


def feedback_source_label(feedback: dict[str, Any]) -> str:
    """Return a compact label for one feedback payload's origin."""
    source_type = str(feedback.get("source_type") or "unknown")
    channel = str(feedback.get("channel") or feedback.get("source") or "unknown")
    return f"{source_type}:{channel}"


def _feedback_dict(raw_feedback: object) -> dict[str, Any]:
    if isinstance(raw_feedback, dict):
        return dict(raw_feedback)
    if not raw_feedback:
        return {}
    try:
        parsed = json.loads(str(raw_feedback))
    except (TypeError, json.JSONDecodeError):
        return {"note": str(raw_feedback)}
    return parsed if isinstance(parsed, dict) else {}


def _infer_channel(source: str | None) -> str | None:
    if not source:
        return None
    text = source.strip().lower()
    if text.startswith("nudge log parse"):
        return "cli.log.parse"
    if text.startswith("nudge log"):
        return "cli.log"
    if text.startswith("nudge check-in parse"):
        return "cli.check-in.parse"
    if text.startswith("nudge check-in"):
        return "cli.check-in"
    if "reminders sync-completed" in text:
        return "reminders.sync_completed"
    if "report_action_status" in text or text.startswith("mcp"):
        return "mcp.report_action_status"
    if text.startswith("nudge agent") or text.startswith("agent"):
        return "agent.status"
    if "review weekly --adapt" in text:
        return "review.adapt"
    if "sleep auto-skip" in text:
        return "sleep.auto_skip"
    return None


def _infer_source_type(source: str | None, channel: str | None) -> str:
    text = " ".join(part for part in (source or "", channel or "") if part).lower()
    if not text:
        return "unknown"
    if "reminders.sync_completed" in text or "reminders sync-completed" in text:
        return "objective"
    if "mcp.report_action_status" in text or "agent.status" in text:
        return "agent"
    if "cli.log" in text or "cli.check-in" in text:
        return "subjective"
    if "review.adapt" in text or "sleep.auto_skip" in text:
        return "system"
    return "unknown"


def _normalize_source_type(value: object) -> str | None:
    text = _clean_string(value)
    if not text:
        return None
    text = text.lower()
    return text if text in KNOWN_SOURCE_TYPES else "unknown"


def _normalize_choice(value: object, allowed: set[str]) -> str | None:
    text = _clean_string(value)
    if not text:
        return None
    text = text.lower()
    return text if text in allowed else None


def _clean_string(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None
