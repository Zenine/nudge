"""Fast check-in / log command for action completion tracking."""

import json
from typing import Any

import click

from nudge.action_hygiene import normalize_reminder_title
from nudge.apple.reminders import complete_reminder
from nudge.brain import NudgeBrainError, parse_check_in_feedback
from nudge.config import DEFAULT_REMINDER_LIST, get_defaults, load_config
from nudge.errors import ErrorReport, classify_llm_error
from nudge.feedback import STATUS_ALLOWED as _ALLOWED_STATUSES
from nudge.feedback import STATUS_NEXT_ACTIONS as _NEXT_ACTIONS
from nudge.feedback import STATUS_REASONS as _REASONS
from nudge.feedback import build_feedback
from nudge.json_contract import versioned_payload
from nudge.state import (
    complete_action,
    get_actions,
    partial_action,
    skip_action,
    update_action_status,
)


_STATUS_LABELS = {
    "done": ("✓", "done"),
    "skipped": ("✗", "skipped"),
    "partial": ("◐", "partial"),
    "deferred": ("↷", "deferred"),
    "blocked": ("⛔", "blocked"),
}


@click.command("log")
@click.argument("status", type=click.Choice(["done", "skipped", "partial", "deferred", "blocked", "parse"]))
@click.argument("note_words", nargs=-1)
@click.option("--id", "action_id", help="Action id to update")
@click.option("--match", "match_text", help="Match pending action by summary text")
@click.option("--reason", type=click.Choice(sorted(_REASONS)), help="Structured reason for unfinished work")
@click.option("--next-action", type=click.Choice(sorted(_NEXT_ACTIONS)), help="Suggested next action")
@click.option("--dry-run", is_flag=True, help="Preview parsed check-in without updating SQLite")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def log_command(
    status: str,
    note_words: tuple[str, ...],
    action_id: str | None,
    match_text: str | None,
    reason: str | None,
    next_action: str | None,
    dry_run: bool,
    json_output: bool,
):
    """Quickly mark the latest pending action as done/skipped/partial."""
    if status == "parse":
        _run_parse_check_in(
            " ".join(note_words),
            action_id=action_id,
            match_text=match_text,
            reason=reason,
            next_action=next_action,
            dry_run=dry_run,
            json_output=json_output,
            source="nudge log parse",
        )
        return
    _run_check_in(
        status,
        " ".join(note_words),
        action_id,
        match_text,
        reason=reason,
        next_action=next_action,
        source="nudge log",
        dry_run=dry_run,
        json_output=json_output,
    )


@click.command("check-in")
@click.argument("status", type=click.Choice(["done", "skipped", "partial", "deferred", "blocked", "parse"]))
@click.argument("note_words", nargs=-1)
@click.option("--id", "action_id", help="Action id to update")
@click.option("--match", "match_text", help="Match pending action by summary text")
@click.option("--reason", type=click.Choice(sorted(_REASONS)), help="Structured reason for unfinished work")
@click.option("--next-action", type=click.Choice(sorted(_NEXT_ACTIONS)), help="Suggested next action")
@click.option("--dry-run", is_flag=True, help="Preview parsed check-in without updating SQLite")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def check_in_command(
    status: str,
    note_words: tuple[str, ...],
    action_id: str | None,
    match_text: str | None,
    reason: str | None,
    next_action: str | None,
    dry_run: bool,
    json_output: bool,
):
    """Alias for `nudge log`."""
    if status == "parse":
        _run_parse_check_in(
            " ".join(note_words),
            action_id=action_id,
            match_text=match_text,
            reason=reason,
            next_action=next_action,
            dry_run=dry_run,
            json_output=json_output,
            source="nudge check-in parse",
        )
        return
    _run_check_in(
        status,
        " ".join(note_words),
        action_id,
        match_text,
        reason=reason,
        next_action=next_action,
        source="nudge check-in",
        dry_run=dry_run,
        json_output=json_output,
    )


def _run_parse_check_in(
    text: str,
    action_id: str | None = None,
    match_text: str | None = None,
    reason: str | None = None,
    next_action: str | None = None,
    dry_run: bool = False,
    json_output: bool = False,
    source: str = "nudge log parse",
) -> None:
    """Parse natural-language feedback and update one pending action."""
    if not text.strip():
        _fail(
            _check_in_error("CHECK_IN_PARSE_EMPTY", "请提供要解析的自然语言反馈。"),
            json_output=json_output,
            dry_run=dry_run,
        )
        return

    try:
        parsed = _normalize_parsed_check_in(parse_check_in_feedback(text))
    except NudgeBrainError as exc:
        _fail(classify_llm_error(str(exc)), json_output=json_output, dry_run=dry_run)
        return
    except click.ClickException as exc:
        _fail(
            _check_in_error("CHECK_IN_PARSE_INVALID", str(exc)),
            json_output=json_output,
            dry_run=dry_run,
        )
        return

    try:
        _run_check_in(
            parsed["status"],
            parsed["note"],
            action_id=action_id,
            match_text=match_text or parsed.get("match"),
            reason=reason or parsed.get("reason"),
            next_action=next_action or parsed.get("next_action"),
            source=source,
            dry_run=dry_run,
            json_output=json_output,
            raw_text=text,
            metrics=parsed["metrics"],
            parsed=parsed,
        )
    except click.ClickException as exc:
        _fail(
            _check_in_error("CHECK_IN_ACTION_NOT_FOUND", exc.message),
            json_output=json_output,
            dry_run=dry_run,
        )


