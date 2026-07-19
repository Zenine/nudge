"""CLI orchestration for legacy Reminder list ownership backfill."""

from __future__ import annotations

import json
import tomllib
from datetime import date

import click

from nudge.apple.reminders import query_all_due_on_date
from nudge.commands.db import backup_database
from nudge.config import load_config
from nudge.json_contract import versioned_payload
from nudge.reminder_lists import (
    parse_strict_minute,
    plan_list_backfill,
    resolve_sync_lists,
    select_list_backfill_actions,
)
from nudge.state import (
    apply_reminder_list_backfill,
    configure_state,
    get_actions,
)


CONFIRMATION_INVALID = "REMINDER_LIST_BACKFILL_CONFIRMATION_INVALID"
RANGE_INVALID = "REMINDER_LIST_BACKFILL_RANGE_INVALID"
CONFIG_INVALID = "REMINDER_LIST_BACKFILL_CONFIG_INVALID"
QUERY_FAILED = "REMINDER_LIST_BACKFILL_QUERY_FAILED"
WRITE_FAILED = "REMINDER_LIST_BACKFILL_WRITE_FAILED"


@click.command("backfill-lists")
@click.option("--from", "from_text", default=None, help="Include actions on/after YYYY-MM-DD")
@click.option("--to", "to_text", default=None, help="Exclude actions on/after YYYY-MM-DD")
@click.option("--list", "list_names", multiple=True, help="Reminder list; repeat to override config")
@click.option("--limit", default="100", help="Maximum actions to inspect, from 1 to 500")
@click.option("--apply", "apply_changes", is_flag=True, help="Apply an approved backfill")
@click.option("--yes", is_flag=True, help="Confirm an --apply operation")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON for scripts")
def backfill_lists_command(
    from_text,
    to_text,
    list_names,
    limit,
    apply_changes,
    yes,
    config_path,
    json_output,
):
    """Inspect legacy reminder actions missing list ownership."""
    dry_run = not apply_changes

    if yes and not apply_changes:
        payload = _error_payload(
            code=CONFIRMATION_INVALID,
            message="--yes requires --apply.",
            dry_run=dry_run,
            list_names=list_names,
            from_text=from_text,
            to_text=to_text,
            limit=None,
        )
        _finish(payload, json_output)

    try:
        date_from = _parse_date(from_text)
        date_to = _parse_date(to_text)
        parsed_limit = _parse_limit(limit)
        if date_from is not None and date_to is not None and date_to <= date_from:
            raise ValueError("invalid range")
    except ValueError:
        payload = _error_payload(
            code=RANGE_INVALID,
            message=(
                "Use valid YYYY-MM-DD dates, --to later than --from, "
                "and --limit from 1 to 500."
            ),
            dry_run=dry_run,
            list_names=list_names,
            from_text=from_text,
            to_text=to_text,
            limit=None,
        )
        _finish(payload, json_output)

    try:
        config = load_config(config_path)
        configure_state(config)
        reminder_lists = resolve_sync_lists(list_names, config)
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        payload = _error_payload(
            code=CONFIG_INVALID,
            message="Unable to load Reminder list backfill configuration.",
            dry_run=dry_run,
            list_names=list_names,
            from_text=from_text,
            to_text=to_text,
            limit=parsed_limit,
        )
        _finish(payload, json_output)

    try:
        actions = get_actions()
        batch = select_list_backfill_actions(
            actions,
            date_from=date_from,
            date_to=date_to,
            limit=parsed_limit,
        )
    except Exception:
        payload = _error_payload(
            code=WRITE_FAILED,
            message="Unable to read Nudge actions.",
            dry_run=dry_run,
            list_names=reminder_lists,
            from_text=from_text,
            to_text=to_text,
            limit=parsed_limit,
        )
        _finish(payload, json_output)

    apple_rows: list[dict] = []
    errors: list[dict] = []
    row_number = 0
    seen_queries: set[tuple[str, date]] = set()
    query_dates = tuple(dict.fromkeys(batch.query_dates))
    for list_name in reminder_lists:
        for target_date in query_dates:
            query_key = (list_name, target_date)
            if query_key in seen_queries:
                continue
            seen_queries.add(query_key)
            try:
                ok, rows = query_all_due_on_date(list_name, target_date)
            except Exception:
                ok, rows = False, []

            query_invalid = not ok or not isinstance(rows, list)
            query_message = (
                rows.strip()
                if not ok and isinstance(rows, str) and rows.strip()
                else "Unable to query this Reminder list and date."
            )
            if isinstance(rows, list):
                for row in rows:
                    current_number = row_number
                    row_number += 1
                    if not _valid_query_row(row, list_name):
                        query_invalid = True
                        continue
                    apple_rows.append({
                        "row_key": current_number,
                        "name": row["name"],
                        "due_at": row["due_at"],
                        "list": list_name,
                    })
            if query_invalid:
                errors.append({
                    "code": QUERY_FAILED,
                    "list": list_name,
                    "date": target_date.isoformat(),
                    "message": query_message,
                })

    plan = plan_list_backfill(batch.actions, apple_rows)
    snapshots = {
        action["id"]: dict(action)
        for action in batch.actions
        if isinstance(action.get("id"), str)
    }
    # Task 5 consumes these complete snapshots when the write path is connected.
    _ = snapshots
    payload = versioned_payload({
        "ok": not errors,
        "dry_run": dry_run,
        "apply_allowed": not errors and bool(plan["candidates"]),
        "lists": reminder_lists,
        "range": {
            "from": date_from.isoformat() if date_from else None,
            "to": date_to.isoformat() if date_to else None,
        },
        "limit": parsed_limit,
        "total_eligible": batch.total_eligible,
        "remaining": batch.remaining,
        "candidates": plan["candidates"],
        "missing": plan["missing"],
        "ambiguous": plan["ambiguous"],
        "invalid": batch.invalid,
        "updated": 0,
        "backup": None,
        "conflicts": [],
        "errors": errors,
    })
    _emit(payload, json_output)
    if not payload["ok"]:
        raise click.exceptions.Exit(1)


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("date must use YYYY-MM-DD")
    return parsed


