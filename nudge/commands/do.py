"""Original 'do' command — parse natural language into actions and execute."""

import json
import math
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

import click

from nudge.apple.adapters import (
    AppleBackends,
    UnsupportedAppleBackendError,
    resolve_apple_backends,
)
from nudge.action_hygiene import normalize_reminder_action
from nudge.apple.clock import DEFAULT_CREATE_ALARM_SHORTCUT
from nudge.brain import NudgeBrainError, parse_actions, suggest_family_routing
from nudge.config import (
    DEFAULT_CALENDAR_NAME,
    DEFAULT_NOTES_FOLDER,
    DEFAULT_REMINDER_LIST,
    FAMILY_GROUP_PERSON,
    get_defaults,
    get_family_aliases,
    get_family_members,
    get_family_routing,
    load_config,
)
from nudge.errors import (
    ErrorReport,
    apple_backend_error_report,
    classify_apple_error,
    classify_clock_error,
    classify_llm_error,
    cli_input_error_report,
    family_routing_invalid_report,
    format_llm_error,
    format_llm_schema_error,
    llm_schema_error_report,
)
from nudge.family_routing import resolve_family_recipients
from nudge.json_contract import (
    action_summary as _action_summary,
    error_to_json as _error_to_json,
    scheduled_at as _scheduled_at,
    versioned_payload,
)
from nudge.state import configure_state, log_action


_REQUIRED_FIELDS = {
    "calendar_event": ("summary", "start", "end"),
    "reminder": ("name", "due_date"),
    "alarm": ("time", "label"),
    "note": ("title", "body"),
}


def _resolve_target(action: dict, alias_map: dict, defaults: dict) -> tuple[str, str]:
    """Resolve calendar name and reminder list for an action."""
    person = action.get("person")
    cal = defaults.get("default_calendar", DEFAULT_CALENDAR_NAME)
    rlist = defaults.get("default_reminder_list", DEFAULT_REMINDER_LIST)
    if person == FAMILY_GROUP_PERSON:
        person = action.get("_family_group_alias")
    if person and person in alias_map:
        cal = alias_map[person].get("calendar", cal)
        rlist = alias_map[person].get("reminder_list", rlist)
    return cal, rlist


def format_action(action: dict, idx: int, alias_map: dict, defaults: dict) -> str:
    """Format an action for display."""
    t = action["type"]
    person = action.get("person")
    cal, rlist = _resolve_target(action, alias_map, defaults)
    lines = []

    if t == "calendar_event":
        lines.append(f'  {idx}. [CALENDAR] "{action["summary"]}"' + (f" for {person}" if person else ""))
        lines.append(f'     When: {action["start"]} - {action["end"]}')
        if action.get("location"):
            lines.append(f'     Where: {action["location"]}')
        lines.append(f"     Calendar: {cal}")

    elif t == "reminder":
        lines.append(f'  {idx}. [REMINDER] "{action["name"]}"' + (f" for {person}" if person else ""))
        lines.append(f'     Due: {action["due_date"]}')
        lines.append(f"     List: {rlist}")
        if action.get("remind_date"):
            lines.append(f'     Remind: {action["remind_date"]}')

    elif t == "alarm":
        lines.append(f'  {idx}. [ALARM] {action["time"]} - {action["label"]}')

    return "\n".join(lines)


def _parse_datetime(value: str, field_name: str) -> datetime:
    """Parse a datetime string from LLM output with error handling."""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except (ValueError, TypeError) as e:
        raise click.ClickException(f"Invalid {field_name} format '{value}': {e}")


def _action_schema_problems(actions: list[dict]) -> list[str]:
    """Return action schema problems without raising."""
    problems = []
    for index, action in enumerate(actions, 1):
        if not isinstance(action, dict):
            problems.append(f"action {index} is not an object")
            continue
        action_type = action.get("type")
        if action_type not in _REQUIRED_FIELDS:
            problems.append(f"action {index} has unsupported type: {action_type}")
            continue
        missing = [
            field
            for field in _REQUIRED_FIELDS[action_type]
            if action.get(field) in (None, "")
        ]
        if missing:
            problems.append(
                f"action {index} {action_type} missing fields: {', '.join(missing)}"
            )
            continue
        problems.extend(_action_value_problems(index, action))
    return problems