def _run_check_in(
    status: str,
    note: str = "",
    action_id: str | None = None,
    match_text: str | None = None,
    reason: str | None = None,
    next_action: str | None = None,
    source: str = "nudge log",
    dry_run: bool = False,
    json_output: bool = False,
    raw_text: str | None = None,
    metrics: dict[str, Any] | None = None,
    parsed: dict[str, Any] | None = None,
) -> None:
    """Update one pending action and print a short confirmation."""
    action = _select_pending_action(action_id=action_id, match_text=match_text)
    feedback = _feedback(
        source=source,
        note=note,
        raw_text=raw_text,
        metrics=metrics,
        reason=reason,
        next_action=next_action,
    )

    if not dry_run:
        _apply_status(status, action["id"], feedback)
    apple_reminder = _sync_apple_reminder_completion(action, status, dry_run=dry_run)

    if json_output:
        _emit_json(_success_payload(
            action,
            status,
            feedback,
            dry_run=dry_run,
            parsed=parsed,
            apple_reminder=apple_reminder,
        ))
        return

    symbol, label = _STATUS_LABELS[status]
    scheduled = f" · {action.get('scheduled_at')}" if action.get("scheduled_at") else ""
    prefix = "DRY-RUN " if dry_run else ""
    click.echo(f"  {prefix}{symbol} {label}: {action['summary']}{scheduled}")
    if note:
        click.echo(f"    note: {note}")
    if reason:
        click.echo(f"    reason: {reason}")
    if next_action:
        click.echo(f"    next: {next_action}")
    if metrics:
        click.echo(f"    metrics: {_format_metrics(metrics)}")
    if apple_reminder.get("attempted"):
        marker = "synced" if apple_reminder.get("ok") else "sync failed"
        click.echo(f"    apple reminder: {marker} ({apple_reminder.get('message')})")


def _select_pending_action(
    action_id: str | None = None,
    match_text: str | None = None,
) -> dict:
    """Select a pending action by id, summary match, or latest pending item."""
    if action_id:
        for action in get_actions():
            if action["id"] == action_id:
                return action
        raise click.ClickException(f"找不到 action id: {action_id}")

    actions = _pending_actions()
    if not actions:
        raise click.ClickException("没有待记录的 action。先用 `nudge \"...\"` 创建计划项。")

    if match_text:
        normalized = match_text.lower()
        matches = [action for action in actions if normalized in action.get("summary", "").lower()]
        if not matches:
            raise click.ClickException(f"找不到匹配的待记录 action: {match_text}")
        if len(matches) > 1:
            names = "；".join(f"{action['id']} {action['summary']}" for action in matches[:5])
            raise click.ClickException(f"匹配到多个 action，请用 --id 指定：{names}")
        return matches[0]

    return actions[0]


def _pending_actions() -> list[dict]:
    """Return pending actions ordered by the state layer's newest-first order."""
    return [
        action
        for action in get_actions()
        if action.get("status") in ("created", "pending")
    ]


def _apply_status(status: str, action_id: str, feedback: dict) -> None:
    if status == "done":
        complete_action(action_id, feedback=feedback)
    elif status == "skipped":
        skip_action(action_id, feedback=feedback)
    elif status == "partial":
        partial_action(action_id, feedback=feedback)
    elif status in ("deferred", "blocked"):
        update_action_status(action_id, status, feedback=feedback)
    else:
        raise click.ClickException(f"Unsupported status: {status}")


def _sync_apple_reminder_completion(action: dict, status: str, dry_run: bool) -> dict:
    """Best-effort mirror for `log done` on reminder actions."""
    if status != "done" or action.get("type") != "reminder":
        return {"attempted": False}

    title = str(action.get("summary") or "").strip()
    if not title:
        return {"attempted": False, "ok": False, "message": "missing reminder title"}

    try:
        reminder_list = _default_reminder_list()
    except Exception as exc:
        return {
            "attempted": True,
            "ok": False,
            "title": title,
            "message": str(exc),
        }
    if dry_run:
        return {
            "attempted": True,
            "dry_run": True,
            "list": reminder_list,
            "title": title,
            "message": "dry-run; Apple Reminders not modified",
        }

    try:
        ok, message = _complete_apple_reminder_by_possible_titles(
            title,
            str(action.get("scheduled_at") or ""),
            reminder_list,
        )
    except Exception as exc:
        ok, message = False, str(exc)
    return {
        "attempted": True,
        "ok": ok,
        "list": reminder_list,
        "title": title,
        "message": message,
    }