def _parse_limit(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid limit") from exc
    if str(parsed) != value or not 1 <= parsed <= 500:
        raise ValueError("invalid limit")
    return parsed


def _valid_query_row(row: object, list_name: str) -> bool:
    if not isinstance(row, dict) or row.get("list") != list_name:
        return False
    name = row.get("name")
    if not isinstance(name, str) or not name.strip():
        return False
    return parse_strict_minute(row.get("due_at")) is not None


def _error_payload(
    *,
    code: str,
    message: str,
    dry_run: bool,
    list_names,
    from_text: str | None,
    to_text: str | None,
    limit: int | None,
) -> dict:
    lists = [
        name.strip()
        for name in list_names
        if isinstance(name, str) and name.strip()
    ]
    return versioned_payload({
        "ok": False,
        "dry_run": dry_run,
        "apply_allowed": False,
        "lists": lists,
        "range": {"from": from_text, "to": to_text},
        "limit": limit,
        "total_eligible": 0,
        "remaining": 0,
        "candidates": [],
        "missing": [],
        "ambiguous": [],
        "invalid": [],
        "updated": 0,
        "backup": None,
        "conflicts": [],
        "errors": [{"code": code, "message": message}],
    })


def _finish(payload: dict, json_output: bool) -> None:
    _emit(payload, json_output)
    raise click.exceptions.Exit(1)


def _public_payload(payload: dict) -> dict:
    backup = payload.get("backup")
    public_backup = None
    if isinstance(backup, dict):
        public_backup = {
            "path": backup.get("path"),
            "integrity": backup.get("integrity", backup.get("integrity_check")),
        }

    conflicts = []
    for conflict in payload.get("conflicts") or []:
        if isinstance(conflict, str):
            conflicts.append(conflict)
        elif isinstance(conflict, dict):
            conflicts.append({
                key: conflict.get(key)
                for key in ("id", "reason")
                if key in conflict
            })

    return {
        "schema_version": payload.get("schema_version"),
        "ok": bool(payload.get("ok")),
        "dry_run": bool(payload.get("dry_run")),
        "apply_allowed": bool(payload.get("apply_allowed")),
        "lists": [item for item in payload.get("lists") or [] if isinstance(item, str)],
        "range": {
            "from": (payload.get("range") or {}).get("from"),
            "to": (payload.get("range") or {}).get("to"),
        },
        "limit": payload.get("limit"),
        "total_eligible": payload.get("total_eligible", 0),
        "remaining": payload.get("remaining", 0),
        "candidates": _public_items(payload, "candidates", (
            "id", "summary", "scheduled_at", "status", "current_reminder_list",
            "target_list", "match_type",
        )),
        "missing": _public_items(payload, "missing", (
            "id", "summary", "scheduled_at", "status",
        )),
        "ambiguous": _public_items(payload, "ambiguous", (
            "id", "summary", "scheduled_at", "status", "matches", "matched_lists",
        )),
        "invalid": _public_items(payload, "invalid", (
            "id", "summary", "scheduled_at", "reason",
        )),
        "updated": payload.get("updated", 0),
        "backup": public_backup,
        "conflicts": conflicts,
        "errors": _public_items(payload, "errors", ("code", "list", "date", "message")),
    }


def _public_items(payload: dict, key: str, allowed: tuple[str, ...]) -> list[dict]:
    result = []
    for item in payload.get(key) or []:
        if not isinstance(item, dict):
            continue
        result.append({field: item.get(field) for field in allowed if field in item})
    return result


def _emit(payload: dict, json_output: bool) -> None:
    public = _public_payload(payload)
    if json_output:
        click.echo(json.dumps(public, ensure_ascii=False))
        return

    status = "DRY-RUN" if public["dry_run"] else "APPLY"
    click.echo(f"{status} Reminder list backfill · {', '.join(public['lists'])}")
    click.echo(
        "  eligible: "
        f"{public['total_eligible']} · candidates: {len(public['candidates'])}"
        f" · missing: {len(public['missing'])} · ambiguous: {len(public['ambiguous'])}"
        f" · invalid: {len(public['invalid'])} · remaining: {public['remaining']}"
    )
    click.echo(f"  updated: {public['updated']}")
    if public["backup"] is not None:
        click.echo(
            f"  backup: {public['backup'].get('path')}"
            f" · integrity: {public['backup'].get('integrity')}"
        )
    for conflict in public["conflicts"]:
        if isinstance(conflict, str):
            click.echo(f"  conflict: {conflict}")
        else:
            click.echo(
                f"  conflict: {conflict.get('id', '')}"
                f" · reason: {conflict.get('reason', '')}"
            )
    for item in public["candidates"]:
        click.echo(
            f"  candidate: {item.get('id')} · {item.get('scheduled_at')}"
            f" · {item.get('summary')} · target: {item.get('target_list')}"
            f" · match_type: {item.get('match_type')}"
        )
    for item in public["missing"]:
        click.echo(
            f"  missing: {item.get('id')} · {item.get('scheduled_at')}"
            f" · {item.get('summary')}"
        )
    for item in public["ambiguous"]:
        matched_lists = item.get("matched_lists") or []
        click.echo(
            f"  ambiguous: {item.get('id')} · {item.get('scheduled_at')}"
            f" · {item.get('summary')} · matches: {item.get('matches')}"
            f" · matched_lists: {', '.join(matched_lists)}"
        )
    for item in public["invalid"]:
        click.echo(
            f"  invalid: {item.get('id')} · {item.get('scheduled_at')}"
            f" · {item.get('summary')} · reason: {item.get('reason')}"
        )
    for error in public["errors"]:
        context = ""
        if error.get("list") or error.get("date"):
            context = f" · {error.get('list', '')} · {error.get('date', '')}"
        click.echo(
            f"  error: {error.get('code')} · {error.get('message')}{context}",
            err=True,
        )
