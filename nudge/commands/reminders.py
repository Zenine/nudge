"""Apple Reminders sync helpers."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import click

from nudge.action_hygiene import normalize_reminder_title
from nudge.apple.reminders import complete_reminder, query_completed_on_date, query_due_on_date
from nudge.config import DEFAULT_REMINDER_LIST, get_defaults, load_config
from nudge.feedback import build_feedback
from nudge.json_contract import versioned_payload
from nudge.sleep_reminders import is_sleep_terminal_action
from nudge.state import complete_action, get_actions, skip_later_sleep_reminders_after_completion


GENERAL_COMPLETED_MATCH_EARLY_HOURS = 12
GENERAL_COMPLETED_MATCH_LATE_HOURS = 12
SLEEP_COMPLETED_MATCH_EARLY_HOURS = 6
SLEEP_COMPLETED_MATCH_LATE_HOURS = 6


@click.group("reminders")
def reminders_command():
    """Sync Apple Reminders state back into Nudge."""
    pass


@reminders_command.command("sync-completed")
@click.option("--date", "date_text", default=None, help="Sync one local date, YYYY-MM-DD; defaults to today")
@click.option("--list", "list_name", default=None, help="Reminder list name; defaults to config")
@click.option("--apply", "apply_changes", is_flag=True, help="Write completed candidates back to SQLite; silence later sleep reminders")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON for scripts")
def sync_completed_command(date_text, list_name, apply_changes, config_path, json_output):
    """Mark Nudge reminders done when Apple Reminders no longer lists them as incomplete."""
    try:
        target_date = _parse_date(date_text)
        config = load_config(config_path)
        defaults = get_defaults(config)
        reminder_list = list_name or defaults.get("default_reminder_list", DEFAULT_REMINDER_LIST)
        payload = sync_completed_for_date(
            target_date=target_date,
            reminder_list=reminder_list,
            apply_changes=apply_changes,
        )
        _emit(payload, json_output)
        if not payload.get("ok"):
            raise click.exceptions.Exit(1)
    except ValueError as exc:
        payload = _error_payload(
            _parse_date(None),
            list_name or "",
            str(exc),
            dry_run=not apply_changes,
        )
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)


def sync_completed_for_date(
    *,
    target_date: date,
    reminder_list: str,
    apply_changes: bool,
) -> dict:
    """Return the same sync payload as the CLI for one local date.

    The daily workflow needs the Reminders completion logic without going
    through Click, so this helper keeps the mutation and matching behavior in
    one place.
    """
    actions = _reminder_actions_for_date(target_date)
    ok, incomplete = query_due_on_date(
        list_name=reminder_list,
        target_date=target_date,
    )
    if not ok:
        return _error_payload(target_date, reminder_list, str(incomplete), dry_run=not apply_changes)

    warnings = []
    completed_ok, completed = query_completed_on_date(
        list_name=reminder_list,
        target_date=target_date,
    )
    if not completed_ok:
        warnings.append({
            "code": "REMINDERS_COMPLETED_QUERY_FAILED",
            "message": str(completed),
        })
        completed = []
    else:
        next_completed_ok, next_completed = query_completed_on_date(
            list_name=reminder_list,
            target_date=target_date + timedelta(days=1),
        )
        if next_completed_ok:
            completed = list(completed) + list(next_completed)
        else:
            warnings.append({
                "code": "REMINDERS_COMPLETED_QUERY_FAILED",
                "message": str(next_completed),
            })

    candidates, open_count = _completed_candidates(actions, incomplete, completed)
    auto_skipped_after_sleep = []
    auto_skipped_ids = set()
    updated_count = 0
    if apply_changes:
        action_by_id = {action.get("id"): action for action in actions}
        for action in candidates:
            if action.get("id") in auto_skipped_ids:
                continue
            source_action = action_by_id.get(action.get("id"), action)
            skipped = complete_action(
                action["id"],
                feedback=_completion_feedback(source_action, action, reminder_list, target_date),
                completed_at=action.get("completed_at"),
            ) or []
            updated_count += 1
            auto_skipped_ids.update(
                skipped_action.get("id")
                for skipped_action in skipped
                if skipped_action.get("id")
            )
            auto_skipped_after_sleep.extend(
                _complete_auto_skipped_sleep_reminders(skipped, reminder_list)
            )
        auto_skipped_after_sleep.extend(
            _backfill_completed_sleep_cascade(
                target_date=target_date,
                reminder_list=reminder_list,
                auto_skipped_ids=auto_skipped_ids,
            )
        )

    return _payload(
        target_date=target_date,
        reminder_list=reminder_list,
        checked=len(actions),
        open_count=open_count,
        candidates=candidates,
        updated=updated_count if apply_changes else 0,
        dry_run=not apply_changes,
        auto_skipped_after_sleep=auto_skipped_after_sleep,
        warnings=warnings,
    )


def _backfill_completed_sleep_cascade(
    *,
    target_date: date,
    reminder_list: str,
    auto_skipped_ids: set[str],
) -> list[dict]:
    """Complete later sleep reminders when the terminal item was already done.

    A daily sync may be rerun after the bedtime/关机流程 reminder has already
    been marked done in SQLite. In that case there is no new completion
    candidate, but later sleep reminders should still be neutralized and
    completed in Apple Reminders.
    """
    start = datetime.combine(target_date, datetime.min.time())
    end = start + timedelta(days=1)
    results: list[dict] = []
    for action in get_actions(
        since=start.strftime("%Y-%m-%d %H:%M"),
        until=end.strftime("%Y-%m-%d %H:%M"),
    ):
        if action.get("type") != "reminder" or action.get("status") != "done":
            continue
        skipped = skip_later_sleep_reminders_after_completion(action["id"]) or []
        new_skipped = [
            item for item in skipped
            if item.get("id") and item.get("id") not in auto_skipped_ids
        ]
        auto_skipped_ids.update(
            item.get("id")
            for item in new_skipped
            if item.get("id")
        )
        results.extend(_complete_auto_skipped_sleep_reminders(new_skipped, reminder_list))
    return results


def _parse_date(value: str | None) -> date:
    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"date must use YYYY-MM-DD: {value}") from exc


def _reminder_actions_for_date(target_date: date) -> list[dict]:
    start = datetime.combine(target_date, datetime.min.time())
    end = start + timedelta(days=1)
    actions = get_actions(
        since=start.strftime("%Y-%m-%d %H:%M"),
        until=end.strftime("%Y-%m-%d %H:%M"),
    )
    return [
        action
        for action in actions
        if action.get("type") == "reminder"
        and action.get("status") in ("created", "pending")
        and str(action.get("scheduled_at") or "").startswith(target_date.isoformat())
    ]


def _completed_candidates(
    actions: list[dict],
    incomplete: list[dict],
    completed: list[dict] | None = None,
) -> tuple[list[dict], int]:
    completed = completed or []
    open_action_ids = {
        action["id"]
        for action in actions
        if _matches_any_incomplete(action, incomplete)
    }
    candidates = []
    for action in actions:
        if action.get("id") in open_action_ids:
            continue
        completed_match = _matching_completed(action, completed)
        candidates.append(_candidate_payload(action, completed_match))
    return candidates, len(open_action_ids)


def _matches_any_incomplete(action: dict, incomplete: list[dict]) -> bool:
    scheduled_at = str(action.get("scheduled_at") or "")
    action_time = _time_part(scheduled_at)
    summary = str(action.get("summary") or "")
    normalized_summary = normalize_reminder_title(summary, scheduled_at)
    for reminder in incomplete:
        if str(reminder.get("due_time") or "") != action_time:
            continue
        reminder_name = str(reminder.get("name") or "")
        if reminder_name == summary:
            return True
        if normalize_reminder_title(reminder_name, scheduled_at) == normalized_summary:
            return True
    return False


def _matching_completed(action: dict, completed: list[dict]) -> dict | None:
    scheduled_at = str(action.get("scheduled_at") or "")
    action_time = _time_part(scheduled_at)
    summary = str(action.get("summary") or "")
    normalized_summary = normalize_reminder_title(summary, scheduled_at)
    matches: list[tuple[timedelta, dict]] = []
    for reminder in completed:
        if str(reminder.get("due_time") or "") != action_time:
            continue
        reminder_name = str(reminder.get("name") or "")
        if reminder_name == summary or normalize_reminder_title(reminder_name, scheduled_at) == normalized_summary:
            score = _completed_at_match_score(action, reminder)
            if score is not None:
                matches.append((score, reminder))
    if not matches:
        return None
    return min(matches, key=lambda item: item[0])[1]


def _completed_at_match_score(action: dict, reminder: dict) -> timedelta | None:
    completed_at = str(reminder.get("completed_at") or "").strip()
    if not completed_at:
        return timedelta.max
    scheduled_at = str(action.get("scheduled_at") or "")
    try:
        scheduled_time = datetime.strptime(scheduled_at[:16], "%Y-%m-%d %H:%M")
        completed_time = datetime.strptime(completed_at[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return timedelta.max
    delta = completed_time - scheduled_time
    if is_sleep_terminal_action(action):
        early = timedelta(hours=SLEEP_COMPLETED_MATCH_EARLY_HOURS)
        late = timedelta(hours=SLEEP_COMPLETED_MATCH_LATE_HOURS)
    else:
        early = timedelta(hours=GENERAL_COMPLETED_MATCH_EARLY_HOURS)
        late = timedelta(hours=GENERAL_COMPLETED_MATCH_LATE_HOURS)
    if not -early <= delta <= late:
        return None
    return delta if delta >= timedelta(0) else -delta


def _time_part(scheduled_at: str) -> str:
    try:
        return scheduled_at.split(" ", 1)[1][:5]
    except IndexError:
        return ""


def _candidate_payload(action: dict, completed_match: dict | None = None) -> dict:
    item = {
        "id": action.get("id"),
        "summary": action.get("summary"),
        "scheduled_at": action.get("scheduled_at"),
    }
    if completed_match and completed_match.get("completed_at"):
        item["completed_at"] = completed_match["completed_at"]
    return item


def _completion_feedback(action: dict, candidate: dict, reminder_list: str, target_date: date) -> dict:
    completed_at = candidate.get("completed_at")
    if completed_at:
        note = "Apple Reminders completionDate 已同步回 Nudge。"
    else:
        note = "Apple Reminders 未完成列表中已不存在该 Nudge reminder，按兼容候选写回。"
    extra = {
        "reminder_list": reminder_list,
        "sync_date": target_date.isoformat(),
        "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if completed_at:
        extra["apple_completed_at"] = completed_at
    if completed_at and is_sleep_terminal_action(action):
        extra["event_type"] = "sleep_start"
        extra["event_at"] = completed_at
    return build_feedback(
        source="nudge reminders sync-completed",
        channel="reminders.sync_completed",
        source_type="objective",
        note=note,
        extra=extra,
    )


def _complete_auto_skipped_sleep_reminders(actions: list[dict], reminder_list: str) -> list[dict]:
    results = []
    for action in actions:
        summary = str(action.get("summary") or "")
        scheduled_at = str(action.get("scheduled_at") or "")
        ok, message = _complete_reminder_by_possible_titles(summary, scheduled_at, reminder_list)
        item = _candidate_payload(action)
        item["apple_completed"] = ok
        item["apple_message"] = message
        results.append(item)
    return results


def _complete_reminder_by_possible_titles(summary: str, scheduled_at: str, reminder_list: str) -> tuple[bool, str]:
    titles = []
    for title in (summary, normalize_reminder_title(summary, scheduled_at)):
        if title and title not in titles:
            titles.append(title)
    if not titles:
        return False, "missing reminder title"

    errors = []
    for title in titles:
        ok, message = complete_reminder(title, reminder_list)
        if ok:
            return True, message
        errors.append(f"{title}: {message}")
    return False, "; ".join(errors)


def _payload(
    *,
    target_date: date,
    reminder_list: str,
    checked: int,
    open_count: int,
    candidates: list[dict],
    updated: int,
    dry_run: bool,
    auto_skipped_after_sleep: list[dict] | None = None,
    warnings: list[dict] | None = None,
) -> dict:
    return versioned_payload({
        "ok": True,
        "dry_run": dry_run,
        "date": target_date.isoformat(),
        "list": reminder_list,
        "checked": checked,
        "open": open_count,
        "candidates": candidates,
        "updated": updated,
        "auto_skipped_after_sleep": auto_skipped_after_sleep or [],
        "warnings": warnings or [],
        "errors": [],
    })


def _error_payload(target_date: date, reminder_list: str, error: str, dry_run: bool) -> dict:
    return versioned_payload({
        "ok": False,
        "dry_run": dry_run,
        "date": target_date.isoformat(),
        "list": reminder_list,
        "checked": 0,
        "open": 0,
        "candidates": [],
        "updated": 0,
        "auto_skipped_after_sleep": [],
        "errors": [{"code": "REMINDERS_SYNC_FAILED", "message": error}],
    })


def _emit(payload: dict, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    status = "DRY-RUN" if payload.get("dry_run") else "APPLY"
    click.echo(f"{status} Reminders sync: {payload.get('date')} · {payload.get('list')}")
    if not payload.get("ok"):
        click.echo(f"  error: {payload['errors'][0]['message']}", err=True)
        return
    click.echo(f"  checked: {payload.get('checked')} · still open: {payload.get('open')} · candidates: {len(payload.get('candidates', []))}")
    for candidate in payload.get("candidates", []):
        click.echo(f"  - {candidate['id']} {candidate['scheduled_at']} {candidate['summary']}")
    for item in payload.get("auto_skipped_after_sleep", []):
        apple = "Apple completed" if item.get("apple_completed") else "Apple complete failed"
        click.echo(f"  ☾ auto-skipped after sleep: {item['id']} {item['scheduled_at']} {item['summary']} · {apple}")
    if payload.get("dry_run") and payload.get("candidates"):
        click.echo("  add --apply to write these candidates back to SQLite")