def _action_value_problems(index: int, action: dict) -> list[str]:
    """Return executable value problems for one already-shaped action."""
    action_type = action.get("type")
    problems = []
    if action_type == "calendar_event":
        start = _validate_action_datetime(action.get("start"), "start time", problems)
        end = _validate_action_datetime(action.get("end"), "end time", problems)
        if start and end and end <= start:
            problems.append("end time must be after start time")
    elif action_type == "reminder":
        _validate_action_datetime(action.get("due_date"), "due date", problems)
        if action.get("remind_date"):
            _validate_action_datetime(action.get("remind_date"), "remind date", problems)
    return [f"action {index} {problem}" for problem in problems]


def _validate_action_datetime(value: str | None, field_name: str, problems: list[str]) -> datetime | None:
    """Validate one action datetime and collect the existing user-facing message."""
    try:
        return _parse_datetime(value, field_name)
    except click.ClickException as exc:
        problems.append(exc.message)
        return None


def _validate_actions(actions: list[dict]) -> None:
    """Fail fast when LLM JSON is syntactically valid but not executable."""
    problems = _action_schema_problems(actions)
    if problems:
        raise click.ClickException(format_llm_schema_error("; ".join(problems)))


def _rewrite_family_group_actions(
    actions: list[dict],
    family_members: list[dict],
    alias_map: dict,
    routing: dict | None = None,
    llm_router=None,
) -> list[dict]:
    """Rewrite family-group actions into per-member reminders."""
    expanded = []
    routable_family_members = _family_members_with_routing_keys(family_members)
    display = _family_routing_display(routing)
    for action in actions:
        person = action.get("person")
        target = alias_map.get(person or "")
        if not _is_family_group_action(person, target, family_members):
            expanded.append(action)
            continue

        route = resolve_family_recipients(
            action,
            routable_family_members,
            routing,
            llm_router=llm_router,
        )
        if not route.members:
            routed_action = deepcopy(action)
            routed_action["_family_group_alias"] = person
            routed_action["_family_routing"] = deepcopy(route.metadata)
            expanded.append(routed_action)
            continue

        if action.get("type") == "calendar_event":
            expanded.extend(_family_group_event_reminders(action, route.members, route.metadata, display))
            continue

        if action.get("type") != "reminder":
            routed_action = deepcopy(action)
            routed_action["_family_group_alias"] = person
            routed_action["_family_routing"] = deepcopy(route.metadata)
            expanded.append(routed_action)
            continue

        for member in route.members:
            member_action = deepcopy(action)
            member_name = member["name"]
            member_action["person"] = member_name
            member_action["_family_group_alias"] = person
            member_action["_family_routing"] = deepcopy(route.metadata)
            member_action["name"] = _member_scoped_reminder_name(
                action["name"],
                member_name,
                display,
            )
            member_body = _member_scoped_reminder_body(
                action.get("body"),
                member_name,
                display,
            )
            if member_body is not None:
                member_action["body"] = member_body
            elif "body" in member_action:
                member_action.pop("body", None)
            expanded.append(member_action)
    return expanded


def _is_family_group_action(person: object, target: dict | None, family_members: list[dict]) -> bool:
    """Return whether an action should be routed as a family group."""
    if (target or {}).get("family_group"):
        return True
    return person == FAMILY_GROUP_PERSON and bool(family_members)


def _family_members_with_routing_keys(family_members: list[dict]) -> list[dict]:
    """Return members with stable keys so default routing stays compatible with old tests."""
    routable = []
    for member in family_members:
        if member.get("key"):
            routable.append(member)
            continue
        copied = dict(member)
        copied["key"] = str(member.get("name") or member.get("display_name") or len(routable))
        routable.append(copied)
    return routable


