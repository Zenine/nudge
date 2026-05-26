"""Minimal MCP stdio server for Nudge Apple actions and safe notes reads.

The server intentionally exposes a small tool surface: `apply_apple_actions`
delegates Apple writes to the existing agent relay engine, while
`list_nudge_notes` only lists titles from the fixed Notes Nudge folder.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from nudge.apple.notes import (
    DEFAULT_NOTE_SUMMARY_LIMIT,
    DEFAULT_NOTES_FOLDER,
    MAX_NOTE_SUMMARY_LIMIT,
    list_nudge_note_summaries,
)
from nudge.commands.agent import (
    MAX_AGENT_ACTIONS,
    configure_agent_state,
    apply_action_status,
    apply_agent_request,
)
from nudge.commands.doctor import doctor_payload, run_checks
from nudge.config import load_config
from nudge.errors import ErrorReport, classify_apple_error
from nudge.json_contract import versioned_payload


MCP_PROTOCOL_VERSION = "2025-11-25"
SERVER_INFO = {"name": "nudge", "version": "0.5.0"}
JSONRPC_VERSION = "2.0"
_configure_agent_state = configure_agent_state


@click.group("mcp")
def mcp_command():
    """Run Nudge as a local MCP server."""
    pass


@mcp_command.command("serve")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
def serve_command(config_path):
    """Serve MCP JSON-RPC over stdio.

    Never write logs to stdout in this command; stdout is reserved for JSON-RPC
    messages.
    """
    config = load_config(config_path)
    if config_path:
        _configure_agent_state(config)
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        response = _handle_line(line, config)
        if response is not None:
            click.echo(json.dumps(response, ensure_ascii=False), nl=True)


def _handle_line(line: str, config: dict) -> dict | None:
    """Parse and handle one newline-delimited JSON-RPC message."""
    try:
        message = json.loads(line)
    except json.JSONDecodeError as e:
        return _error_response(None, -32700, f"Parse error: {e}")
    if not isinstance(message, dict):
        return _error_response(None, -32600, "Invalid Request")
    return _handle_message(message, config)


def _handle_message(message: dict, config: dict) -> dict | None:
    """Handle one parsed JSON-RPC message."""
    request_id = message.get("id")
    method = message.get("method")
    if method == "notifications/initialized":
        return None
    if "id" not in message:
        return None

    if method == "initialize":
        return _result_response(request_id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })
    if method == "tools/list":
        return _result_response(request_id, {
            "tools": [
                _apply_apple_actions_tool(),
                _report_action_status_tool(),
                _doctor_status_tool(),
                _list_nudge_notes_tool(),
            ]
        })
    if method == "tools/call":
        return _handle_tools_call(request_id, message.get("params"), config)
    return _error_response(request_id, -32601, f"Method not found: {method}")


def _handle_tools_call(request_id: Any, params: object, config: dict) -> dict:
    """Handle MCP tools/call."""
    if not isinstance(params, dict):
        return _error_response(request_id, -32602, "Invalid params")
    tool_name = params.get("name")
    if tool_name not in {"apply_apple_actions", "report_action_status", "doctor_status", "list_nudge_notes"}:
        return _error_response(request_id, -32602, f"Unknown tool: {tool_name}")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _error_response(request_id, -32602, "Tool arguments must be an object")

    if tool_name == "list_nudge_notes":
        return _handle_list_nudge_notes_call(request_id, arguments)
    if tool_name == "doctor_status":
        return _handle_doctor_status_call(request_id, arguments, config)
    if tool_name == "report_action_status":
        return _handle_report_action_status_call(request_id, arguments)

    payload, exit_code = apply_agent_request(request=arguments, config=config)
    return _result_response(request_id, _tool_result(payload, is_error=bool(exit_code)))


def _apply_apple_actions_tool() -> dict:
    """Return the MCP tool definition for structured Apple writes."""
    return {
        "name": "apply_apple_actions",
        "title": "Apply Apple Actions",
        "description": (
            "Apply structured actions to Apple Calendar / Reminders / Notes / Clock through "
            "Nudge's local adapter layer. Supports plan text confirmation, dry-run, "
            "partial failure JSON, SQLite tracking, external_id reporting, and batches "
            f"up to {MAX_AGENT_ACTIONS} actions."
        ),
        "annotations": _tool_annotations(
            title="Apply Apple Actions",
            read_only=False,
            destructive=False,
            idempotent=False,
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "Optional caller-generated request id for tracing.",
                },
                "source": {
                    "type": "string",
                    "description": "Optional calling agent or workflow name.",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Preview without writing Apple apps.",
                    "default": False,
                },
                "require_confirmation": {
                    "type": "boolean",
                    "description": (
                        "When true, dry-run returns a dry_run_token and real writes "
                        "must provide the matching token."
                    ),
                    "default": False,
                },
                "dry_run_token": {
                    "type": "string",
                    "description": "Token returned by a previous matching dry-run request.",
                },
                "plan_driven": {
                    "type": "boolean",
                    "description": (
                        "Set true when actions were generated from a multi-action text plan. "
                        "Plan-driven requests require text_plan_confirmed=true and text_plan_ref "
                        "before dry-run or write."
                    ),
                    "default": False,
                },
                "text_plan_confirmed": {
                    "type": "boolean",
                    "description": (
                        "Must be true for plan-driven requests after the user has confirmed the "
                        "human-readable text plan."
                    ),
                    "default": False,
                },
                "text_plan_ref": {
                    "type": "string",
                    "description": (
                        "Reference to the confirmed text plan, such as a repo doc path or stable note title. "
                        "Required when plan_driven=true."
                    ),
                },
                "actions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_AGENT_ACTIONS,
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "calendar_event.create",
                                    "reminder.create",
                                    "alarm.create",
                                    "note.create",
                                ],
                            }
                        },
                        "required": ["type"],
                    },
                },
            },
            "required": ["actions"],
        },
    }


def _tool_result(payload: dict, is_error: bool) -> dict:
    """Build an MCP CallToolResult from a Nudge payload."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False),
            }
        ],
        "structuredContent": payload,
        "isError": is_error,
    }


