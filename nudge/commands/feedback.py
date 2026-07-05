"""Low-friction feedback pullback and batch status writeback."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import click

from nudge.feedback import STATUS_ALLOWED, STATUS_NEXT_ACTIONS, STATUS_REASONS, build_feedback
from nudge.json_contract import versioned_payload
from nudge.state import (
    complete_action,
    get_action,
    get_actions,
    partial_action,
    skip_action,
    update_action_status,
)

_PENDING_STATUSES = {"created", "pending"}


@dataclass(frozen=True)
class _FeedbackUpdate:
    action_id: str
    status: str
    note: str | None = None
    reason: str | None = None
    next_action: str | None = None
    source: str | None = None
    feedback: dict[str, Any] | None = None


@click.group("feedback")
def feedback_command():
    """List pending feedback and batch-write action status updates."""


@feedback_command.command("today")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def today_command(json_output: bool):
    """List today's actions that still need completion feedback."""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    actions = get_actions(since=today.isoformat(), until=tomorrow.isoformat())
    items = [_feedback_item(action) for action in actions if action.get("status") in _PENDING_STATUSES]
    payload = versioned_payload({
        "ok": True,
        "period": {"start": today.isoformat(), "end": tomorrow.isoformat()},
        "total": len(items),
        "items": items,
    })
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if not items:
        click.echo("今天没有待反馈 action。")
        return
    click.echo("今天待反馈 action:")
    for item in items:
        scheduled = f" · {item.get('scheduled_at')}" if item.get("scheduled_at") else ""
        click.echo(f"- {item['summary']}{scheduled}")
        click.echo(f"  done: {item['quick_commands']['done']}")
        click.echo(f"  partial: {item['quick_commands']['partial']}")
        click.echo(f"  skipped: {item['quick_commands']['skipped']}")


@feedback_command.command("apply")
@click.option("--file", "file_path", type=click.Path(dir_okay=False), help="Read feedback update JSON from file")
@click.option("--dry-run", is_flag=True, help="Validate and preview without updating SQLite")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def apply_command(file_path: str | None, dry_run: bool, json_output: bool):
    """Apply multiple action status updates from JSON.

    Input format:
    {"updates": [{"id": "...", "status": "done", "note": "..."}]}
    """
    try:
        request = _read_request(file_path)
        updates = _normalize_request(request)
        previous = _validate_updates(updates)
    except ValueError as exc:
        _emit_error(str(exc), json_output=json_output, dry_run=dry_run)
        return

    results = []
    if not dry_run:
        for update in updates:
            feedback = _build_update_feedback(update)
            _apply_update(update, feedback)

    for update in updates:
        before = previous[update.action_id]
        after = get_action(update.action_id) if not dry_run else None
        results.append({
            "id": update.action_id,
            "summary": before.get("summary"),
            "type": before.get("type"),
            "scheduled_at": before.get("scheduled_at"),
            "previous_status": before.get("status"),
            "status": update.status,
            "updated_status": after.get("status") if after else None,
            "feedback": _build_update_feedback(update),
        })

    payload = versioned_payload({
        "ok": True,
        "dry_run": dry_run,
        "total": len(results),
        "succeeded": 0 if dry_run else len(results),
        "failed": 0,
        "updates": results,
        "errors": [],
    })
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    prefix = "DRY-RUN " if dry_run else ""
    click.echo(f"{prefix}feedback updates: {len(results)}")
    for result in results:
        click.echo(f"- {result['status']}: {result['summary']}")


def _feedback_item(action: dict) -> dict[str, Any]:
    action_id = str(action.get("id") or "")
    return {
        "id": action_id,
        "summary": action.get("summary"),
        "type": action.get("type"),
        "status": action.get("status"),
        "scheduled_at": action.get("scheduled_at"),
        "quick_commands": {
            "done": _quick_command(action_id, "done"),
            "partial": _quick_command(action_id, "partial"),
            "skipped": _quick_command(action_id, "skipped"),
            "deferred": _quick_command(action_id, "deferred"),
            "blocked": _quick_command(action_id, "blocked"),
        },
    }