def _complete_apple_reminder_by_possible_titles(summary: str, scheduled_at: str, reminder_list: str) -> tuple[bool, str]:
    titles = []
    for title in (summary, normalize_reminder_title(summary, scheduled_at)):
        if title and title not in titles:
            titles.append(title)

    errors = []
    for title in titles:
        ok, message = complete_reminder(title, reminder_list, due_date=scheduled_at or None)
        if ok:
            return True, message
        errors.append(f"{title}: {message}")
    return False, "; ".join(errors) or "missing reminder title"


def _default_reminder_list() -> str:
    defaults = get_defaults(load_config())
    return defaults.get("default_reminder_list", DEFAULT_REMINDER_LIST)


def _normalize_parsed_check_in(parsed: dict) -> dict:
    if not isinstance(parsed, dict):
        raise click.ClickException("LLM 返回的 check-in 结果不是 JSON object")

    status = str(parsed.get("status") or "").strip().lower()
    if status not in _ALLOWED_STATUSES:
        raise click.ClickException(f"LLM 返回了不支持的 status: {status or '<empty>'}")

    metrics = parsed.get("metrics") or {}
    if not isinstance(metrics, dict):
        raise click.ClickException("LLM 返回的 metrics 必须是 object")

    reason = _optional_choice(parsed.get("reason"), _REASONS, "reason")
    next_action = _optional_choice(parsed.get("next_action"), _NEXT_ACTIONS, "next_action")
    match = parsed.get("match")
    return {
        "status": status,
        "note": str(parsed.get("note") or "").strip(),
        "metrics": metrics,
        "match": str(match).strip() if match else None,
        "reason": reason,
        "next_action": next_action,
    }


def _optional_choice(value: Any, allowed: set[str], field_name: str) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    if normalized not in allowed:
        raise click.ClickException(f"LLM 返回了不支持的 {field_name}: {normalized}")
    return normalized


def _feedback(
    source: str,
    note: str,
    raw_text: str | None = None,
    metrics: dict[str, Any] | None = None,
    reason: str | None = None,
    next_action: str | None = None,
) -> dict:
    return build_feedback(
        source=source,
        channel=_feedback_channel(source),
        source_type="subjective",
        note=note,
        raw_text=raw_text,
        metrics=metrics,
        reason=reason,
        next_action=next_action,
    )


def _feedback_channel(source: str) -> str:
    if source.startswith("nudge log parse"):
        return "cli.log.parse"
    if source.startswith("nudge check-in parse"):
        return "cli.check-in.parse"
    if source.startswith("nudge check-in"):
        return "cli.check-in"
    return "cli.log"


def _format_metrics(metrics: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in metrics.items())


def _action_payload(action: dict, status: str) -> dict:
    payload = {
        "id": action.get("id"),
        "summary": action.get("summary"),
        "status": status,
    }
    if action.get("scheduled_at"):
        payload["scheduled_at"] = action.get("scheduled_at")
    return payload


def _success_payload(
    action: dict,
    status: str,
    feedback: dict,
    dry_run: bool,
    parsed: dict | None = None,
    apple_reminder: dict | None = None,
) -> dict:
    payload = {
        "ok": True,
        "dry_run": dry_run,
        "action": _action_payload(action, status),
        "feedback": feedback,
    }
    if parsed is not None:
        payload["parsed"] = parsed
    if apple_reminder and apple_reminder.get("attempted"):
        payload["apple_reminder"] = apple_reminder
    return versioned_payload(payload)


def _check_in_error(code: str, message: str) -> ErrorReport:
    return ErrorReport(
        code=code,
        title="自然语言 check-in 解析失败",
        detail=message,
        next_steps=(
            "改用显式命令，例如 `nudge log done \"备注\"`。",
            "或收窄自然语言反馈后重试 `nudge log parse \"...\"`。",
        ),
        raw_error=message,
    )


def _error_payload(error: ErrorReport, dry_run: bool = False) -> dict:
    return versioned_payload({
        "ok": False,
        "dry_run": dry_run,
        "error": {
            "code": error.code,
            "message": error.title,
            "detail": error.detail,
            "raw_error": error.raw_error,
        },
    })


def _emit_json(payload: dict) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False))


def _fail(error: ErrorReport, json_output: bool, dry_run: bool = False) -> None:
    if json_output:
        _emit_json(_error_payload(error, dry_run=dry_run))
    else:
        click.echo(error.render(), err=True)
    raise click.exceptions.Exit(1)
