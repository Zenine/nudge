"""Dry-run confirmation token helpers for agent apply."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from pathlib import Path
from typing import Protocol

from nudge.state import STATE_DIR


CONFIRMATION_TOKEN_VERSION = "nudge.agent.confirm.v1"
CONFIRMATION_SECRET_PATH = STATE_DIR / "agent_confirm_secret"


class ConfirmationRequest(Protocol):
    request_id: str | None
    source: str | None
    plan_driven: bool
    text_plan_confirmed: bool
    text_plan_ref: str | None
    actions: list[dict]


def configure_confirmation_state(state_dir: Path) -> None:
    """Point confirmation token storage at the active state directory."""
    global CONFIRMATION_SECRET_PATH
    CONFIRMATION_SECRET_PATH = state_dir / "agent_confirm_secret"


def confirmation_token(normalized: ConfirmationRequest) -> str:
    """Return a stable token binding a real write to a specific dry-run summary."""
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


def confirmation_token_matches(actual: str, expected: str) -> bool:
    """Compare confirmation tokens without leaking timing about the digest."""
    return hmac.compare_digest(actual, expected)


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
