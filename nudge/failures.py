"""Failure visibility aggregation for Nudge dogfood."""

from __future__ import annotations

import json
import shlex
from datetime import datetime, timedelta
from typing import Any

from nudge.feedback import normalize_feedback

_UNFINISHED_WITH_REASON = {"skipped", "partial", "deferred", "blocked"}
_PENDING_STATUSES = {"created", "pending"}


def build_failure_visibility_report(
    actions: list[dict],
    *,
    now: datetime | None = None,
    overdue_hours: int = 24,
) -> dict[str, Any]:
    """Build a read-only report for overdue, blocked, and unexplained actions."""
    now = now or datetime.now()
    overdue_hours = max(1, int(overdue_hours or 24))
    cutoff = now - timedelta(hours=overdue_hours)

    pending_overdue: list[dict] = []
    blocked_open: list[dict] = []
    deferred_open: list[dict] = []
    missing_reason: list[dict] = []
    missing_next_action: list[dict] = []

    for action in actions:
        status = str(action.get("status") or "")
        item = _item(action, now)
        scheduled = _parse_datetime(action.get("scheduled_at"))
        if status in _PENDING_STATUSES and scheduled is not None and scheduled <= cutoff:
            pending_overdue.append(item)
        if status == "blocked":
            blocked_open.append(item)
        if status == "deferred":
            deferred_open.append(item)
        if status in _UNFINISHED_WITH_REASON:
            feedback = _feedback(action)
            if not str(feedback.get("reason") or "").strip():
                missing_reason.append(item)
            if not str(feedback.get("next_action") or "").strip():
                missing_next_action.append(item)

    summary = {
        "pending_overdue": len(pending_overdue),
        "blocked_open": len(blocked_open),
        "deferred_open": len(deferred_open),
        "missing_reason": len(missing_reason),
        "missing_next_action": len(missing_next_action),
    }
    return {
        "ok": True,
        "overdue_hours": overdue_hours,
        "summary": summary,
        "total_open_issues": sum(summary.values()),
        "pending_overdue": pending_overdue,
        "blocked_open": blocked_open,
        "deferred_open": deferred_open,
        "missing_reason": missing_reason,
        "missing_next_action": missing_next_action,
    }


def render_failure_visibility_report(report: dict, *, limit: int = 10) -> str:
    """Render a compact Chinese failure visibility report."""
    summary = report.get("summary") or {}
    lines = [
        "失败/阻塞可见性",
        (
            "summary: "
            f"overdue={summary.get('pending_overdue', 0)} "
            f"blocked={summary.get('blocked_open', 0)} "
            f"deferred={summary.get('deferred_open', 0)} "
            f"missing_reason={summary.get('missing_reason', 0)} "
            f"missing_next_action={summary.get('missing_next_action', 0)}"
        ),
    ]
    items = _priority_items(report)[: max(1, limit)]
    if not items:
        lines.append("暂无失败/阻塞待跟进。")
        return "\n".join(lines)

    lines.append("待跟进:")
    for item in items:
        scheduled = f" · {item.get('scheduled_at')}" if item.get("scheduled_at") else ""
        age = f" · {item.get('age_hours')}h" if item.get("age_hours") is not None else ""
        lines.append(f"- [{item.get('status')}] {item.get('summary')}{scheduled}{age}")
        lines.append(f"  记录：{item.get('followup_command')}")
    return "\n".join(lines)


def failure_followup_section(report: dict, *, limit: int = 5) -> str:
    """Return a short briefing section for failure follow-up, or empty string."""
    items = _priority_items(report)[: max(1, limit)]
    if not items:
        return ""
    summary = report.get("summary") or {}
    lines = [
        "失败/阻塞待跟进:",
        (
            "- 汇总："
            f"overdue={summary.get('pending_overdue', 0)} "
            f"blocked={summary.get('blocked_open', 0)} "
            f"missing_reason={summary.get('missing_reason', 0)} "
            f"missing_next_action={summary.get('missing_next_action', 0)}"
        ),
    ]
    for item in items:
        scheduled = f" · {item.get('scheduled_at')}" if item.get("scheduled_at") else ""
        lines.append(f"- [{item.get('status')}] {item.get('summary')}{scheduled}")
        lines.append(f"  记录：{item.get('followup_command')}")
    return "\n".join(lines)


def _priority_items(report: dict) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for key in ("pending_overdue", "blocked_open", "missing_reason", "missing_next_action", "deferred_open"):
        for item in report.get(key) or []:
            item_id = str(item.get("id") or "")
            marker = item_id or json.dumps(item, ensure_ascii=False, sort_keys=True)
            if marker in seen:
                continue
            seen.add(marker)
            result.append(item)
    return result


def _item(action: dict, now: datetime) -> dict:
    feedback = _feedback(action)
    status = str(action.get("status") or "pending")
    return {
        "id": action.get("id"),
        "summary": action.get("summary"),
        "status": status,
        "scheduled_at": action.get("scheduled_at"),
        "age_hours": _age_hours(action.get("scheduled_at"), now),
        "reason": feedback.get("reason"),
        "next_action": feedback.get("next_action"),
        "followup_command": _followup_command(action, feedback),
    }


def _followup_command(action: dict, feedback: dict) -> str:
    status = str(action.get("status") or "pending")
    if status in _PENDING_STATUSES:
        status = "done"
    action_id = str(action.get("id") or "<id>")
    reason = str(feedback.get("reason") or _default_reason(status))
    next_action = str(feedback.get("next_action") or _default_next_action(status))
    note = _default_note(status)
    return (
        f"nudge log {status} --id {shlex.quote(action_id)} "
        f"--reason {shlex.quote(reason)} --next-action {shlex.quote(next_action)} "
        f"{shlex.quote(note)}"
    )


def _default_reason(status: str) -> str:
    if status == "blocked":
        return "waiting_on_other"
    if status == "deferred":
        return "no_time"
    return "unclear"


def _default_next_action(status: str) -> str:
    if status == "deferred":
        return "reschedule"
    return "keep"


def _default_note(status: str) -> str:
    if status == "blocked":
        return "补充阻塞原因"
    if status == "deferred":
        return "补充延期原因"
    return "补充执行结果"


def _feedback(action: dict) -> dict:
    return normalize_feedback(action.get("feedback"))


def _age_hours(value: object, now: datetime) -> int | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds() // 3600))


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value)
    for candidate in (text, text.replace(" ", "T")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None
