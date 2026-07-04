"""Morning/evening briefing command."""

import json
from datetime import date, timedelta

import click

from nudge.apple.calendar import get_today_events
from nudge.apple.mail import get_recent_messages, get_unread_count
from nudge.apple.notifications import notify
from nudge.apple.reminders import get_due_today
from nudge.brain import NudgeBrainError, generate_briefing, generate_evening_review
from nudge.commands.daemon import build_daemon_health_report
from nudge.config import get_configured_calendar_names, load_config
from nudge.errors import classify_apple_error, format_llm_error
from nudge.failures import build_failure_visibility_report, failure_followup_section
from nudge.state import get_actions, get_habit_streaks


@click.command("briefing")
@click.argument("time_of_day", default="morning", type=click.Choice(["morning", "evening"]))
@click.option("--notify", "send_notification", is_flag=True, help="Also send a macOS notification")
def briefing_command(time_of_day, send_notification):
    """Generate a daily briefing (morning or evening)."""
    click.echo(f"Generating {time_of_day} briefing...\n")

    try:
        if time_of_day == "morning":
            text = _morning_briefing()
        else:
            text = _evening_briefing()
    except NudgeBrainError as exc:
        raise click.ClickException(format_llm_error(str(exc)))

    click.echo(text)

    if send_notification:
        title = "Nudge 早报" if time_of_day == "morning" else "Nudge 晚报"
        main_text, daemon_alert = _split_daemon_alert_section(text)
        notify(title, main_text[:200])
        if daemon_alert:
            notify("Nudge daemon 告警", daemon_alert[:240], subtitle="daemon health")


def _morning_briefing() -> str:
    config = load_config()
    calendar_names = get_configured_calendar_names(config)
    try:
        events = get_today_events(calendar_names=calendar_names)
    except Exception as exc:
        raise click.ClickException(
            _apple_read_error("Calendar", ", ".join(calendar_names) or "configured calendars", exc)
        )
    try:
        reminders = get_due_today()
    except Exception as exc:
        raise click.ClickException(_apple_read_error("Reminders", "due today", exc))
    try:
        unread = get_unread_count()
        emails = get_recent_messages(n=5)
    except Exception as exc:
        raise click.ClickException(_apple_read_error("Mail", "Inbox", exc))

    text = generate_briefing(
        events=events,
        reminders=reminders,
        unread_count=unread,
        recent_emails=emails,
    )
    daemon_alerts = _daemon_health_alerts()
    return f"{text}\n\n{daemon_alerts}" if daemon_alerts else text


def _evening_briefing() -> str:
    today = date.today().isoformat()
    config = load_config()
    calendar_names = get_configured_calendar_names(config)
    try:
        events = get_today_events(calendar_names=calendar_names)
    except Exception as exc:
        raise click.ClickException(
            _apple_read_error("Calendar", ", ".join(calendar_names) or "configured calendars", exc)
        )

    # Get today's actions from SQLite
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    all_actions = get_actions(since=today, until=tomorrow)
    completed = [a for a in all_actions if a["status"] == "done"]
    skipped = [
        a for a in all_actions
        if a["status"] in ("skipped", "pending", "created", "deferred", "blocked")
    ]

    habits = get_habit_streaks()

    text = generate_evening_review(
        events=events,
        completed_actions=completed,
        skipped_actions=skipped,
        habit_streaks=habits,
    )
    pullback = _feedback_pullback(all_actions)
    failure_followup = failure_followup_section(
        build_failure_visibility_report(all_actions),
        limit=5,
    )
    daemon_alerts = _daemon_health_alerts()
    sections = [section for section in [text, pullback, failure_followup, daemon_alerts] if section]
    return "\n\n".join(sections)


def _apple_read_error(service: str, target: str, exc: Exception) -> str:
    target_kind = "Calendar" if service == "Calendar" else service
    return classify_apple_error(service, target_kind, target, str(exc)).render()


def _feedback_pullback(actions: list[dict]) -> str:
    pending = [
        action for action in actions
        if action.get("status") in ("created", "pending")
    ][:5]
    if not pending:
        return ""
    lines = ["待反馈 action:"]
    updates = []
    for action in pending:
        scheduled = f" · {action.get('scheduled_at')}" if action.get("scheduled_at") else ""
        lines.append(f"- {action.get('summary')}{scheduled}")
        action_id = action.get("id")
        lines.append(
            f"  记录：nudge log done --id {action_id} | "
            f"nudge log partial --id {action_id} | "
            f"nudge log skipped --id {action_id}"
        )
        updates.append({
            "id": action_id,
            "status": "done",
            "note": "按晚报批量回执确认完成",
        })
    lines.extend([
        "",
        "批量回执模板:",
        "```bash",
        "nudge feedback apply --json <<'JSON'",
        json.dumps({"updates": updates}, ensure_ascii=False, indent=2),
        "JSON",
        "```",
        "提示：把未完成项的 status 改为 partial/skipped/deferred/blocked，并补 reason/next_action 后再执行。",
    ])
    return "\n".join(lines)


def _daemon_health_alerts() -> str:
    """Render daemon health issues as deterministic local briefing alerts."""
    try:
        report = build_daemon_health_report()
    except Exception as exc:
        return "\n".join([
            "Nudge daemon 告警:",
            f"- WARN DAEMON_HEALTH_UNAVAILABLE: daemon 健康巡检失败：{exc}",
            "  处理：nudge daemon health --json",
        ])

    if report.get("ok") and not report.get("issues"):
        return ""

    queue = report.get("queue") or {}
    stale_running = report.get("stale_running") or {}
    lines = [
        "Nudge daemon 告警:",
        (
            "- 队列："
            f"queued={queue.get('queued', 0)} "
            f"running={queue.get('running', 0)} "
            f"dead_letter={queue.get('dead_letter', 0)} "
            f"stale_running={stale_running.get('count', 0)} "
            f"failed={queue.get('failed', 0)}"
        ),
    ]
    for issue in report.get("issues") or []:
        severity = issue.get("severity", "warn").upper()
        code = issue.get("code", "DAEMON_HEALTH_ISSUE")
        message = issue.get("message", "")
        lines.append(f"- {severity} {code}: {message}")

    lines.append("处理：nudge daemon health --json")
    issue_codes = {issue.get("code") for issue in report.get("issues") or []}
    if "LAUNCHD_PLIST_MISSING" in issue_codes:
        lines.append("处理：nudge daemon launchd install")
    elif "LAUNCHD_NOT_LOADED" in issue_codes:
        lines.append("处理：nudge daemon launchd start")
    if "STALE_RUNNING_COMMANDS" in issue_codes:
        lines.append("处理：nudge daemon recover")
    if "DEAD_LETTER_COMMANDS" in issue_codes:
        lines.append("处理：nudge daemon queue --status dead_letter --json")
        lines.append("处理：确认不会重复写入后，nudge daemon retry --request-id <request_id>")
    return "\n".join(lines)


def _split_daemon_alert_section(text: str) -> tuple[str, str]:
    marker = "Nudge daemon 告警:"
    index = text.find(marker)
    if index < 0:
        return text, ""
    return text[:index].rstrip(), text[index:].strip()