def _quick_command(action_id: str, status: str) -> str:
    return (
        "nudge feedback apply --json <<'JSON'\n"
        + json.dumps({"updates": [{"id": action_id, "status": status}]}, ensure_ascii=False)
        + "\nJSON"
    )


def _read_request(file_path: str | None) -> object:
    if file_path:
        text = Path(file_path).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        raise ValueError("missing feedback JSON; pass --file or pipe stdin")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


def _normalize_request(request: object) -> list[_FeedbackUpdate]:
    if not isinstance(request, dict):
        raise ValueError("request must be a JSON object")
    raw_updates = request.get("updates")
    if not isinstance(raw_updates, list) or not raw_updates:
        raise ValueError("request.updates must be a non-empty list")
    if len(raw_updates) > 50:
        raise ValueError("request.updates must contain at most 50 items")
    updates = [_normalize_update(item, index) for index, item in enumerate(raw_updates, start=1)]
    ids = [update.action_id for update in updates]
    if len(ids) != len(set(ids)):
        raise ValueError("request.updates contains duplicate action ids")
    return updates


def _normalize_update(item: object, index: int) -> _FeedbackUpdate:
    if not isinstance(item, dict):
        raise ValueError(f"updates[{index}] must be an object")
    action_id = _string(item.get("id") or item.get("action_id"))
    if not action_id:
        raise ValueError(f"updates[{index}].id is required")
    status = _string(item.get("status")).lower()
    if status not in STATUS_ALLOWED:
        raise ValueError(f"updates[{index}].status unsupported: {status}")
    reason = _optional_choice(item.get("reason"), STATUS_REASONS, f"updates[{index}].reason")
    next_action = _optional_choice(item.get("next_action"), STATUS_NEXT_ACTIONS, f"updates[{index}].next_action")
    raw_feedback = item.get("feedback", {})
    if not isinstance(raw_feedback, dict):
        raise ValueError(f"updates[{index}].feedback must be an object if provided")
    return _FeedbackUpdate(
        action_id=action_id,
        status=status,
        note=_optional_string(item.get("note")),
        reason=reason,
        next_action=next_action,
        source=_optional_string(item.get("source")),
        feedback=raw_feedback,
    )


def _validate_updates(updates: list[_FeedbackUpdate]) -> dict[str, dict]:
    previous = {}
    for update in updates:
        action = get_action(update.action_id)
        if action is None:
            raise ValueError(f"FEEDBACK_ACTION_NOT_FOUND: {update.action_id}")
        previous[update.action_id] = action
    return previous


def _build_update_feedback(update: _FeedbackUpdate) -> dict[str, Any]:
    return build_feedback(
        source=update.source or "nudge feedback apply",
        channel="cli.feedback.apply",
        source_type="subjective",
        note=update.note,
        reason=update.reason,
        next_action=update.next_action,
        extra=update.feedback,
    )


def _apply_update(update: _FeedbackUpdate, feedback: dict[str, Any]) -> None:
    if update.status == "done":
        complete_action(update.action_id, feedback=feedback)
    elif update.status == "skipped":
        skip_action(update.action_id, feedback=feedback)
    elif update.status == "partial":
        partial_action(update.action_id, feedback=feedback)
    else:
        update_action_status(update.action_id, update.status, feedback=feedback)


def _emit_error(message: str, *, json_output: bool, dry_run: bool) -> None:
    code = "FEEDBACK_REQUEST_INVALID"
    detail = message
    if message.startswith("FEEDBACK_ACTION_NOT_FOUND:"):
        code = "FEEDBACK_ACTION_NOT_FOUND"
        detail = message.split(":", 1)[1].strip()
    payload = versioned_payload({
        "ok": False,
        "dry_run": dry_run,
        "errors": [{"code": code, "message": detail}],
    })
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        raise click.exceptions.Exit(1)
    raise click.ClickException(f"{code}: {detail}")


def _optional_choice(value: object, allowed: set[str], field_name: str) -> str | None:
    text = _optional_string(value)
    if not text:
        return None
    normalized = text.lower()
    if normalized not in allowed:
        raise ValueError(f"{field_name} unsupported: {normalized}")
    return normalized


def _optional_string(value: object) -> str | None:
    text = _string(value)
    return text or None


def _string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