def _report_action_status_tool() -> dict:
    """Return the MCP tool definition for local-only status reporting."""
    return {
        "name": "report_action_status",
        "title": "Report Action Status",
        "description": (
            "Write action feedback back to local SQLite only. It does not read or write "
            "Apple Calendar / Reminders / Notes / Mail."
        ),
        "annotations": _tool_annotations(
            title="Report Action Status",
            read_only=False,
            destructive=False,
            idempotent=True,
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_id": {
                    "type": "string",
                    "description": "Local action id from SQLite.",
                },
                "status": {
                    "type": "string",
                    "description": "One of done / skipped / partial / deferred / blocked.",
                    "enum": ["done", "skipped", "partial", "deferred", "blocked"],
                },
                "source": {
                    "type": "string",
                    "description": "Optional caller/automation identifier.",
                },
                "note": {
                    "type": "string",
                    "description": "Optional short feedback note.",
                },
                "reason": {
                    "type": "string",
                    "enum": [
                        "too_hard",
                        "no_time",
                        "conflict",
                        "low_energy",
                        "forgot",
                        "unclear",
                        "not_important",
                        "waiting_on_other",
                    ],
                },
                "next_action": {
                    "type": "string",
                    "enum": ["keep", "reduce", "split", "reschedule", "cancel"],
                },
                "feedback": {
                    "type": "object",
                    "description": "Additional metadata merged into structured feedback.",
                    "additionalProperties": True,
                },
            },
            "required": ["action_id", "status"],
        },
    }


def _doctor_status_tool() -> dict:
    """Return the MCP tool definition for read-only local diagnostics."""
    return {
        "name": "doctor_status",
        "title": "Doctor Status",
        "description": (
            "Run Nudge's read-only local doctor diagnostics and return PASS/WARN/FAIL "
            "checks plus fix hints. Does not write Apple apps, read note bodies, or expose "
            "Calendar / Reminders / Mail item contents."
        ),
        "annotations": _tool_annotations(
            title="Doctor Status",
            read_only=True,
            destructive=False,
            idempotent=True,
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "include_pass": {
                    "type": "boolean",
                    "default": True,
                    "description": "When false, return only WARN/FAIL check rows while keeping full summary counts.",
                }
            },
        },
    }


def _handle_doctor_status_call(request_id: Any, arguments: dict, config: dict) -> dict:
    """Handle the read-only doctor_status MCP tool."""
    if extra := sorted(set(arguments) - {"include_pass"}):
        payload = _mcp_doctor_error_payload(
            mcp_request_error_report(
                f"doctor_status only accepts `include_pass`; rejected fields: {', '.join(extra)}",
                tool_name="doctor_status",
            )
        )
        return _result_response(request_id, _tool_result(payload, is_error=True))

    include_pass = arguments.get("include_pass", True)
    if not isinstance(include_pass, bool):
        payload = _mcp_doctor_error_payload(
            mcp_request_error_report(
                "doctor_status `include_pass` must be a boolean",
                tool_name="doctor_status",
            )
        )
        return _result_response(request_id, _tool_result(payload, is_error=True))

    payload = doctor_payload(run_checks(config=config), include_pass=include_pass)
    payload["tool"] = "doctor_status"
    return _result_response(request_id, _tool_result(payload, is_error=not bool(payload.get("ok"))))


def _handle_report_action_status_call(request_id: Any, arguments: dict) -> dict:
    """Handle MCP tool call for local-only status feedback."""
    if not isinstance(arguments, dict):
        payload = versioned_payload({
            "ok": False,
            "request_id": None,
            "source": None,
            "dry_run": False,
            "total": 0,
            "succeeded": 0,
            "actions": [],
            "failures": [],
            "errors": [
                {
                    "code": "MCP_REQUEST_INVALID",
                    "message": "MCP tool arguments must be an object",
                    "detail": "report_action_status arguments must be an object",
                    "raw_error": "arguments must be object",
                }
            ],
        })
        return _result_response(request_id, _tool_result(payload, is_error=True))

    payload, exit_code = apply_action_status(
        request=arguments,
        dry_run_override=False,
        feedback_channel="mcp.report_action_status",
        feedback_source_type="agent",
    )
    return _result_response(request_id, _tool_result(payload, is_error=bool(exit_code)))