def _family_group_event_reminders(
    action: dict,
    family_members: list[dict],
    routing_metadata: dict,
    display: dict,
) -> list[dict]:
    start = _parse_datetime(action["start"], "start time")
    reminder_times = [
        (start - timedelta(minutes=30), "30 分钟后开始"),
        (start, "现在开始"),
    ]
    body = _family_event_body(action)
    reminders = []
    for member in family_members:
        member_name = member["name"]
        for due, suffix in reminder_times:
            reminders.append({
                "type": "reminder",
                "name": _member_scoped_reminder_name(
                    f'{action["summary"]}（{suffix}）',
                    member_name,
                    display,
                ),
                "due_date": due.strftime("%Y-%m-%d %H:%M"),
                "person": member_name,
                "body": _member_scoped_reminder_body(body, member_name, display),
                "priority": action.get("priority", 0),
                "remind_date": due.strftime("%Y-%m-%d %H:%M"),
                "_family_group_alias": action.get("person"),
                "_family_routing": deepcopy(routing_metadata),
            })
    return reminders


def _family_event_body(action: dict) -> str:
    lines = [
        f'家庭组事件：{action["summary"]}',
        f'开始：{action["start"]}',
        f'结束：{action["end"]}',
    ]
    if action.get("location"):
        lines.append(f'地点：{action["location"]}')
    if action.get("notes"):
        lines.append(str(action["notes"]))
    return "\n".join(lines)


def _family_routing_display(routing: dict | None) -> dict:
    display = (routing or {}).get("display", {})
    if not isinstance(display, dict):
        display = {}
    return {
        "title_prefix": bool(display.get("title_prefix", True)),
        "body_assignee_note": bool(display.get("body_assignee_note", False)),
    }


def _member_scoped_reminder_name(name: str, member_name: str, display: dict | None = None) -> str:
    display = _family_routing_display({"display": display or {}})
    if not display["title_prefix"]:
        return name
    if name.startswith(f"{member_name}："):
        return name
    return f"{member_name}：{name}"


def _member_scoped_reminder_body(body: object, member_name: str, display: dict | None = None) -> str | None:
    display = _family_routing_display({"display": display or {}})
    if not display["body_assignee_note"]:
        return body if body is None else str(body)

    assignee_line = f"负责人：{member_name}"
    if body is None or str(body).strip() == "":
        return assignee_line
    text = str(body)
    if assignee_line in text.splitlines():
        return text
    return f"{text}\n{assignee_line}"


def _json_target(
    action: dict,
    alias_map: dict,
    defaults: dict,
    apple_backends: AppleBackends | None = None,
) -> dict:
    """Return a stable target object for JSON mode."""
    action_type = action.get("type")
    cal, rlist = _resolve_target(action, alias_map, defaults)
    if action_type == "calendar_event":
        return {"kind": "Calendar", "name": cal}
    if action_type == "reminder":
        return {"kind": "Reminder list", "name": rlist}
    if action_type == "alarm":
        shortcut_name = (
            apple_backends.clock.shortcut_name
            if apple_backends is not None
            else DEFAULT_CREATE_ALARM_SHORTCUT
        )
        return {"kind": "Clock alarm", "name": shortcut_name}
    if action_type == "note":
        return {"kind": "Notes folder", "name": defaults.get("default_notes_folder", DEFAULT_NOTES_FOLDER)}
    return {"kind": "Unknown", "name": ""}


def _routing_value_to_string(value: object) -> str:
    """Return a stable string representation for routing metadata values."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _routing_optional_string(value: object) -> str | None:
    """Return a string for present routing metadata, preserving null."""
    if value is None:
        return None
    return _routing_value_to_string(value)


def _routing_string_list(value: object) -> list[str]:
    """Return a stable list[str] for routing metadata list fields."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]
    return [_routing_value_to_string(item) for item in values]


