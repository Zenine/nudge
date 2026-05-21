"""Failure visibility command — read-only follow-up report."""

from __future__ import annotations

import json
from datetime import datetime

import click

from nudge.apple.notifications import notify
from nudge.failures import build_failure_visibility_report, render_failure_visibility_report
from nudge.json_contract import versioned_payload
from nudge.state import get_actions


@click.command("failures")
@click.option(
    "--overdue-hours",
    default=24,
    show_default=True,
    type=click.IntRange(1, 24 * 30),
    help="How old pending actions must be before they are treated as overdue.",
)
@click.option(
    "--limit",
    default=10,
    show_default=True,
    type=click.IntRange(1, 100),
    help="Maximum follow-up items to show in text output.",
)
@click.option("--notify", "send_notification", is_flag=True, help="Send a macOS notification when issues exist")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def failures_command(overdue_hours: int, limit: int, send_notification: bool, json_output: bool):
    """Show overdue, blocked, and unexplained actions without mutating state."""
    actions = get_actions()
    report = build_failure_visibility_report(
        actions,
        now=datetime.now(),
        overdue_hours=overdue_hours,
    )
    payload = {"ok": True, "report": report}
    if send_notification:
        payload["notification"] = _send_failure_visibility_notification(report)
    payload = versioned_payload(payload)

    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    click.echo(render_failure_visibility_report(report, limit=limit))
    if send_notification:
        notification = payload.get("notification") or {}
        if notification.get("sent"):
            click.echo("\nnotification: sent")
        elif notification.get("reason") == "no_issues":
            click.echo("\nnotification: skipped (no issues)")
        else:
            click.echo(f"\nnotification: failed ({notification.get('error')})")


def _send_failure_visibility_notification(report: dict) -> dict[str, object]:
    """Send one local notification for non-empty failure visibility reports."""
    summary = report.get("summary") or {}
    if not any(int(summary.get(key) or 0) for key in (
        "pending_overdue",
        "blocked_open",
        "deferred_open",
        "missing_reason",
        "missing_next_action",
    )):
        return {"sent": False, "reason": "no_issues"}

    message = _notification_message(report)
    ok, raw = notify(
        "Nudge 失败/阻塞待跟进",
        message[:240],
        subtitle=(
            f"overdue={summary.get('pending_overdue', 0)} "
            f"blocked={summary.get('blocked_open', 0)}"
        ),
    )
    return {
        "sent": bool(ok),
        "ok": bool(ok),
        "error": None if ok else raw,
    }


def _notification_message(report: dict) -> str:
    summary = report.get("summary") or {}
    lines = [
        (
            f"overdue={summary.get('pending_overdue', 0)} "
            f"blocked={summary.get('blocked_open', 0)} "
            f"missing_reason={summary.get('missing_reason', 0)} "
            f"missing_next_action={summary.get('missing_next_action', 0)}"
        )
    ]
    first = _first_issue(report)
    if first:
        lines.append(f"{first.get('summary')} · {first.get('status')}")
    lines.append("查看：nudge failures")
    return "\n".join(lines)


def _first_issue(report: dict) -> dict | None:
    for key in ("pending_overdue", "blocked_open", "missing_reason", "missing_next_action", "deferred_open"):
        items = report.get(key) or []
        if items:
            return items[0]
    return None
