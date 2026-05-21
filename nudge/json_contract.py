"""Shared JSON response contract helpers for Nudge CLI."""

CLI_SCHEMA_VERSION = "nudge.cli.v1"


def versioned_payload(payload: dict) -> dict:
    """Return a CLI JSON payload with the stable schema version."""
    data = dict(payload)
    data.pop("schema_version", None)
    return {"schema_version": CLI_SCHEMA_VERSION, **data}
