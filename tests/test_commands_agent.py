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


def test_confirmation_secret_first_create_is_0600_and_returns_file_content():
    from nudge.commands.agent import CONFIRMATION_SECRET_PATH, _confirmation_secret

    secret = _confirmation_secret()

    assert isinstance(secret, bytes)
    assert secret == CONFIRMATION_SECRET_PATH.read_text(encoding="utf-8").strip().encode("utf-8")
    assert (CONFIRMATION_SECRET_PATH.stat().st_mode & 0o777) == 0o600


def test_confirmation_secret_reads_existing_without_overwrite():
    from nudge.commands.agent import CONFIRMATION_SECRET_PATH, _confirmation_secret

    CONFIRMATION_SECRET_PATH.write_text("existing-secret\n", encoding="utf-8")
    CONFIRMATION_SECRET_PATH.chmod(0o600)

    assert _confirmation_secret() == b"existing-secret"
    assert CONFIRMATION_SECRET_PATH.read_text(encoding="utf-8") == "existing-secret\n"


def test_confirmation_secret_reads_existing_when_concurrent_create_wins(monkeypatch):
    import nudge.commands.agent as agent

    agent.CONFIRMATION_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    agent.CONFIRMATION_SECRET_PATH.write_text("winner-secret\n", encoding="utf-8")
    agent.CONFIRMATION_SECRET_PATH.chmod(0o600)

    original_read_text = type(agent.CONFIRMATION_SECRET_PATH).read_text
    reads = {"count": 0}

    def read_text_with_race(path, *args, **kwargs):
        if path == agent.CONFIRMATION_SECRET_PATH and reads["count"] == 0:
            reads["count"] += 1
            raise FileNotFoundError(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(type(agent.CONFIRMATION_SECRET_PATH), "read_text", read_text_with_race)

    assert agent._confirmation_secret() == b"winner-secret"
    assert agent.CONFIRMATION_SECRET_PATH.read_text(encoding="utf-8") == "winner-secret\n"


def test_confirmation_secret_creates_parent_directory(monkeypatch):
    from nudge.commands.agent import CONFIRMATION_SECRET_PATH, _confirmation_secret
    import nudge.commands.agent as agent

    nested_secret = CONFIRMATION_SECRET_PATH.parent / "nested" / "agent_confirm_secret"
    monkeypatch.setattr(agent, "CONFIRMATION_SECRET_PATH", nested_secret)

    secret = _confirmation_secret()

    assert secret == nested_secret.read_text(encoding="utf-8").strip().encode("utf-8")
    assert (nested_secret.stat().st_mode & 0o777) == 0o600


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
