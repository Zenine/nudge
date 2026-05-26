"""Public-safe regression tests mirrored from the private control plane."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from nudge.cli import cli
from nudge.commands.agent import _normalize_action, apply_agent_request
from nudge.config import get_defaults, get_family_aliases, load_config
from nudge.json_contract import CLI_SCHEMA_VERSION, versioned_payload


PUBLIC_CONFIG = {
    "general": {"default_calendar": "Personal", "default_reminder_list": "Tasks"},
    "apple": {
        "calendar": {"backend": "native"},
        "reminders": {"backend": "native"},
        "notes": {"backend": "native"},
        "clock": {"backend": "shortcuts", "shortcut_name": "Nudge Create Alarm"},
    },
}


@pytest.fixture(autouse=True)
def isolate_agent_state(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.commands.agent.STATE_DIR", tmp_path)
    monkeypatch.setattr(
        "nudge.commands.agent_confirmation.CONFIRMATION_SECRET_PATH",
        tmp_path / "agent_confirm_secret",
    )


def test_load_config_reads_explicit_public_safe_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                "[general]",
                'default_calendar = "Personal"',
                'default_reminder_list = "Tasks"',
                "",
                "[llm]",
                'provider = "qwen"',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(Path(path))

    assert config["general"]["default_calendar"] == "Personal"
    assert config["llm"]["provider"] == "qwen"


def test_get_defaults_uses_public_safe_values():
    defaults = get_defaults(
        {
            "general": {
                "default_calendar": "Personal",
                "default_reminder_list": "Tasks",
            }
        }
    )

    assert defaults == {
        "default_calendar": "Personal",
        "default_reminder_list": "Tasks",
    }


def test_get_family_aliases_handles_empty_public_config():
    all_aliases, alias_map = get_family_aliases({})

    assert all_aliases == []
    assert alias_map == {}


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
    assert payload["schema_version"] == CLI_SCHEMA_VERSION
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


def test_mcp_serve_initialize_and_tools_list(monkeypatch):
    result, responses = _run_mcp(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ],
        monkeypatch,
    )

    assert result.exit_code == 0, result.output
    assert responses[0]["result"]["serverInfo"]["name"] == "nudge"
    tools = responses[1]["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "apply_apple_actions",
        "report_action_status",
        "doctor_status",
        "list_nudge_notes",
    ]
    assert tools[0]["inputSchema"]["type"] == "object"
    assert tools[2]["annotations"]["readOnlyHint"] is True


def test_mcp_validation_error_is_tool_error(monkeypatch):
    result, responses = _run_mcp(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "apply_apple_actions", "arguments": {"actions": []}},
            },
        ],
        monkeypatch,
    )

    assert result.exit_code == 0, result.output
    assert responses[1]["result"]["isError"] is True
    assert responses[1]["result"]["structuredContent"]["ok"] is False


def test_versioned_payload_adds_stable_schema_version():
    payload = versioned_payload({"ok": True, "value": 42})

    assert payload == {
        "schema_version": CLI_SCHEMA_VERSION,
        "ok": True,
        "value": 42,
    }


def test_versioned_payload_replaces_caller_schema_version():
    payload = versioned_payload({"schema_version": "old", "ok": True})

    assert payload == {"schema_version": CLI_SCHEMA_VERSION, "ok": True}


def _run_mcp(messages, monkeypatch):
    monkeypatch.setattr("nudge.cli.load_config", lambda: PUBLIC_CONFIG)
    monkeypatch.setattr("nudge.commands.mcp.load_config", lambda p=None: PUBLIC_CONFIG)
    input_text = "\n".join(json.dumps(message) for message in messages) + "\n"
    result = CliRunner().invoke(cli, ["mcp", "serve"], input=input_text, prog_name="nudge")
    responses = [json.loads(line) for line in result.output.splitlines() if line.strip()]
    return result, responses
