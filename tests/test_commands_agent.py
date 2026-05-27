"""Public-safe tests for agent-facing Apple action relay behavior."""

import json

import pytest

from nudge.commands.agent import _normalize_action, apply_agent_request
from nudge.config import get_defaults


PUBLIC_CONFIG = {
    "general": {"default_calendar": "Personal", "default_reminder_list": "Tasks"},
    "apple": {
        "calendar": {"backend": "native"},
        "reminders": {"backend": "native"},
    },
}


@pytest.fixture(autouse=True)
def isolate_agent_state(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.commands.agent.STATE_DIR", tmp_path)
    monkeypatch.setattr(
        "nudge.commands.agent.CONFIRMATION_SECRET_PATH",
        tmp_path / "agent_confirm_secret",
    )


def test_agent_apply_dry_run_outputs_contract_without_writes(monkeypatch):
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not write Calendar")),
    )
    request = {
        "request_id": "public-dry-run",
        "source": "public-test",
        "dry_run": True,
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "Project sync",
                "start": "2026-05-22 14:00",
                "end": "2026-05-22 15:00",
            }
        ],
    }

    payload, exit_code = apply_agent_request(request=request, config=PUBLIC_CONFIG)

    assert exit_code == 0
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["actions"][0]["status"] == "dry_run"
    assert payload["actions"][0]["target"] == {"kind": "Calendar", "name": "Personal"}


def test_agent_apply_rejects_too_many_actions():
    request = {
        "request_id": "too-many",
        "source": "public-test",
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": f"Batch event {index}",
                "start": "2026-05-22 09:00",
                "end": "2026-05-22 09:15",
            }
            for index in range(11)
        ],
    }

    payload, exit_code = apply_agent_request(request=request, config=PUBLIC_CONFIG)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "AGENT_BATCH_TOO_LARGE"


def test_agent_normalize_reminder_uses_public_defaults():
    normalized = _normalize_action(
        {
            "type": "reminder.create",
            "name": "Review notes",
            "due_date": "2026-05-22 18:00",
        },
        get_defaults(PUBLIC_CONFIG),
    )

    assert json.dumps(normalized, ensure_ascii=True)
    assert normalized["target"] == {"kind": "Reminder list", "name": "Tasks"}