def _routing_confidence(value: object) -> int | float | str:
    """Return JSON-safe confidence while keeping finite numbers numeric."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if math.isfinite(number):
            return value
        return str(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _routing_value_to_string(value)
    if math.isfinite(number):
        return number
    return _routing_value_to_string(value)


def _routing_to_json(metadata: object) -> dict | None:
    """Serialize family routing metadata using the public JSON contract."""
    if not isinstance(metadata, dict):
        return None

    routing = {
        "source": _routing_value_to_string(metadata.get("source") or ""),
        "rule_id": _routing_optional_string(metadata.get("rule_id")),
        "original_person": _routing_optional_string(metadata.get("original_person")),
        "assignees": _routing_string_list(metadata.get("assignees")),
        "reason": _routing_optional_string(metadata.get("reason")),
    }

    for key in ("invalid_assignees", "empty_assignees"):
        if key in metadata:
            routing[key] = _routing_string_list(metadata.get(key))
    for key in ("assignee_error", "llm_error"):
        if key in metadata:
            routing[key] = _routing_value_to_string(metadata.get(key))
    for key in ("confidence", "llm_confidence"):
        if key in metadata:
            routing[key] = _routing_confidence(metadata.get(key))

    return routing


def _action_to_json(
    action: dict,
    index: int,
    alias_map: dict,
    defaults: dict,
    status: str,
    apple_backends: AppleBackends | None = None,
) -> dict:
    """Serialize one action for the stable JSON contract."""
    item = {
        "index": index,
        "type": action.get("type"),
        "status": status,
        "summary": _action_summary(action),
        "scheduled_at": _scheduled_at(action),
        "target": _json_target(action, alias_map, defaults, apple_backends),
    }
    if action.get("person") is not None:
        item["person"] = action.get("person")
    if action.get("_external_id"):
        item["external_id"] = action["_external_id"]
    routing = _routing_to_json(action.get("_family_routing"))
    if routing is not None:
        item["routing"] = routing
    if action.get("_error"):
        item["error_code"] = action["_error"].code
        item["error"] = action["_error"].title
    return item


def _failure_to_json(action: dict, index: int) -> dict:
    """Serialize a failed action without duplicating the full action payload."""
    error = action.get("_error")
    return {
        "index": index,
        "summary": _action_summary(action) or "<unknown>",
        "error_code": error.code if error else "ACTION_FAILED",
        "error": error.title if error else "Action failed",
    }


def _json_payload(
    actions: list[dict],
    alias_map: dict,
    defaults: dict,
    dry_run: bool,
    success: int,
    failed_indices: list[int],
    errors: list[ErrorReport],
    apple_backends: AppleBackends | None = None,
) -> dict:
    """Build the stable JSON response for external callers."""
    failed = set(failed_indices)
    serialized_actions = []
    for index, action in enumerate(actions, 1):
        if dry_run:
            status = "dry_run"
        elif index in failed:
            status = "failed"
        else:
            status = "succeeded"
        serialized_actions.append(
            _action_to_json(action, index, alias_map, defaults, status, apple_backends)
        )

    return versioned_payload({
        "ok": not errors and not failed_indices,
        "dry_run": dry_run,
        "total": len(actions),
        "succeeded": success,
        "actions": serialized_actions,
        "failures": [
            _failure_to_json(actions[index - 1], index)
            for index in failed_indices
        ],
        "errors": [_error_to_json(error) for error in errors],
    })


def _emit_json(payload: dict) -> None:
    """Write JSON to stdout as the only machine-readable output."""
    click.echo(json.dumps(payload, ensure_ascii=False))


def _emit_json_error(error: ErrorReport, dry_run: bool = False) -> None:
    """Emit a parse/validation error using the stable JSON shape."""
    _emit_json(versioned_payload({
        "ok": False,
        "dry_run": dry_run,
        "total": 0,
        "succeeded": 0,
        "actions": [],
        "failures": [],
        "errors": [_error_to_json(error)],
    }))


def _invalid_family_routing_error(action: dict) -> ErrorReport | None:
    """Return a blocking error when family routing metadata is not executable."""
    metadata = action.get("_family_routing")
    if not isinstance(metadata, dict):
        return None

    source = str(metadata.get("source") or "")
    preserved_family_target = bool(action.get("_family_group_alias"))
    no_route_members = preserved_family_target and metadata.get("assignees") == []
    if source in {"keyword_invalid", "default_invalid"} or no_route_members:
        return family_routing_invalid_report(_action_summary(action), metadata)
    return None


def execute_action(
    action: dict,
    alias_map: dict,
    defaults: dict,
    quiet: bool = False,
    apple_backends: AppleBackends | None = None,
) -> bool:
    """Execute a single action. Returns True on success."""
    routing_error = _invalid_family_routing_error(action)
    if routing_error is not None:
        action["_error"] = routing_error
        if not quiet:
            click.echo(routing_error.render(indent="     "), err=True)
        return False

    if apple_backends is None:
        apple_backends = resolve_apple_backends({})

    try:
        t = action["type"]
        cal, rlist = _resolve_target(action, alias_map, defaults)

        if t == "calendar_event":
            start = _parse_datetime(action["start"], "start time")
            end = _parse_datetime(action["end"], "end time")
            result = apple_backends.calendar.create_event(
                summary=action["summary"],
                start=start,
                end=end,
                calendar_name=cal,
                location=action.get("location"),
                notes=action.get("notes"),
            )
            if not result.ok:
                error = classify_apple_error("Calendar", "Calendar", cal, result.message)
                action["_error"] = error
                if not quiet:
                    click.echo(error.render(indent="     "), err=True)
            else:
                action["_external_id"] = result.external_id
            return result.ok

        elif t == "reminder":
            due = _parse_datetime(action["due_date"], "due date")
            remind = None
            if action.get("remind_date"):
                remind = _parse_datetime(action["remind_date"], "remind date")
            action["_reminder_list"] = rlist
            result = apple_backends.reminders.create_reminder(
                name=action["name"],
                due_date=due,
                list_name=rlist,
                body=action.get("body"),
                priority=action.get("priority", 0),
                remind_date=remind,
            )
            if not result.ok:
                error = classify_apple_error("Reminders", "Reminder list", rlist, result.message)
                action["_error"] = error
                if not quiet:
                    click.echo(error.render(indent="     "), err=True)
            elif result.external_id:
                action["_external_id"] = result.external_id
            return result.ok

        elif t == "alarm":
            result = apple_backends.clock.create_alarm(time=action["time"], label=action["label"])
            if not result.ok:
                error = classify_clock_error(
                    result.message,
                    shortcut_name=apple_backends.clock.shortcut_name,
                )
                action["_error"] = error
                if not quiet:
                    click.echo(error.render(indent="     "), err=True)
            else:
                action["_external_id"] = result.external_id
            return result.ok

        elif t == "note":
            folder_name = defaults.get("default_notes_folder", DEFAULT_NOTES_FOLDER)
            result = apple_backends.notes.create_note(
                title=action["title"],
                body=action["body"],
                folder_name=folder_name,
            )
            if not result.ok:
                error = classify_apple_error("Notes", "Notes folder", folder_name, result.message)
                action["_error"] = error
                if not quiet:
                    click.echo(error.render(indent="     "), err=True)
            elif result.external_id:
                action["_external_id"] = result.external_id
            return result.ok
    except click.ClickException as exc:
        error = llm_schema_error_report(exc.message)
        action["_error"] = error
        if not quiet:
            click.echo(error.render(indent="     "), err=True)
        return False

    return False


@click.command("do")
@click.argument("message", required=False)
@click.option("--file", "-f", "file_path", help="Read message from file")
@click.option("--dry-run", "-n", is_flag=True, help="Preview without creating")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON for scripts")
def do_command(message, file_path, dry_run, config_path, json_output):
    """Parse a message and create calendar events / reminders."""
    # Get input text
    try:
        if file_path:
            text = Path(file_path).read_text()
        elif message:
            text = message
        elif not sys.stdin.isatty():
            text = sys.stdin.read()
        else:
            if json_output:
                _emit_json_error(
                    cli_input_error_report("Provide a message, --file, or pipe input"),
                    dry_run=dry_run,
                )
                raise click.exceptions.Exit(1)
            click.echo("Error: Provide a message, --file, or pipe input", err=True)
            sys.exit(1)
    except OSError as exc:
        if json_output:
            _emit_json_error(cli_input_error_report(str(exc)), dry_run=dry_run)
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))

    try:
        config = load_config(config_path)
    except Exception as exc:
        if json_output:
            _emit_json_error(cli_input_error_report(str(exc)), dry_run=dry_run)
            raise click.exceptions.Exit(1)
        raise
    if config_path:
        configure_state(config)
    defaults = get_defaults(config)
    all_aliases, alias_map = get_family_aliases(config)
    family_members = get_family_members(config)
    routing = get_family_routing(config)
    try:
        apple_backends = resolve_apple_backends(config)
    except UnsupportedAppleBackendError as e:
        error = apple_backend_error_report(str(e))
        if json_output:
            _emit_json_error(error, dry_run=dry_run)
            raise click.exceptions.Exit(1)
        raise click.ClickException(error.render())

    if not json_output:
        click.echo(f"Parsing: {text[:80]}{'...' if len(text) > 80 else ''}\n")
    try:
        actions = parse_actions(text, all_aliases)
    except NudgeBrainError as e:
        if json_output:
            _emit_json_error(classify_llm_error(str(e)), dry_run=dry_run)
            raise click.exceptions.Exit(1)
        raise click.ClickException(format_llm_error(str(e)))
    problems = _action_schema_problems(actions)
    if problems:
        message = "; ".join(problems)
        if json_output:
            _emit_json_error(llm_schema_error_report(message), dry_run=dry_run)
            raise click.exceptions.Exit(1)
        raise click.ClickException(format_llm_schema_error(message))
    actions = [normalize_reminder_action(action) for action in actions]
    llm_router = suggest_family_routing if routing.get("llm_fallback") else None
    actions = _rewrite_family_group_actions(
        actions,
        family_members,
        alias_map,
        routing,
        llm_router=llm_router,
    )

    if not json_output:
        click.echo(f"Found {len(actions)} action(s):\n")

        for i, action in enumerate(actions, 1):
            click.echo(format_action(action, i, alias_map, defaults))
        click.echo()

    if dry_run:
        if json_output:
            _emit_json(_json_payload(
                actions=actions,
                alias_map=alias_map,
                defaults=defaults,
                dry_run=True,
                success=0,
                failed_indices=[],
                errors=[],
                apple_backends=apple_backends,
            ))
        else:
            click.echo("(dry-run, nothing created)")
        return

    success = 0
    failed_indices = []
    for index, action in enumerate(actions, 1):
        if execute_action(
            action,
            alias_map,
            defaults,
            quiet=json_output,
            apple_backends=apple_backends,
        ):
            success += 1
            # Log to SQLite for tracking
            log_action(
                action_type=action["type"],
                summary=_action_summary(action),
                scheduled_at=_scheduled_at(action),
                external_id=action.get("_external_id"),
                reminder_list=action.get("_reminder_list"),
            )
        else:
            failed_indices.append(index)

    errors = [
        actions[index - 1]["_error"]
        for index in failed_indices
        if actions[index - 1].get("_error")
    ]
    if json_output:
        _emit_json(_json_payload(
            actions=actions,
            alias_map=alias_map,
            defaults=defaults,
            dry_run=False,
            success=success,
            failed_indices=failed_indices,
            errors=errors,
            apple_backends=apple_backends,
        ))
        if failed_indices:
            raise click.exceptions.Exit(1)
        return

    click.echo(f"Done. ({success}/{len(actions)} succeeded)")
    if failed_indices:
        click.echo("", err=True)
        click.echo("部分 action 写入失败。已成功的 action 可能已经创建并写入本地记录。", err=True)
        click.echo("不要直接整条重试；请只处理失败项，避免重复创建已成功项。", err=True)
        for index in failed_indices:
            summary = _action_summary(actions[index - 1]) or "<unknown>"
            click.echo(f"- 失败项：{summary}", err=True)
        raise click.exceptions.Exit(1)
