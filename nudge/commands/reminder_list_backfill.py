"""CLI orchestration for legacy Reminder list ownership backfill."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import tomllib
import unicodedata
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
    ReminderListBackfillConflictError,
    apply_reminder_list_backfill,
    configure_state,
    get_actions_readonly,
)


CONFIRMATION_INVALID = "REMINDER_LIST_BACKFILL_CONFIRMATION_INVALID"
CONFIRMATION_REQUIRED = "REMINDER_LIST_BACKFILL_CONFIRMATION_REQUIRED"
CANCELLED = "REMINDER_LIST_BACKFILL_CANCELLED"
BACKUP_FAILED = "REMINDER_LIST_BACKFILL_BACKUP_FAILED"
CONFLICT = "REMINDER_LIST_BACKFILL_CONFLICT"
RANGE_INVALID = "REMINDER_LIST_BACKFILL_RANGE_INVALID"
CONFIG_INVALID = "REMINDER_LIST_BACKFILL_CONFIG_INVALID"
QUERY_FAILED = "REMINDER_LIST_BACKFILL_QUERY_FAILED"
WRITE_FAILED = "REMINDER_LIST_BACKFILL_WRITE_FAILED"
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_TEXT_LIMIT = 500


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
        _validate_config(config)
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
        actions = get_actions_readonly()
    except (FileNotFoundError, sqlite3.Error, OSError):
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
    batch = select_list_backfill_actions(
        actions,
        date_from=date_from,
        date_to=date_to,
        limit=parsed_limit,
    )

    query_dates = tuple(dict.fromkeys(batch.query_dates))
    plan, errors = _query_and_plan(batch.actions, query_dates, reminder_lists)
    snapshots = {
        action["id"]: dict(action)
        for action in batch.actions
        if isinstance(action.get("id"), str)
    }
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
    if not payload["ok"]:
        _finish(payload, json_output)
    if not apply_changes or not payload["candidates"]:
        _emit(payload, json_output)
        return

    if not yes:
        if json_output or not _is_interactive_terminal():
            _finish(
                _with_error(
                    payload,
                    code=CONFIRMATION_REQUIRED,
                    message="Re-run with --yes after reviewing the final candidates.",
                ),
                json_output,
            )
        _emit(payload, json_output=False)
        try:
            confirmed = click.confirm(
                "确认仅回填以上 Nudge SQLite reminder_list？",
                default=False,
            )
        except click.Abort:
            confirmed = False
        if not confirmed:
            _finish(
                _with_error(
                    payload,
                    code=CANCELLED,
                    message="Reminder list backfill was cancelled.",
                ),
                json_output=False,
            )

    revalidated_plan, revalidation_errors = _query_and_plan(
        batch.actions,
        query_dates,
        reminder_lists,
    )
    if revalidation_errors:
        failed = dict(payload)
        failed["ok"] = False
        failed["apply_allowed"] = False
        failed["updated"] = 0
        failed["errors"] = revalidation_errors
        _finish(failed, json_output)
    if _plan_fingerprint(revalidated_plan) != _plan_fingerprint(plan):
        failed = _with_error(
            payload,
            code=CONFLICT,
            message="Reminder data changed after planning; re-run to review current candidates.",
        )
        failed["conflicts"] = sorted({
            item["id"]
            for current_plan in (plan, revalidated_plan)
            for category in ("candidates", "missing", "ambiguous")
            for item in current_plan.get(category, [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        })
        _finish(failed, json_output)

    try:
        backup_path = backup_database(initialize=False)
    except Exception:
        _finish(
            _with_error(
                payload,
                code=BACKUP_FAILED,
                message="Unable to create a verified Nudge database backup.",
            ),
            json_output,
        )

    payload = dict(payload)
    payload["backup"] = {"path": str(backup_path), "integrity": "ok"}
    updates = [
        {"id": candidate["id"], "target_list": candidate["target_list"]}
        for candidate in payload["candidates"]
    ]
    try:
        applied = apply_reminder_list_backfill(updates, snapshots=snapshots)
        requested_ids = [update["id"] for update in updates]
        if (
            not isinstance(applied, list)
            or any(not isinstance(action_id, str) for action_id in applied)
            or len(applied) != len(requested_ids)
            or len(set(applied)) != len(applied)
            or set(applied) != set(requested_ids)
        ):
            raise ValueError("applied reminder list backfill IDs do not match request")
    except ReminderListBackfillConflictError as exc:
        failed = _with_error(
            payload,
            code=CONFLICT,
            message="Reminder list backfill conflicts with current Nudge state.",
        )
        failed["conflicts"] = list(exc.action_ids)
        _finish(failed, json_output)
    except Exception:
        _finish(
            _with_error(
                payload,
                code=WRITE_FAILED,
                message="Unable to update Nudge reminder list ownership.",
            ),
            json_output,
        )

    payload["updated"] = len(applied)
    _emit(payload, json_output)


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


def _validate_config(config: object) -> None:
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    for section in ("reminders", "general", "state"):
        if section in config and not isinstance(config[section], dict):
            raise ValueError(f"[{section}] must be a table")


def _valid_query_row(row: object, list_name: str, target_date: date) -> bool:
    if not isinstance(row, dict) or row.get("list") != list_name:
        return False
    name = row.get("name")
    if not isinstance(name, str) or not name.strip():
        return False
    due_at = parse_strict_minute(row.get("due_at"))
    due_time = row.get("due_time")
    if due_at is None or due_at.date() != target_date:
        return False
    if not isinstance(due_time, str) or len(due_time) != 5:
        return False
    return due_time == due_at.strftime("%H:%M")


def _query_and_plan(
    actions: list[dict],
    query_dates: tuple[date, ...],
    reminder_lists: list[str],
) -> tuple[dict, list[dict]]:
    """Query the fixed Apple scope and produce a deterministic safe plan."""
    apple_rows: list[dict] = []
    errors: list[dict] = []
    row_number = 0
    for list_name in reminder_lists:
        for target_date in query_dates:
            try:
                ok, rows = query_all_due_on_date(list_name, target_date)
            except Exception:
                ok, rows = False, []

            query_invalid = not ok or not isinstance(rows, list)
            if isinstance(rows, list):
                for row in rows:
                    current_number = row_number
                    row_number += 1
                    if not _valid_query_row(row, list_name, target_date):
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
                    "message": "Unable to query this Reminder list and date.",
                })
    return plan_list_backfill(actions, apple_rows), errors


def _plan_fingerprint(plan: dict) -> str:
    stable_plan = {
        category: plan.get(category, [])
        for category in ("candidates", "missing", "ambiguous")
    }
    return json.dumps(
        stable_plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


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


def _with_error(payload: dict, *, code: str, message: str) -> dict:
    """Return a failed copy containing only the approved public error fields."""
    failed = dict(payload)
    failed["ok"] = False
    failed["apply_allowed"] = False
    failed["updated"] = 0
    failed["errors"] = [*payload.get("errors", []), {"code": code, "message": message}]
    return failed


def _is_interactive_terminal() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


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

    public = {
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
    return _sanitize_public_strings(public)


def _sanitize_public_strings(value):
    if isinstance(value, str):
        return _safe_json_text(value)
    if isinstance(value, list):
        return [_sanitize_public_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_public_strings(item) for key, item in value.items()}
    return value


def _safe_json_text(value: str) -> str:
    text = _OSC_RE.sub("", value)
    text = _ANSI_RE.sub("", text)
    return "".join(
        character
        for character in text
        if not unicodedata.category(character).startswith("C")
    )


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
    click.echo(
        f"{status} Reminder list backfill · "
        f"{', '.join(_safe_text(item) for item in public['lists'])}"
    )
    click.echo(
        "  eligible: "
        f"{_safe_text(public['total_eligible'])} · candidates: {len(public['candidates'])}"
        f" · missing: {len(public['missing'])} · ambiguous: {len(public['ambiguous'])}"
        f" · invalid: {len(public['invalid'])} · remaining: {_safe_text(public['remaining'])}"
    )
    click.echo(f"  updated: {_safe_text(public['updated'])}")
    if public["backup"] is not None:
        click.echo(
            f"  backup: {_safe_text(public['backup'].get('path'))}"
            f" · integrity: {_safe_text(public['backup'].get('integrity'))}"
        )
    for conflict in public["conflicts"]:
        if isinstance(conflict, str):
            click.echo(f"  conflict: {_safe_text(conflict)}")
        else:
            click.echo(
                f"  conflict: {_safe_text(conflict.get('id', ''))}"
                f" · reason: {_safe_text(conflict.get('reason', ''))}"
            )
    for item in public["candidates"]:
        click.echo(
            f"  candidate: {_safe_text(item.get('id'))}"
            f" · {_safe_text(item.get('scheduled_at'))}"
            f" · {_safe_text(item.get('summary'))}"
            f" · target: {_safe_text(item.get('target_list'))}"
            f" · match_type: {_safe_text(item.get('match_type'))}"
        )
    for item in public["missing"]:
        click.echo(
            f"  missing: {_safe_text(item.get('id'))}"
            f" · {_safe_text(item.get('scheduled_at'))}"
            f" · {_safe_text(item.get('summary'))}"
        )
    for item in public["ambiguous"]:
        matched_lists = item.get("matched_lists") or []
        click.echo(
            f"  ambiguous: {_safe_text(item.get('id'))}"
            f" · {_safe_text(item.get('scheduled_at'))}"
            f" · {_safe_text(item.get('summary'))}"
            f" · matches: {_safe_text(item.get('matches'))}"
            f" · matched_lists: {', '.join(_safe_text(value) for value in matched_lists)}"
        )
    for item in public["invalid"]:
        click.echo(
            f"  invalid: {_safe_text(item.get('id'))}"
            f" · {_safe_text(item.get('scheduled_at'))}"
            f" · {_safe_text(item.get('summary'))}"
            f" · reason: {_safe_text(item.get('reason'))}"
        )
    for error in public["errors"]:
        context = ""
        if error.get("list") or error.get("date"):
            context = (
                f" · {_safe_text(error.get('list', ''))}"
                f" · {_safe_text(error.get('date', ''))}"
            )
        click.echo(
            f"  error: {_safe_text(error.get('code'))}"
            f" · {_safe_text(error.get('message'))}{context}",
            err=True,
        )


def _safe_text(value: object) -> str:
    """Make one bounded terminal-safe line from an untrusted display value."""
    text = "" if value is None else str(value)
    text = _OSC_RE.sub("", text)
    text = _ANSI_RE.sub("", text)
    text = "".join(
        " " if unicodedata.category(character).startswith("C") else character
        for character in text
    )
    text = " ".join(text.split())
    if len(text) > _TEXT_LIMIT:
        return f"{text[:_TEXT_LIMIT - 1]}…"
    return text
