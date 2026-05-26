"""Regression tests for the agent apply safety contract."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from nudge.apple.adapters import AppleBackends, WriteResult
from nudge.commands.agent import apply_agent_request
from nudge.json_contract import CLI_SCHEMA_VERSION


PUBLIC_CONFIG = {
    "general": {"default_calendar": "Personal", "default_reminder_list": "Tasks"},
    "apple": {
        "calendar": {"backend": "native"},
        "reminders": {"backend": "native"},
        "notes": {"backend": "native"},
        "clock": {"backend": "shortcuts", "shortcut_name": "Nudge Create Alarm"},
    },
}


@dataclass
class FakeCalendarBackend:
    writes: list[dict]
    fail_summaries: set[str] | None = None
    name: str = "fake-calendar"

    def create_event(self, **kwargs) -> WriteResult:
        self.writes.append(kwargs)
        if kwargs["summary"] in (self.fail_summaries or set()):
            return WriteResult(ok=False, message="Calendar permission denied")
        return WriteResult(ok=True, message="created", external_id=f"calendar:{len(self.writes)}")


@dataclass
class FakeRemindersBackend:
    writes: list[dict]
    name: str = "fake-reminders"

    def create_reminder(self, **kwargs) -> WriteResult:
        self.writes.append(kwargs)
        return WriteResult(ok=True, message="created", external_id=f"reminder:{len(self.writes)}")


@dataclass
class FakeClockBackend:
    writes: list[dict]
    shortcut_name: str = "Fake Alarm Shortcut"
    name: str = "fake-clock"

    def create_alarm(self, **kwargs) -> WriteResult:
        self.writes.append(kwargs)
        return WriteResult(ok=True, message="created", external_id=f"alarm:{len(self.writes)}")


@dataclass
class FakeNotesBackend:
    writes: list[dict]
    name: str = "fake-notes"

    def create_note(self, **kwargs) -> WriteResult:
        self.writes.append(kwargs)
        return WriteResult(ok=True, message="created", external_id=f"note:{len(self.writes)}")


@pytest.fixture
def fake_apple_backends(monkeypatch):
    writes = {"calendar": [], "reminders": [], "clock": [], "notes": []}
    backends = AppleBackends(
        calendar=FakeCalendarBackend(writes["calendar"]),
        reminders=FakeRemindersBackend(writes["reminders"]),
        clock=FakeClockBackend(writes["clock"]),
        notes=FakeNotesBackend(writes["notes"]),
    )
    monkeypatch.setattr("nudge.commands.agent.resolve_apple_backends", lambda config: backends)
    return backends, writes


@pytest.fixture(autouse=True)
def isolate_agent_state(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.commands.agent.STATE_DIR", tmp_path)
    monkeypatch.setattr(
        "nudge.commands.agent.CONFIRMATION_SECRET_PATH",
        tmp_path / "agent_confirm_secret",
    )


def calendar_action(summary: str = "Project sync") -> dict:
    return {
        "type": "calendar_event.create",
        "summary": summary,
        "start": "2026-05-22 14:00",
        "end": "2026-05-22 15:00",
    }


def apply_request(request: dict) -> tuple[dict, int]:
    return apply_agent_request(request=request, config=PUBLIC_CONFIG)


@pytest.mark.parametrize(
    "missing_fields",
    [
        {"text_plan_confirmed": False, "text_plan_ref": "docs/confirmed-plan.md"},
        {"text_plan_confirmed": True},
    ],
)
def test_plan_driven_request_requires_text_plan_confirmation_before_dry_run(
    fake_apple_backends,
    missing_fields,
):
    _backends, writes = fake_apple_backends
    request = {
        "request_id": "plan-missing-confirmation",
        "source": "contract-test",
        "dry_run": True,
        "require_confirmation": True,
        "plan_driven": True,
        "actions": [calendar_action()],
        **missing_fields,
    }

    payload, exit_code = apply_request(request)

    assert exit_code == 1
    assert payload["schema_version"] == CLI_SCHEMA_VERSION
    assert payload["ok"] is False
    assert payload["dry_run"] is True
    assert payload["errors"][0]["code"] == "AGENT_TEXT_PLAN_CONFIRMATION_REQUIRED"
    assert "dry_run_token" not in payload
    assert writes["calendar"] == []


def test_confirmation_token_required_and_bound_to_matching_request(fake_apple_backends):
    _backends, writes = fake_apple_backends
    base_request = {
        "request_id": "confirm-token",
        "source": "contract-test",
        "require_confirmation": True,
        "actions": [calendar_action()],
    }

    dry_run_payload, dry_run_exit = apply_request({**base_request, "dry_run": True})

    assert dry_run_exit == 0
    assert dry_run_payload["ok"] is True
    assert dry_run_payload["dry_run_token"].startswith("nudge.agent.confirm.v1:")
    assert dry_run_payload["actions"][0]["status"] == "dry_run"
    assert writes["calendar"] == []

    missing_token_payload, missing_token_exit = apply_request({**base_request, "dry_run": False})

    assert missing_token_exit == 1
    assert missing_token_payload["ok"] is False
    assert missing_token_payload["errors"][0]["code"] == "AGENT_CONFIRMATION_REQUIRED"
    assert writes["calendar"] == []

    changed_request = {
        **base_request,
        "dry_run": False,
        "dry_run_token": dry_run_payload["dry_run_token"],
        "actions": [calendar_action("Different project sync")],
    }

    invalid_token_payload, invalid_token_exit = apply_request(changed_request)

    assert invalid_token_exit == 1
    assert invalid_token_payload["ok"] is False
    assert invalid_token_payload["errors"][0]["code"] == "AGENT_CONFIRMATION_INVALID"
    assert writes["calendar"] == []

    write_payload, write_exit = apply_request(
        {
            **base_request,
            "dry_run": False,
            "dry_run_token": dry_run_payload["dry_run_token"],
        }
    )

    assert write_exit == 0
    assert write_payload["ok"] is True
    assert write_payload["actions"][0]["status"] == "succeeded"
    assert write_payload["actions"][0]["external_id"] == "calendar:1"
    assert len(writes["calendar"]) == 1


def test_agent_apply_rejects_more_than_ten_actions_before_writes(fake_apple_backends):
    _backends, writes = fake_apple_backends
    request = {
        "request_id": "too-many",
        "source": "contract-test",
        "actions": [calendar_action(f"Batch event {index}") for index in range(11)],
    }

    payload, exit_code = apply_request(request)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "AGENT_BATCH_TOO_LARGE"
    assert payload["actions"] == []
    assert writes["calendar"] == []


def test_partial_failure_returns_parseable_payload_and_keeps_successes(monkeypatch, fake_apple_backends):
    backends, writes = fake_apple_backends
    backends.calendar.fail_summaries = {"Failing event"}
    logged_actions = []
    monkeypatch.setattr(
        "nudge.commands.agent.log_action",
        lambda **kwargs: logged_actions.append(kwargs) or f"action-{len(logged_actions)}",
    )
    request = {
        "request_id": "partial-failure",
        "source": "contract-test",
        "actions": [
            calendar_action("Successful event"),
            calendar_action("Failing event"),
        ],
    }

    payload, exit_code = apply_request(request)
    parsed_payload = json.loads(json.dumps(payload, ensure_ascii=False))

    assert exit_code == 1
    assert parsed_payload["schema_version"] == CLI_SCHEMA_VERSION
    assert parsed_payload["ok"] is False
    assert parsed_payload["total"] == 2
    assert parsed_payload["succeeded"] == 1
    assert parsed_payload["actions"][0]["status"] == "succeeded"
    assert parsed_payload["actions"][0]["external_id"] == "calendar:1"
    assert parsed_payload["actions"][1]["status"] == "failed"
    assert parsed_payload["actions"][1]["error_code"].startswith("APPLE_")
    assert parsed_payload["failures"] == [
        {
            "index": 2,
            "summary": "Failing event",
            "error_code": parsed_payload["actions"][1]["error_code"],
            "error": parsed_payload["actions"][1]["error"],
        }
    ]
    assert parsed_payload["errors"][0]["code"] == parsed_payload["actions"][1]["error_code"]
    assert len(writes["calendar"]) == 2
    assert logged_actions == [
        {
            "action_type": "calendar_event",
            "summary": "Successful event",
            "scheduled_at": "2026-05-22 14:00",
            "external_id": "calendar:1",
        }
    ]
