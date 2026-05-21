"""Agent-facing Apple action relay command.

This command is intentionally lower-level than `nudge do`: callers provide
structured actions, Nudge handles adapter selection, macOS app writes, tracking,
and stable JSON results. Future MCP tools should wrap this engine instead of
calling AppleScript/EventKit directly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sys
from pathlib import Path

import click

from nudge.action_hygiene import normalize_reminder_title
from nudge.apple.adapters import UnsupportedAppleBackendError, resolve_apple_backends
from nudge.commands.do import _action_schema_problems, execute_action
from nudge.config import DEFAULT_CALENDAR_NAME, DEFAULT_REMINDER_LIST, get_defaults, load_config
from nudge.errors import (
    ErrorReport,
    agent_action_not_found_report,
    agent_batch_too_large_report,
    agent_confirmation_invalid_report,
    agent_confirmation_required_report,
    agent_request_error_report,
    agent_status_request_error_report,
    agent_text_plan_confirmation_required_report,
    apple_backend_error_report,
)
from nudge.feedback import STATUS_ALLOWED, STATUS_NEXT_ACTIONS, STATUS_REASONS, build_feedback
from nudge.json_contract import versioned_payload
from nudge.state import (
    STATE_DIR,
    complete_action,
    configure_state,
    get_action,
    log_action,
    partial_action,
    skip_action,
    update_action_status,
)


SUPPORTED_AGENT_ACTIONS = {
    "calendar_event.create": ("summary", "start", "end"),
    "reminder.create": ("name", "due_date"),
    "alarm.create": ("time", "label"),
    "note.create": ("title", "body"),
}
MAX_AGENT_ACTIONS = 10
CONFIRMATION_TOKEN_VERSION = "nudge.agent.confirm.v1"
CONFIRMATION_SECRET_PATH = STATE_DIR / "agent_confirm_secret"


@click.group("agent")
def agent_command():
    """Agent relay APIs for applying structured Apple actions."""
    pass


@agent_command.command("apply")
@click.option("--file", "-f", "file_path", default=None, help="Read agent request JSON from file")
@click.option("--dry-run", "-n", is_flag=True, help="Preview without creating Apple app items")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON for scripts")
def apply_command(file_path, dry_run, config_path, json_output):
    """Apply structured Apple actions from another local agent.

    Output is always JSON; `--json` is accepted to make script usage explicit.
    """
    del json_output  # Agent apply is machine-facing and always emits JSON.

    try:
        raw_request = _read_request_text(file_path)
    except OSError as e:
        _emit_agent_error(
            request_id=None,
            source=None,
            dry_run=dry_run,
            error=agent_request_error_report(f"cannot read request JSON: {e}"),
        )
        raise click.exceptions.Exit(1)
    try:
        request = json.loads(raw_request)
    except json.JSONDecodeError as e:
        _emit_agent_error(
            request_id=None,
            source=None,
            dry_run=dry_run,
            error=agent_request_error_report(f"invalid JSON: {e}"),
        )
        raise click.exceptions.Exit(1)

    request_id = request.get("request_id") if isinstance(request, dict) else None
    source = request.get("source") if isinstance(request, dict) else None
    try:
        config = load_config(config_path)
    except Exception as e:
        _emit_agent_error(
            request_id=request_id,
            source=source,
            dry_run=dry_run,
            error=agent_request_error_report(f"cannot load config: {e}"),
        )
        raise click.exceptions.Exit(1)
    if config_path:
        _configure_agent_state(config)
    payload, exit_code = apply_agent_request(
        request=request,
        config=config,
        dry_run_override=dry_run,
    )
    click.echo(json.dumps(payload, ensure_ascii=False))
    if exit_code:
        raise click.exceptions.Exit(exit_code)


def _configure_agent_state(config: dict) -> None:
    """Point agent state and confirmation token storage at a loaded config."""
    global STATE_DIR, CONFIRMATION_SECRET_PATH

    STATE_DIR = configure_state(config)
    CONFIRMATION_SECRET_PATH = STATE_DIR / "agent_confirm_secret"


@agent_command.command("status")
@click.option("--file", "-f", "request_file", default=None, help="Read status JSON from file")
@click.option("--dry-run", "-n", is_flag=True, help="Preview only, do not write SQLite")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON for scripts")
def status_command(request_file, dry_run, json_output):
    """Update local action status from another local agent or automation tool."""
    del json_output  # agent status always emits JSON.

    try:
        raw_request = _read_request_text(request_file)
    except OSError as e:
        _emit_agent_error(
            request_id=None,
            source="agent.status",
            dry_run=dry_run,
            error=agent_status_request_error_report(f"cannot read status JSON: {e}"),
        )
        raise click.exceptions.Exit(1)

    try:
        request = json.loads(raw_request)
    except json.JSONDecodeError as e:
        _emit_agent_error(
            request_id=None,
            source="agent.status",
            dry_run=dry_run,
            error=agent_status_request_error_report(f"invalid JSON: {e}"),
        )
        raise click.exceptions.Exit(1)

    payload, exit_code = apply_action_status(
        request=request,
        dry_run_override=dry_run,
    )
    click.echo(json.dumps(payload, ensure_ascii=False))
    if exit_code:
        raise click.exceptions.Exit(exit_code)


class _NormalizedRequest:
    """Internal normalized request representation."""

    def __init__(
        self,
        *,
        request_id: str | None,
        source: str | None,
        dry_run: bool,
        require_confirmation: bool,
        dry_run_token: str | None,
        plan_driven: bool,
        text_plan_confirmed: bool,
        text_plan_ref: str | None,
        actions: list[dict],
    ):
        self.request_id = request_id
        self.source = source
        self.dry_run = dry_run
        self.require_confirmation = require_confirmation
        self.dry_run_token = dry_run_token
        self.plan_driven = plan_driven
        self.text_plan_confirmed = text_plan_confirmed
        self.text_plan_ref = text_plan_ref
        self.actions = actions


class AgentBatchTooLargeError(ValueError):
    """Raised when an agent request exceeds the safe batch limit."""

    def __init__(self, *, limit: int, received: int):
        self.limit = limit
        self.received = received
        super().__init__(f"agent request contains {received} actions; limit is {limit}")


class _NormalizedStatus:
    """Internal normalized status update representation."""

    def __init__(
        self,
        *,
        action_id: str,
        status: str,
        source: str | None,
        note: str | None,
        reason: str | None,
        next_action: str | None,
        raw_feedback: dict | None,
    ):
        self.action_id = action_id
        self.status = status
        self.source = source
        self.note = note
        self.reason = reason
        self.next_action = next_action
        self.raw_feedback = raw_feedback


def apply_agent_request(
    *,
    request: object,
    config: dict,
    dry_run_override: bool = False,
) -> tuple[dict, int]:
    """Apply one structured agent request and return a JSON payload plus exit code.

    This is the shared engine used by both `nudge agent apply` and the MCP
    wrapper. It never writes to stdout/stderr and is therefore safe to call from
    stdio JSON-RPC transports.
    """
    request_id = request.get("request_id") if isinstance(request, dict) else None
    source = request.get("source") if isinstance(request, dict) else None
    try:
        apple_backends = resolve_apple_backends(config)
        normalized = _normalize_request(request, config)
    except UnsupportedAppleBackendError as e:
        return _agent_error_payload(
            request_id=request_id,
            source=source,
            dry_run=dry_run_override,
            error=apple_backend_error_report(str(e)),
        ), 1
    except AgentBatchTooLargeError as e:
        return _agent_error_payload(
            request_id=request_id,
            source=source,
            dry_run=dry_run_override,
            error=agent_batch_too_large_report(limit=e.limit, received=e.received),
        ), 1
    except ValueError as e:
        return _agent_error_payload(
            request_id=request_id,
            source=source,
            dry_run=dry_run_override,
            error=agent_request_error_report(str(e)),
        ), 1

    return _apply_normalized_request(
        normalized=normalized,
        apple_backends=apple_backends,
        dry_run=dry_run_override or normalized.dry_run,
    )


def apply_action_status(
    *,
    request: object,
    dry_run_override: bool = False,
    feedback_channel: str = "agent.status",
    feedback_source_type: str = "agent",
) -> tuple[dict, int]:
    """Apply one structured action-status 回写 request and return payload + exit code."""
    source = request.get("source") if isinstance(request, dict) else None
    try:
        normalized = _normalize_status_request(request)
    except ValueError as e:
        return _agent_error_payload(
            request_id=None,
            source=source,
            dry_run=dry_run_override,
            error=agent_status_request_error_report(str(e)),
        ), 1

    previous = get_action(normalized.action_id)
    if previous is None:
        return _agent_error_payload(
            request_id=None,
            source=normalized.source or source,
            dry_run=dry_run_override,
            error=agent_action_not_found_report(normalized.action_id),
        ), 1

    payload = _action_status_payload(
        normalized=normalized,
        previous=previous,
        dry_run=dry_run_override,
        feedback_channel=feedback_channel,
        feedback_source_type=feedback_source_type,
    )
    if dry_run_override:
        return payload, 0

    feedback = _build_status_feedback(
        normalized,
        feedback_channel=feedback_channel,
        feedback_source_type=feedback_source_type,
    )
    if normalized.status == "done":
        complete_action(normalized.action_id, feedback=feedback)
    elif normalized.status == "skipped":
        skip_action(normalized.action_id, feedback=feedback)
    elif normalized.status == "partial":
        partial_action(normalized.action_id, feedback=feedback)
    else:
        update_action_status(normalized.action_id, normalized.status, feedback=feedback)

    updated = get_action(normalized.action_id)
    return _action_status_payload(
        normalized=normalized,
        previous=previous,
        dry_run=False,
        updated=updated,
        feedback_channel=feedback_channel,
        feedback_source_type=feedback_source_type,
    ), 0


def _read_request_text(file_path: str | None) -> str:
    """Read agent request JSON from a file or stdin."""
    if file_path:
        return Path(file_path).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    _emit_agent_error(
        request_id=None,
        source=None,
        dry_run=False,
        error=agent_request_error_report("missing request JSON; pass --file or pipe stdin"),
    )
    raise click.exceptions.Exit(1)


def _normalize_status_request(request: object) -> _NormalizedStatus:
    """Validate and normalize an action-status 回写 request."""
    if not isinstance(request, dict):
        raise ValueError("request must be a JSON object")

    action_id = _optional_string(request.get("action_id"))
    if not action_id:
        raise ValueError("request.action_id is required")

    status = _optional_string(request.get("status"))
    if not status:
        raise ValueError("request.status is required")
    status = status.lower().strip()
    if status not in STATUS_ALLOWED:
        raise ValueError(f"unsupported status: {status}")

    source = _optional_string(request.get("source"))
    note = _optional_string(request.get("note"))
    reason = _optional_choice(request.get("reason"), STATUS_REASONS, "reason")
    next_action = _optional_choice(request.get("next_action"), STATUS_NEXT_ACTIONS, "next_action")

    feedback = request.get("feedback", {})
    if not isinstance(feedback, dict):
        raise ValueError("request.feedback must be object if provided")

    return _NormalizedStatus(
        action_id=action_id,
        status=status,
        source=source,
        note=note,
        reason=reason,
        next_action=next_action,
        raw_feedback=feedback,
    )


def _build_status_feedback(
    status: _NormalizedStatus,
    *,
    feedback_channel: str = "agent.status",
    feedback_source_type: str = "agent",
) -> dict:
    return build_feedback(
        source=status.source,
        channel=feedback_channel,
        source_type=feedback_source_type,
        note=status.note,
        reason=status.reason,
        next_action=status.next_action,
        extra=status.raw_feedback,
    )


def _action_status_payload(
    normalized: _NormalizedStatus,
    previous: dict,
    dry_run: bool,
    updated: dict | None = None,
    feedback_channel: str = "agent.status",
    feedback_source_type: str = "agent",
) -> dict:
    action = {
        "id": normalized.action_id,
        "summary": previous.get("summary"),
        "status": normalized.status,
        "scheduled_at": previous.get("scheduled_at"),
        "type": previous.get("type"),
    }
    payload = versioned_payload({
        "ok": True,
        "request_id": None,
        "source": normalized.source,
        "dry_run": dry_run,
        "action": {
            "id": normalized.action_id,
            "summary": previous.get("summary"),
            "status": normalized.status,
            "previous_status": previous.get("status"),
            "scheduled_at": previous.get("scheduled_at"),
            "type": previous.get("type"),
        },
        "updated": action if updated else None,
        "feedback": _build_status_feedback(
            normalized,
            feedback_channel=feedback_channel,
            feedback_source_type=feedback_source_type,
        ),
        "errors": [],
    })
    return payload


def _optional_choice(value: object, allowed: set[str], field_name: str) -> str | None:
    if value is None or value == "":
        return None
    normalized = str(value).strip().lower()
    if normalized not in allowed:
        raise ValueError(f"unsupported {field_name}: {normalized}")
    return normalized


def _normalize_request(request: object, config: dict) -> _NormalizedRequest:
    """Validate and normalize an agent request."""
    if not isinstance(request, dict):
        raise ValueError("request must be a JSON object")

    actions = request.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("request.actions must be a non-empty list")
    if len(actions) > MAX_AGENT_ACTIONS:
        raise AgentBatchTooLargeError(limit=MAX_AGENT_ACTIONS, received=len(actions))

    defaults = get_defaults(config)
    normalized_actions = []
    problems = []
    for index, action in enumerate(actions, 1):
        if not isinstance(action, dict):
            problems.append(f"action {index} must be an object")
            continue
        action_type = action.get("type")
        if action_type not in SUPPORTED_AGENT_ACTIONS:
            problems.append(f"action {index} has unsupported type: {action_type}")
            continue
        missing = [
            field
            for field in SUPPORTED_AGENT_ACTIONS[action_type]
            if action.get(field) in (None, "")
        ]
        if missing:
            problems.append(
                f"action {index} {action_type} missing fields: {', '.join(missing)}"
            )
            continue
        normalized = _normalize_action(action, defaults)
        validation_problems = _action_schema_problems([normalized["execute"]])
        if validation_problems:
            problems.extend(
                problem.replace("action 1", f"action {index}", 1)
                for problem in validation_problems
            )
            continue
        normalized_actions.append(normalized)

    if problems:
        raise ValueError("; ".join(problems))

    return _NormalizedRequest(
        request_id=_optional_string(request.get("request_id")),
        source=_optional_string(request.get("source")),
        dry_run=bool(request.get("dry_run", False)),
        require_confirmation=bool(request.get("require_confirmation", False)),
        dry_run_token=_optional_string(request.get("dry_run_token")),
        plan_driven=request.get("plan_driven") is True,
        text_plan_confirmed=request.get("text_plan_confirmed") is True,
        text_plan_ref=_optional_string(request.get("text_plan_ref")),
        actions=normalized_actions,
    )


def _normalize_action(action: dict, defaults: dict) -> dict:
    """Convert an agent action into the existing executable action shape."""
    action_type = action["type"]
    target = action.get("target") if isinstance(action.get("target"), dict) else {}
    if action_type == "calendar_event.create":
        calendar_name = (
            action.get("calendar_name")
            or action.get("calendar")
            or target.get("calendar")
            or target.get("name")
            or defaults.get("default_calendar", DEFAULT_CALENDAR_NAME)
        )
        return {
            "agent_type": action_type,
            "execute": {
                "type": "calendar_event",
                "summary": action["summary"],
                "start": action["start"],
                "end": action["end"],
                "location": action.get("location"),
                "notes": action.get("notes"),
            },
            "defaults": {"default_calendar": calendar_name},
            "target": {"kind": "Calendar", "name": calendar_name},
        }
    if action_type == "reminder.create":
        list_name = (
            action.get("list_name")
            or action.get("reminder_list")
            or target.get("list")
            or target.get("reminder_list")
            or target.get("name")
            or defaults.get("default_reminder_list", DEFAULT_REMINDER_LIST)
        )
        return {
            "agent_type": action_type,
            "execute": {
                "type": "reminder",
                "name": normalize_reminder_title(action["name"], action["due_date"]),
                "due_date": action["due_date"],
                "body": action.get("body"),
                "priority": action.get("priority", 0),
                "remind_date": action.get("remind_date"),
            },
            "defaults": {"default_reminder_list": list_name},
            "target": {"kind": "Reminder list", "name": list_name},
        }
    if action_type == "note.create":
        folder_name = (
            action.get("folder_name")
            or action.get("folder")
            or target.get("folder")
            or target.get("name")
            or "Nudge"
        )
        return {
            "agent_type": action_type,
            "execute": {
                "type": "note",
                "title": action["title"],
                "body": action["body"],
            },
            "defaults": {"default_notes_folder": folder_name},
            "target": {"kind": "Notes folder", "name": folder_name},
        }
    return {
        "agent_type": action_type,
        "execute": {
            "type": "alarm",
            "time": action["time"],
            "label": action["label"],
        },
        "defaults": {},
        "target": {"kind": "Clock alarm", "name": ""},
    }


def _apply_normalized_request(
    *,
    normalized: _NormalizedRequest,
    apple_backends,
    dry_run: bool,
) -> tuple[dict, int]:
    """Apply normalized actions and return a stable JSON payload plus exit code."""
    actions = normalized.actions
    if _plan_text_confirmation_missing(normalized):
        return _agent_error_payload(
            request_id=normalized.request_id,
            source=normalized.source,
            dry_run=dry_run,
            error=agent_text_plan_confirmation_required_report(),
            confirmation_required=normalized.require_confirmation,
            plan_driven=normalized.plan_driven,
            text_plan_confirmed=normalized.text_plan_confirmed,
            text_plan_ref=normalized.text_plan_ref,
        ), 1

    _fill_backend_targets(actions, apple_backends)
    if dry_run:
        dry_run_token = (
            _confirmation_token(normalized)
            if normalized.require_confirmation
            else None
        )
        payload = _agent_payload(
            normalized=normalized,
            dry_run=True,
            success=0,
            failed_indices=[],
            errors=[],
            statuses={index: "dry_run" for index in range(1, len(actions) + 1)},
            dry_run_token=dry_run_token,
        )
        return payload, 0

    if normalized.require_confirmation:
        expected_token = _confirmation_token(normalized)
        if not normalized.dry_run_token:
            return _agent_error_payload(
                request_id=normalized.request_id,
                source=normalized.source,
                dry_run=False,
                error=agent_confirmation_required_report(),
                confirmation_required=True,
                plan_driven=normalized.plan_driven,
                text_plan_confirmed=normalized.text_plan_confirmed,
                text_plan_ref=normalized.text_plan_ref,
            ), 1
        if not hmac.compare_digest(normalized.dry_run_token, expected_token):
            return _agent_error_payload(
                request_id=normalized.request_id,
                source=normalized.source,
                dry_run=False,
                error=agent_confirmation_invalid_report(),
                confirmation_required=True,
                plan_driven=normalized.plan_driven,
                text_plan_confirmed=normalized.text_plan_confirmed,
                text_plan_ref=normalized.text_plan_ref,
            ), 1

    success = 0
    failed_indices = []
    statuses = {}
    for index, item in enumerate(actions, 1):
        executable = item["execute"]
        if execute_action(
            executable,
            alias_map={},
            defaults=item["defaults"],
            quiet=True,
            apple_backends=apple_backends,
        ):
            success += 1
            statuses[index] = "succeeded"
            log_action(
                action_type=executable["type"],
                summary=_summary(executable),
                scheduled_at=_scheduled_at(executable),
                external_id=executable.get("_external_id"),
            )
        else:
            statuses[index] = "failed"
            failed_indices.append(index)

    errors = [
        actions[index - 1]["execute"]["_error"]
        for index in failed_indices
        if actions[index - 1]["execute"].get("_error")
    ]
    payload = _agent_payload(
        normalized=normalized,
        dry_run=False,
        success=success,
        failed_indices=failed_indices,
        errors=errors,
        statuses=statuses,
        dry_run_token=None,
    )
    return payload, 1 if failed_indices else 0


def _fill_backend_targets(actions: list[dict], apple_backends) -> None:
    """Fill backend-resolved target names that are not known during validation."""
    for item in actions:
        if item["agent_type"] == "alarm.create":
            item["target"]["name"] = apple_backends.clock.shortcut_name


def _agent_payload(
    *,
    normalized: _NormalizedRequest,
    dry_run: bool,
    success: int,
    failed_indices: list[int],
    errors: list[ErrorReport],
    statuses: dict[int, str],
    dry_run_token: str | None,
) -> dict:
    """Build stable JSON response for agent apply."""
    failed = set(failed_indices)
    payload = {
        "ok": not errors and not failed_indices,
        "request_id": normalized.request_id,
        "source": normalized.source,
        "dry_run": dry_run,
        "confirmation_required": normalized.require_confirmation,
        "plan_driven": normalized.plan_driven,
        "text_plan_confirmed": normalized.text_plan_confirmed,
        "total": len(normalized.actions),
        "succeeded": success,
        "actions": [
            _action_to_json(item, index, statuses.get(index, "failed"))
            for index, item in enumerate(normalized.actions, 1)
        ],
        "failures": [
            _failure_to_json(normalized.actions[index - 1], index)
            for index in failed
        ],
        "errors": [_error_to_json(error) for error in errors],
    }
    if normalized.text_plan_ref:
        payload["text_plan_ref"] = normalized.text_plan_ref
    if dry_run_token:
        payload["dry_run_token"] = dry_run_token
    return versioned_payload(payload)


def _action_to_json(item: dict, index: int, status: str) -> dict:
    executable = item["execute"]
    data = {
        "index": index,
        "type": item["agent_type"],
        "status": status,
        "summary": _summary(executable),
        "scheduled_at": _scheduled_at(executable),
        "target": _target_for_json(item),
    }
    if executable.get("_external_id"):
        data["external_id"] = executable["_external_id"]
    if executable.get("_error"):
        data["error_code"] = executable["_error"].code
        data["error"] = executable["_error"].title
    return data


def _target_for_json(item: dict) -> dict:
    if item["agent_type"] == "alarm.create":
        return {"kind": "Clock alarm", "name": item["target"]["name"]}
    return item["target"]


def _failure_to_json(item: dict, index: int) -> dict:
    error = item["execute"].get("_error")
    return {
        "index": index,
        "summary": _summary(item["execute"]) or "<unknown>",
        "error_code": error.code if error else "ACTION_FAILED",
        "error": error.title if error else "Action failed",
    }


def _emit_agent_error(
    *,
    request_id: str | None,
    source: str | None,
    dry_run: bool,
    error: ErrorReport,
) -> None:
    click.echo(json.dumps(
        _agent_error_payload(
            request_id=request_id,
            source=source,
            dry_run=dry_run,
            error=error,
        ),
        ensure_ascii=False,
    ))


def _agent_error_payload(
    *,
    request_id: str | None,
    source: str | None,
    dry_run: bool,
    error: ErrorReport,
    confirmation_required: bool = False,
    plan_driven: bool = False,
    text_plan_confirmed: bool = False,
    text_plan_ref: str | None = None,
) -> dict:
    """Build stable JSON response for request-level agent errors."""
    payload = {
        "ok": False,
        "request_id": request_id,
        "source": source,
        "dry_run": dry_run,
        "confirmation_required": confirmation_required,
        "plan_driven": plan_driven,
        "text_plan_confirmed": text_plan_confirmed,
        "total": 0,
        "succeeded": 0,
        "actions": [],
        "failures": [],
        "errors": [_error_to_json(error)],
    }
    if text_plan_ref:
        payload["text_plan_ref"] = text_plan_ref
    return versioned_payload(payload)


def _plan_text_confirmation_missing(normalized: _NormalizedRequest) -> bool:
    """Return true when a plan-driven request lacks the required text-plan confirmation."""
    if not normalized.plan_driven:
        return False
    if not normalized.text_plan_confirmed:
        return True
    return not (normalized.text_plan_ref or "").strip()


def _confirmation_token(normalized: _NormalizedRequest) -> str:
    """Return a stable token binding a real write to a specific dry-run summary.

    This is a confirmation token, not an authentication credential. It prevents
    accidental or hidden mutation between dry-run and real write by hashing the
    exact normalized actions, targets, request id, and source.
    """
    material = {
        "version": CONFIRMATION_TOKEN_VERSION,
        "request_id": normalized.request_id,
        "source": normalized.source,
        "plan_driven": normalized.plan_driven,
        "text_plan_confirmed": normalized.text_plan_confirmed,
        "text_plan_ref": normalized.text_plan_ref,
        "actions": normalized.actions,
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hmac.new(_confirmation_secret(), raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{CONFIRMATION_TOKEN_VERSION}:{digest}"


def _confirmation_secret() -> bytes:
    """Return a stable local HMAC secret for dry-run confirmation tokens."""
    try:
        value = CONFIRMATION_SECRET_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        CONFIRMATION_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_hex(32)
        CONFIRMATION_SECRET_PATH.write_text(value + "\n", encoding="utf-8")
        CONFIRMATION_SECRET_PATH.chmod(0o600)
    return value.encode("utf-8")


def _error_to_json(error: ErrorReport) -> dict:
    return {
        "code": error.code,
        "message": error.title,
        "detail": error.detail,
        "raw_error": error.raw_error,
    }


def _summary(action: dict) -> str:
    return action.get("summary") or action.get("name") or action.get("label") or action.get("title", "")


def _scheduled_at(action: dict) -> str | None:
    return action.get("start") or action.get("due_date") or action.get("time")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
