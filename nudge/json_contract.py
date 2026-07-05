"""Shared JSON response contract helpers for Nudge CLI.

Single source of truth for the small serialization helpers that several command
modules (`do`, `agent`, `mcp`) previously duplicated. Action/failure/target
serialization stays per-command for now because those operate on different
shapes (internal action dicts vs. agent request items).
"""

from nudge.errors import ErrorReport


CLI_SCHEMA_VERSION = "nudge.cli.v1"


def versioned_payload(payload: dict) -> dict:
    """Return a CLI JSON payload with the stable schema version."""
    data = dict(payload)
    data.pop("schema_version", None)
    return {"schema_version": CLI_SCHEMA_VERSION, **data}


def error_to_json(error: ErrorReport) -> dict:
    """Serialize an ErrorReport for machine consumers."""
    return {
        "code": error.code,
        "message": error.title,
        "detail": error.detail,
        "raw_error": error.raw_error,
    }


def action_summary(action: dict) -> str:
    """Return the display summary for any supported action."""
    return action.get("summary") or action.get("name") or action.get("label") or action.get("title", "")


def scheduled_at(action: dict) -> str | None:
    """Return the canonical action schedule timestamp."""
    return action.get("start") or action.get("due_date") or action.get("time")
