"""Apple Reminders sync helpers."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import click

from nudge.action_hygiene import normalize_reminder_title
from nudge.apple.reminders import (
    complete_reminder,
    make_reminder_external_id,
    query_completed_on_date,
    query_due_on_date,
    set_reminder_external_id,
)
from nudge.config import DEFAULT_REMINDER_LIST, get_defaults, load_config
from nudge.feedback import build_feedback
from nudge.json_contract import versioned_payload
from nudge.sleep_reminders import is_sleep_terminal_action
from nudge.state import (
    complete_action,
    configure_state,
    get_actions,
    skip_later_sleep_reminders_after_completion,
    update_action_external_id,
)


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
@click.option(
    "--list",
    "list_names",
    multiple=True,
    help="Reminder list name; repeat for multiple lists; defaults to config",
)
@click.option("--apply", "apply_changes", is_flag=True, help="Write completed candidates back to SQLite; silence later sleep reminders")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON for scripts")
def sync_completed_command(date_text, list_names, apply_changes, config_path, json_output):
    """Mark Nudge reminders done after an explicit Apple completion match."""
    try:
        target_date = _parse_date(date_text)
        config = load_config(config_path)
        if config_path:
            configure_state(config)
        reminder_lists = resolve_sync_lists(list_names, config)
        payload = sync_completed_for_lists(
            target_date=target_date,
            reminder_lists=reminder_lists,
            apply_changes=apply_changes,
        )
        _emit(payload, json_output)
        if not payload.get("ok"):
            raise click.exceptions.Exit(1)
    except ValueError as exc:
        payload = _error_payload(
            _parse_date(None),
            ",".join(list_names),
            str(exc),
            dry_run=not apply_changes,
        )
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)


def resolve_sync_lists(explicit_names, config: dict) -> list[str]:
    """Resolve an ordered, duplicate-free set of lists for completion sync."""
    configured = (config.get("reminders") or {}).get("sync_lists")
    if explicit_names:
        raw_names = list(explicit_names)
    elif configured is not None:
        if not isinstance(configured, list):
            raise ValueError("[reminders].sync_lists must be an array of list names")
        raw_names = configured
    else:
        defaults = get_defaults(config)
        raw_names = [defaults.get("default_reminder_list", DEFAULT_REMINDER_LIST)]

    result: list[str] = []
    for raw_name in raw_names:
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError("reminder list names must be non-empty strings")
        name = raw_name.strip()
        if name not in result:
            result.append(name)
    if not result:
        raise ValueError("at least one reminder list is required")
    return result


def sync_completed_for_lists(
    *,
    target_date: date,
    reminder_lists: list[str],
    apply_changes: bool,
) -> dict:
    """Sync one due date across multiple Apple Reminders lists safely."""
    results = [
        sync_completed_for_date(
            target_date=target_date,
            reminder_list=reminder_list,
            apply_changes=apply_changes,
        )
        for reminder_list in reminder_lists
    ]

    def annotated_items(key: str) -> list[dict]:
        items: list[dict] = []
        for result in results:
            for item in result.get(key) or []:
                items.append({**item, "list": item.get("list") or result.get("list")})
        return items

    return versioned_payload({
        "ok": all(result.get("ok") for result in results),
        "dry_run": not apply_changes,
        "date": target_date.isoformat(),
        "list": reminder_lists[0] if len(reminder_lists) == 1 else "",
        "lists": reminder_lists,
        "checked": sum(int(result.get("checked") or 0) for result in results),
        "open": sum(int(result.get("open") or 0) for result in results),
        "candidates": annotated_items("candidates"),
        "updated": sum(int(result.get("updated") or 0) for result in results),
        "auto_skipped_after_sleep": annotated_items("auto_skipped_after_sleep"),
        "warnings": annotated_items("warnings"),
        "errors": annotated_items("errors"),
        "results": results,
    })


@reminders_command.command("backfill-ids")
@click.option("--from", "from_text", default=None, help="Backfill actions scheduled on/after YYYY-MM-DD")
@click.option("--to", "to_text", default=None, help="Backfill actions scheduled before YYYY-MM-DD")
@click.option("--list", "list_name", default=None, help="Reminder list name; defaults to config")
@click.option("--include-completed", is_flag=True, help="Also inspect already completed Apple Reminders")
@click.option("--limit", type=int, default=None, help="Maximum legacy actions to inspect")
@click.option("--apply", "apply_changes", is_flag=True, help="Write IDs to Apple Reminders and SQLite")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON for scripts")
def backfill_ids_command(
    from_text,
    to_text,
    list_name,
    include_completed,
    limit,
    apply_changes,
    config_path,
    json_output,
):
    """Attach stable Nudge IDs to legacy Apple Reminders."""
    try:
        config = load_config(config_path)
        if config_path:
            configure_state(config)
        defaults = get_defaults(config)
        reminder_list = list_name or defaults.get("default_reminder_list", DEFAULT_REMINDER_LIST)
        from_date = date.fromisoformat(from_text) if from_text else None
        to_date = date.fromisoformat(to_text) if to_text else None
        payload = backfill_ids(
            reminder_list=reminder_list,
            from_date=from_date,
            to_date=to_date,
            include_completed=include_completed,
            limit=limit,
            apply_changes=apply_changes,
        )
        _emit_backfill(payload, json_output)
        if not payload.get("ok"):
            raise click.exceptions.Exit(1)
    except ValueError as exc:
        payload = versioned_payload({
            "ok": False,
            "dry_run": not apply_changes,
            "list": list_name or "",
            "checked": 0,
            "would_update": 0,
            "updated": 0,
            "candidates": [],
            "missing": [],
            "ambiguous": [],
            "skipped": [],
            "errors": [{"code": "REMINDERS_BACKFILL_FAILED", "message": str(exc)}],
        })
        _emit_backfill(payload, json_output)
        raise click.exceptions.Exit(1)


def backfill_ids(
    *,
    reminder_list: str,
    from_date: date | None,
    to_date: date | None,
    include_completed: bool,
    limit: int | None,
    apply_changes: bool,
) -> dict:
    """Backfill stable external ids for legacy reminder actions."""
    actions = _legacy_reminder_actions(
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        reminder_list=reminder_list,
    )
    candidates: list[dict] = []
    missing: list[dict] = []
    ambiguous: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    updated = 0

    query_cache: dict[tuple[date, bool], list[dict] | str] = {}

    for action in actions:
        target_date = _action_date(action)
        if target_date is None:
            skipped.append({**_backfill_action_payload(action), "reason": "missing_or_invalid_scheduled_at"})
            continue
        ok, incomplete = _cached_due_reminders(query_cache, reminder_list, target_date)
        if not ok:
            errors.append({
                "code": "REMINDERS_QUERY_FAILED",
                "id": action.get("id"),
                "message": str(incomplete),
            })
            continue
        reminders = list(incomplete)
        if include_completed:
            for completed_date in (target_date, target_date + timedelta(days=1)):
                completed_ok, completed = _cached_completed_reminders(query_cache, reminder_list, completed_date)
                if completed_ok:
                    reminders.extend(completed)
                else:
                    errors.append({
                        "code": "REMINDERS_COMPLETED_QUERY_FAILED",
                        "id": action.get("id"),
                        "message": str(completed),
                    })
        matches = _matching_reminders_for_backfill(action, reminders)
        item = _backfill_action_payload(action)
        item["matches"] = len(matches)
        if len(matches) == 0:
            missing.append(item)
            continue
        if len(matches) > 1:
            item["matched_titles"] = [match.get("name") for match in matches]
            ambiguous.append(item)
            continue

        external_id = make_reminder_external_id()
        item["external_id"] = external_id
        candidates.append(item)
        if apply_changes:
            ok, message = set_reminder_external_id(
                str(matches[0].get("name") or action.get("summary") or ""),
                reminder_list,
                str(action.get("scheduled_at") or ""),
                external_id,
            )
            item["apple_message"] = message
            if not ok:
                errors.append({
                    "code": "REMINDERS_SET_ID_FAILED",
                    "id": action.get("id"),
                    "message": message,
                })
                continue
            update_action_external_id(str(action["id"]), external_id)
            updated += 1

    return versioned_payload({
        "ok": not errors,
        "dry_run": not apply_changes,
        "list": reminder_list,
        "from": from_date.isoformat() if from_date else None,
        "to": to_date.isoformat() if to_date else None,
        "include_completed": include_completed,
        "checked": len(actions),
        "would_update": len(candidates),
        "updated": updated,
        "candidates": candidates,
        "missing": missing,
        "ambiguous": ambiguous,
        "skipped": skipped,
        "errors": errors,
    })


def _cached_due_reminders(
    cache: dict[tuple[date, bool], list[dict] | str],
    reminder_list: str,
    target_date: date,
) -> tuple[bool, list[dict] | str]:
    key = (target_date, False)
    if key not in cache:
        ok, result = query_due_on_date(reminder_list, target_date)
        cache[key] = result if ok else str(result)
    result = cache[key]
    return (False, result) if isinstance(result, str) else (True, result)


def _cached_completed_reminders(
    cache: dict[tuple[date, bool], list[dict] | str],
    reminder_list: str,
    target_date: date,
) -> tuple[bool, list[dict] | str]:
    key = (target_date, True)
    if key not in cache:
        ok, result = query_completed_on_date(reminder_list, target_date)
        cache[key] = result if ok else str(result)
    result = cache[key]
    return (False, result) if isinstance(result, str) else (True, result)


def _legacy_reminder_actions(
    *,
    from_date: date | None,
    to_date: date | None,
    limit: int | None,
    reminder_list: str,
) -> list[dict]:
    since = f"{from_date.isoformat()} 00:00" if from_date else None
    until = f"{to_date.isoformat()} 00:00" if to_date else None
    actions = [
        action
        for action in get_actions(since=since, until=until)
        if action.get("type") == "reminder"
        and not action.get("external_id")
        and action.get("summary")
        and action.get("scheduled_at")
        and _belongs_to_reminder_list(action, reminder_list)
    ]
    actions.sort(key=lambda item: str(item.get("scheduled_at") or ""))
    if limit is not None:
        return actions[:max(limit, 0)]
    return actions


def _action_date(action: dict) -> date | None:
    try:
        return date.fromisoformat(str(action.get("scheduled_at") or "")[:10])
    except ValueError:
        return None


def _backfill_action_payload(action: dict) -> dict:
    return {
        "id": action.get("id"),
        "summary": action.get("summary"),
        "scheduled_at": action.get("scheduled_at"),
        "status": action.get("status"),
    }


def _matching_reminders_for_backfill(action: dict, reminders: list[dict]) -> list[dict]:
    scheduled_at = str(action.get("scheduled_at") or "")
    action_time = _time_part(scheduled_at)
    summary = str(action.get("summary") or "")
    normalized_summary = normalize_reminder_title(summary, scheduled_at)
    matches = []
    for reminder in reminders:
        due_at = str(reminder.get("due_at") or "")
        if due_at and due_at[:16] != scheduled_at[:16]:
            continue
        if str(reminder.get("due_time") or "") != action_time:
            continue
        reminder_name = str(reminder.get("name") or "")
        if reminder_name == summary or normalize_reminder_title(reminder_name, scheduled_at) == normalized_summary:
            matches.append(reminder)
    return matches


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
    actions = _reminder_actions_for_date(target_date, reminder_list=reminder_list)
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
        if (
            action.get("type") != "reminder"
            or action.get("status") != "done"
            or not _belongs_to_reminder_list(action, reminder_list)
        ):
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


def _reminder_actions_for_date(target_date: date, *, reminder_list: str) -> list[dict]:
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
        and _belongs_to_reminder_list(action, reminder_list)
    ]


def _belongs_to_reminder_list(action: dict, reminder_list: str) -> bool:
    """Keep legacy unassigned actions visible while honoring known ownership."""
    assigned = action.get("reminder_list")
    return not assigned or assigned == reminder_list


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
        if completed_match is None:
            continue
        candidates.append(_candidate_payload(action, completed_match))
    return candidates, len(open_action_ids)


def _matches_any_incomplete(action: dict, incomplete: list[dict]) -> bool:
    scheduled_at = str(action.get("scheduled_at") or "")
    action_time = _time_part(scheduled_at)
    summary = str(action.get("summary") or "")
    normalized_summary = normalize_reminder_title(summary, scheduled_at)
    for reminder in incomplete:
        due_at = str(reminder.get("due_at") or "")
        if due_at and due_at[:16] != scheduled_at[:16]:
            continue
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
        due_at = str(reminder.get("due_at") or "")
        if due_at and due_at[:16] != scheduled_at[:16]:
            continue
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
        note = "Apple Reminders 已返回明确完成记录，但未提供 completionDate。"
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
        target_list = str(action.get("reminder_list") or reminder_list)
        ok, message = _complete_reminder_by_possible_titles(summary, scheduled_at, target_list)
        item = _candidate_payload(action)
        item["list"] = target_list
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
        ok, message = complete_reminder(title, reminder_list, due_date=scheduled_at or None)
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


def _emit_backfill(payload: dict, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    status = "DRY-RUN" if payload.get("dry_run") else "APPLY"
    click.echo(f"{status} Reminders ID backfill · {payload.get('list')}")
    if not payload.get("ok"):
        for error in payload.get("errors", []):
            click.echo(f"  error: {error.get('message')}", err=True)
    click.echo(
        "  checked: "
        f"{payload.get('checked')} · candidates: {payload.get('would_update')} · updated: {payload.get('updated')}"
    )
    if payload.get("missing"):
        click.echo(f"  missing: {len(payload['missing'])}")
    if payload.get("ambiguous"):
        click.echo(f"  ambiguous: {len(payload['ambiguous'])}")
    for candidate in payload.get("candidates", []):
        click.echo(f"  - {candidate['id']} {candidate['scheduled_at']} {candidate['summary']}")
    if payload.get("dry_run") and payload.get("candidates"):
        click.echo("  add --apply to write IDs to Apple Reminders and SQLite")