def _list_nudge_notes_tool() -> dict:
    """Return the MCP tool definition for safe Nudge Notes listing."""
    return {
        "name": "list_nudge_notes",
        "title": "List Nudge Notes",
        "description": (
            "List note titles and title-derived summaries from the fixed Apple Notes "
            "Nudge Notes folder. Does not read note bodies and does not accept arbitrary folders."
        ),
        "annotations": _tool_annotations(
            title="List Nudge Notes",
            read_only=True,
            destructive=False,
            idempotent=True,
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_NOTE_SUMMARY_LIMIT,
                    "default": DEFAULT_NOTE_SUMMARY_LIMIT,
                    "description": "Maximum number of Nudge folder note titles to return.",
                }
            },
        },
    }


def _tool_annotations(
    *,
    title: str,
    read_only: bool,
    destructive: bool,
    idempotent: bool,
) -> dict:
    """Return MCP ToolAnnotations for client-side UI hints.

    These hints are not a security boundary; server-side schema, dry-run token,
    and local execution validation remain authoritative.
    """
    return {
        "title": title,
        "readOnlyHint": read_only,
        "destructiveHint": destructive,
        "idempotentHint": idempotent,
        "openWorldHint": False,
    }


def _handle_list_nudge_notes_call(request_id: Any, arguments: dict) -> dict:
    """Handle the read-only Nudge Notes MCP tool."""
    if extra := sorted(set(arguments) - {"limit"}):
        payload = _mcp_notes_error_payload(
            mcp_request_error_report(
                f"list_nudge_notes only accepts `limit`; rejected fields: {', '.join(extra)}"
            ),
            limit=DEFAULT_NOTE_SUMMARY_LIMIT,
        )
        return _result_response(request_id, _tool_result(payload, is_error=True))

    limit = _notes_limit(arguments.get("limit", DEFAULT_NOTE_SUMMARY_LIMIT))
    ok, result = list_nudge_note_summaries(limit=limit)
    if not ok:
        error = classify_apple_error("Notes", "Notes folder", DEFAULT_NOTES_FOLDER, str(result))
        return _result_response(
            request_id,
            _tool_result(_mcp_notes_error_payload(error, limit=limit), is_error=True),
        )

    payload = versioned_payload({
        "ok": True,
        "tool": "list_nudge_notes",
        "folder": DEFAULT_NOTES_FOLDER,
        "limit": limit,
        "total": len(result),
        "notes": result,
        "errors": [],
    })
    return _result_response(request_id, _tool_result(payload, is_error=False))


def _notes_limit(value: object) -> int:
    """Return a safe Notes listing limit from MCP arguments."""
    if isinstance(value, bool):
        return DEFAULT_NOTE_SUMMARY_LIMIT
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_NOTE_SUMMARY_LIMIT
    return max(1, min(limit, MAX_NOTE_SUMMARY_LIMIT))


def mcp_request_error_report(raw_error: str, *, tool_name: str = "list_nudge_notes") -> ErrorReport:
    """Build a structured MCP request validation error."""
    raw = str(raw_error or "").strip()
    if tool_name == "doctor_status":
        next_steps = (
            "`doctor_status` 只允许传 `include_pass`，不能传 config_path、文件路径或 Apple 数据读取参数。",
            "如果需要不同配置，请在启动 MCP server 时指定配置，不要通过 tool call 暴露任意路径。",
            "不要把 Calendar / Reminders / Mail 个人内容暴露给 MCP client。",
        )
    else:
        next_steps = (
            "`list_nudge_notes` 只允许传 `limit`，不能传 folder、search query 或 body 读取参数。",
            "如果需要读取其他来源，新增单独 tool 并重新审查安全边界。",
            "不要把任意 Notes folder 暴露给 MCP client。",
        )
    return ErrorReport(
        code="MCP_REQUEST_INVALID",
        title="MCP tool arguments 无效",
        detail=raw,
        next_steps=next_steps,
        raw_error=raw,
    )


def _mcp_notes_error_payload(error: ErrorReport, *, limit: int) -> dict:
    """Build stable JSON for list_nudge_notes errors."""
    return versioned_payload({
        "ok": False,
        "tool": "list_nudge_notes",
        "folder": DEFAULT_NOTES_FOLDER,
        "limit": limit,
        "total": 0,
        "notes": [],
        "errors": [_error_to_json(error)],
    })


def _mcp_doctor_error_payload(error: ErrorReport) -> dict:
    """Build stable JSON for doctor_status request errors."""
    return versioned_payload({
        "ok": False,
        "tool": "doctor_status",
        "summary": {"PASS": 0, "WARN": 0, "FAIL": 0},
        "checks": [],
        "errors": [_error_to_json(error)],
    })


def _error_to_json(error: ErrorReport) -> dict:
    return {
        "code": error.code,
        "message": error.title,
        "detail": error.detail,
        "raw_error": error.raw_error,
    }


def _result_response(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> dict:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }
