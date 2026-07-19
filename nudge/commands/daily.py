"""Daily sync command group."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable

import click

from nudge.commands.reminders import resolve_sync_lists, sync_completed_for_date
from nudge.config import load_config
from nudge.docs_audit import audit_docs
from nudge.failures import build_failure_visibility_report
from nudge.health import apply_health_import, parse_apple_health_export
from nudge.json_contract import versioned_payload
from nudge.state import configure_state, get_actions, log_action


DEFAULT_HEALTH_EXPORT_DIR = (
    Path.home()
    / "Library"
    / "Mobile Documents"
    / "iCloud~HealthExport"
    / "Documents"
    / "Health"
)
_PENDING_STATUSES = {"created", "pending"}
_FAILURE_KEYS = ("pending_overdue", "blocked_open", "missing_reason", "missing_next_action", "deferred_open")
DOCS_MAINTENANCE_SUMMARY = "[Nudge Docs] 本周文档需要维护"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@click.group("daily")
def daily_command():
    """Run daily maintenance workflows."""


@daily_command.command("sync")
@click.option("--date", "date_text", default=None, help="Sync local date YYYY-MM-DD; defaults to today")
@click.option("--from", "date_from", default=None, help="Force reminder backfill from YYYY-MM-DD through --date")
@click.option(
    "--lookback-days",
    default=7,
    show_default=True,
    type=click.IntRange(1, 60),
    help="How far back to look for pending reminder gaps and Health import data",
)
@click.option(
    "--list",
    "list_names",
    multiple=True,
    help="Reminder list name; repeat for multiple lists; defaults to config",
)
@click.option("--health", "health_path", type=click.Path(exists=True, dir_okay=False), default=None, help="Health export JSON/ZIP path")
@click.option("--health-from", default=None, help="Import Health dates from YYYY-MM-DD, inclusive")
@click.option("--health-to", default=None, help="Import Health dates before YYYY-MM-DD, exclusive")
@click.option("--no-health", "skip_health", is_flag=True, help="Skip Apple Health import")
@click.option(
    "--overdue-hours",
    default=24,
    show_default=True,
    type=click.IntRange(1, 24 * 30),
    help="How old pending actions must be before they are treated as overdue",
)
@click.option("--apply", "apply_changes", is_flag=True, help="Write synced results to local SQLite")
@click.option("--config", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON for scripts")
def sync_command(
    date_text: str | None,
    date_from: str | None,
    lookback_days: int,
    list_names: tuple[str, ...],
    health_path: str | None,
    health_from: str | None,
    health_to: str | None,
    skip_health: bool,
    overdue_hours: int,
    apply_changes: bool,
    config_path: str | None,
    json_output: bool,
):
    """Sync daily Health + Reminders data and show leftovers needing a human."""
    try:
        target_date = _parse_date(date_text)
        reminder_start = _reminder_start_date(target_date, date_from, lookback_days)
        health_start = _parse_date(health_from) if health_from else target_date - timedelta(days=lookback_days)
        health_end = _parse_date(health_to) if health_to else target_date + timedelta(days=1)
        if health_end <= health_start:
            raise ValueError("--health-to must be later than --health-from")
        try:
            config = load_config(config_path)
        except FileNotFoundError:
            config = {}
        if config_path:
            configure_state(config)
        reminder_lists = resolve_sync_lists(list_names, config)

        reminder_dates = _reminder_sync_dates(
            target_date=target_date,
            start_date=reminder_start,
            forced_range=bool(date_from),
        )
        reminder_results = []
        for reminder_date in reminder_dates:
            for reminder_list in reminder_lists:
                reminder_results.append(
                    sync_completed_for_date(
                        target_date=reminder_date,
                        reminder_list=reminder_list,
                        apply_changes=apply_changes,
                    )
                )
        health_payload = _sync_health(
            health_path=health_path,
            skip_health=skip_health,
            date_from=health_start.isoformat(),
            date_to=health_end.isoformat(),
            apply_changes=apply_changes,
        )
        docs_payload = _sync_docs_audit(
            target_date=target_date,
            apply_changes=apply_changes,
        )
        remaining_report = _remaining_failures(target_date, overdue_hours)
        payload = versioned_payload({
            "ok": _all_ok(reminder_results, health_payload),
            "dry_run": not apply_changes,
            "date": target_date.isoformat(),
            "reminders": {
                "list": reminder_lists[0] if len(reminder_lists) == 1 else "",
                "lists": reminder_lists,
                "dates": [item.isoformat() for item in reminder_dates],
                "results": reminder_results,
            },
            "health": health_payload,
            "docs": docs_payload,
            "remaining_failures": remaining_report,
            "human_needed": _priority_items(remaining_report, limit=10),
            "errors": _collect_errors(reminder_results, health_payload),
        })
    except (OSError, ValueError) as exc:
        payload = versioned_payload({
            "ok": False,
            "dry_run": not apply_changes,
            "date": date_text or date.today().isoformat(),
            "reminders": {"list": "", "lists": list(list_names), "dates": [], "results": []},
            "health": {"ok": False, "skipped": bool(skip_health), "errors": []},
            "remaining_failures": {},
            "human_needed": [],
            "errors": [{"code": "DAILY_SYNC_FAILED", "message": str(exc)}],
        })

    _emit(payload, json_output)
    if not payload.get("ok"):
        raise click.exceptions.Exit(1)


def _parse_date(value: str | None) -> date:
    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"date must use YYYY-MM-DD: {value}") from exc


def _reminder_start_date(target_date: date, date_from: str | None, lookback_days: int) -> date:
    if not date_from:
        return target_date - timedelta(days=lookback_days)
    start = _parse_date(date_from)
    if start > target_date:
        raise ValueError("--from must be on or before --date")
    return start


def _reminder_sync_dates(*, target_date: date, start_date: date, forced_range: bool) -> list[date]:
    if forced_range:
        return list(_date_range(start_date, target_date))

    dates = {target_date}
    yesterday = target_date - timedelta(days=1)
    if yesterday >= start_date:
        dates.add(yesterday)
    dates.update(_pending_reminder_dates(start_date, target_date))
    return sorted(dates)


def _date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _pending_reminder_dates(start_date: date, target_date: date) -> set[date]:
    start = datetime.combine(start_date, time.min).strftime("%Y-%m-%d %H:%M")
    end = datetime.combine(target_date + timedelta(days=1), time.min).strftime("%Y-%m-%d %H:%M")
    result: set[date] = set()
    for action in get_actions(since=start, until=end):
        if action.get("type") != "reminder":
            continue
        if action.get("status") not in _PENDING_STATUSES:
            continue
        scheduled_date = _date_part(action.get("scheduled_at"))
        if scheduled_date and start_date <= scheduled_date <= target_date:
            result.add(scheduled_date)
    return result


def _date_part(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _sync_health(
    *,
    health_path: str | None,
    skip_health: bool,
    date_from: str,
    date_to: str,
    apply_changes: bool,
) -> dict:
    if skip_health:
        return {"ok": True, "skipped": True, "reason": "disabled"}

    source = health_path or _latest_health_export()
    if not source:
        return {
            "ok": True,
            "skipped": True,
            "reason": "not_found",
            "search_dir": str(DEFAULT_HEALTH_EXPORT_DIR),
        }

    try:
        result = parse_apple_health_export(str(source), date_from=date_from, date_to=date_to)
        updated = (
            apply_health_import(result)
            if apply_changes
            else {"daily_upserted": 0, "workouts_upserted": 0}
        )
        return {
            "ok": True,
            "skipped": False,
            "dry_run": not apply_changes,
            "source": result.source_path,
            "date_start": result.date_start,
            "date_end": result.date_end,
            "summary": {
                "daily": len(result.daily_summaries),
                "workouts": len(result.workouts),
                "ignored_route_files": result.ignored_route_files,
                "export_xml": result.export_xml_name,
            },
            "updated": updated,
            "errors": [],
        }
    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "skipped": False,
            "dry_run": not apply_changes,
            "source": str(source),
            "summary": {"daily": 0, "workouts": 0, "ignored_route_files": 0},
            "updated": {"daily_upserted": 0, "workouts_upserted": 0},
            "errors": [{"code": "HEALTH_IMPORT_FAILED", "message": str(exc)}],
        }


def _latest_health_export() -> str | None:
    candidates: list[Path] = []
    if DEFAULT_HEALTH_EXPORT_DIR.exists():
        candidates.extend(DEFAULT_HEALTH_EXPORT_DIR.glob("health-*.json"))
        candidates.extend(DEFAULT_HEALTH_EXPORT_DIR.glob("*.zip"))
    files = [path for path in candidates if path.is_file()]
    if not files:
        return None
    latest = max(files, key=lambda path: (path.stat().st_mtime_ns, path.name))
    return str(latest)


def _sync_docs_audit(*, target_date: date, apply_changes: bool) -> dict:
    report = audit_docs(PROJECT_ROOT)
    attention_required = _docs_attention_required(report)
    payload = {
        "ok": True,
        "dry_run": not apply_changes,
        "report": report,
        "attention_required": attention_required,
        "action_created": False,
    }
    if not attention_required:
        return payload

    existing = _existing_docs_maintenance_action(target_date)
    if existing:
        payload["existing_action_id"] = existing["id"]
        return payload

    if not apply_changes:
        payload["would_create_action"] = True
        return payload

    action_id = log_action(
        action_type="maintenance",
        summary=DOCS_MAINTENANCE_SUMMARY,
        scheduled_at=f"{target_date.isoformat()} 09:00",
        status="created",
    )
    payload["action_created"] = True
    payload["action_id"] = action_id
    return payload


def _docs_attention_required(report: dict) -> bool:
    summary = report.get("summary") or {}
    return int(summary.get("errors") or 0) > 0 or int(summary.get("warnings") or 0) > 0


def _existing_docs_maintenance_action(target_date: date) -> dict | None:
    start = datetime.combine(target_date, time.min).strftime("%Y-%m-%d %H:%M")
    end = datetime.combine(target_date + timedelta(days=1), time.min).strftime("%Y-%m-%d %H:%M")
    for action in get_actions(since=start, until=end):
        if action.get("type") != "maintenance":
            continue
        if action.get("summary") != DOCS_MAINTENANCE_SUMMARY:
            continue
        if action.get("status") not in _PENDING_STATUSES:
            continue
        return action
    return None


def _remaining_failures(target_date: date, overdue_hours: int) -> dict:
    report_now = _report_now(target_date)
    return build_failure_visibility_report(
        get_actions(),
        now=report_now,
        overdue_hours=overdue_hours,
    )


def _report_now(target_date: date) -> datetime:
    today = date.today()
    if target_date == today:
        return datetime.now()
    return datetime.combine(target_date + timedelta(days=1), time.min)


def _priority_items(report: dict, *, limit: int) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for key in _FAILURE_KEYS:
        for item in report.get(key) or []:
            marker = str(item.get("id") or json.dumps(item, ensure_ascii=False, sort_keys=True))
            if marker in seen:
                continue
            seen.add(marker)
            result.append(item)
            if len(result) >= limit:
                return result
    return result


def _all_ok(reminder_results: list[dict], health_payload: dict) -> bool:
    return bool(health_payload.get("ok")) and all(bool(result.get("ok")) for result in reminder_results)


def _collect_errors(reminder_results: list[dict], health_payload: dict) -> list[dict]:
    errors: list[dict] = []
    for result in reminder_results:
        errors.extend(result.get("errors") or [])
    errors.extend(health_payload.get("errors") or [])
    return errors


def _emit(payload: dict, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    status = "DRY-RUN" if payload.get("dry_run") else "APPLY"
    click.echo(f"{status} Daily sync: {payload.get('date')}")
    if not payload.get("ok"):
        for error in payload.get("errors") or []:
            click.echo(f"  error: {error.get('message')}", err=True)
        return

    reminders = payload.get("reminders") or {}
    results = reminders.get("results") or []
    updated = sum(int(item.get("updated") or 0) for item in results if item.get("ok"))
    candidates = sum(len(item.get("candidates") or []) for item in results if item.get("ok"))
    click.echo(
        f"  reminders: {reminders.get('list')} · dates={', '.join(reminders.get('dates') or [])} "
        f"· candidates={candidates} · updated={updated}"
    )
    health = payload.get("health") or {}
    if health.get("skipped"):
        click.echo(f"  health: skipped ({health.get('reason')})")
    else:
        summary = health.get("summary") or {}
        click.echo(
            f"  health: {health.get('source')} · daily={summary.get('daily')} "
            f"· workouts={summary.get('workouts')}"
        )
    failure_summary = (payload.get("remaining_failures") or {}).get("summary") or {}
    click.echo(
        "  remaining: "
        f"overdue={failure_summary.get('pending_overdue', 0)} "
        f"blocked={failure_summary.get('blocked_open', 0)} "
        f"deferred={failure_summary.get('deferred_open', 0)} "
        f"missing_reason={failure_summary.get('missing_reason', 0)} "
        f"missing_next_action={failure_summary.get('missing_next_action', 0)}"
    )
    for item in payload.get("human_needed") or []:
        click.echo(f"  - {item.get('followup_command')}")
