"""Public-safe tests for optional local auth on agent/MCP write entrypoints."""

import json

import pytest
from click.testing import CliRunner

import nudge.state as state
from nudge.cli import cli
from nudge.commands.agent import apply_action_status, apply_agent_request
from nudge.commands.doctor import CheckResult, PASS


PUBLIC_CONFIG = {
    "general": {"default_calendar": "Personal", "default_reminder_list": "Tasks"},
    "apple": {
        "calendar": {"backend": "native"},
        "reminders": {"backend": "native"},
        "notes": {"backend": "native"},
        "clock": {"backend": "shortcuts", "shortcut_name": "Nudge Create Alarm"},
    },
}


def _auth_config():
    return {
        **PUBLIC_CONFIG,
        "security": {
            "local_auth": {
                "enabled": True,
                "token_env": "NUDGE_TEST_LOCAL_AUTH_TOKEN",
            }
        },
    }


@pytest.fixture(autouse=True)
def isolate_state(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")
    monkeypatch.setattr("nudge.commands.agent.STATE_DIR", tmp_path)
    monkeypatch.setattr(
        "nudge.commands.agent.CONFIRMATION_SECRET_PATH",
        tmp_path / "agent_confirm_secret",
    )


def _calendar_request(**extra):
    request = {
        "request_id": "auth-write",
        "source": "auth-test",
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "Auth protected sync",
                "start": "2026-05-22 14:00",
                "end": "2026-05-22 15:00",
            }
        ],
    }
    request.update(extra)
    return request


def test_agent_apply_requires_auth_before_writes(monkeypatch):
    monkeypatch.setenv("NUDGE_TEST_LOCAL_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr(
        "nudge.commands.agent.execute_action",
        lambda action, **kwargs: (_ for _ in ()).throw(AssertionError("auth failure must not write")),
    )

    payload, exit_code = apply_agent_request(request=_calendar_request(), config=_auth_config())

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "AGENT_AUTH_REQUIRED"
    assert "secret-token" not in json.dumps(payload, ensure_ascii=False)


def test_agent_status_requires_auth_before_state_update(monkeypatch):
    monkeypatch.setenv("NUDGE_TEST_LOCAL_AUTH_TOKEN", "secret-token")
    action_id = state.log_action("calendar_event", "Protected action", status="pending")

    payload, exit_code = apply_action_status(
        request={"action_id": action_id, "status": "done", "source": "auth-test"},
        config=_auth_config(),
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "AGENT_AUTH_REQUIRED"
    assert state.get_action(action_id)["status"] == "pending"


def test_mcp_write_tool_returns_jsonrpc_unauthorized_when_auth_missing(monkeypatch):
    monkeypatch.setenv("NUDGE_TEST_LOCAL_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr("nudge.cli.load_config", lambda: _auth_config())
    monkeypatch.setattr("nudge.commands.mcp.load_config", lambda p=None: _auth_config())
    monkeypatch.setattr(
        "nudge.commands.mcp.apply_agent_request",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("auth failure must not call write engine")),
    )
    message = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "apply_apple_actions", "arguments": _calendar_request()},
    }

    result = CliRunner().invoke(cli, ["mcp", "serve"], input=json.dumps(message) + "\n", prog_name="nudge")
    responses = [json.loads(line) for line in result.output.splitlines() if line.strip()]

    assert result.exit_code == 0, result.output
    assert responses == [
        {
            "jsonrpc": "2.0",
            "id": 7,
            "error": {
                "code": -32001,
                "message": "Unauthorized",
                "data": {"code": "AGENT_AUTH_REQUIRED", "tool": "apply_apple_actions"},
            },
        }
    ]


def test_agent_apply_non_ascii_auth_token_rejected_without_crash(monkeypatch):
    # A non-ASCII auth_token is attacker-controlled input; it must be rejected as
    # unauthorized, never raise TypeError from hmac.compare_digest on str args.
    monkeypatch.setenv("NUDGE_TEST_LOCAL_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr(
        "nudge.commands.agent.execute_action",
        lambda action, **kwargs: (_ for _ in ()).throw(AssertionError("auth failure must not write")),
    )

    payload, exit_code = apply_agent_request(
        request=_calendar_request(auth_token="café-中文"),
        config=_auth_config(),
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "AGENT_AUTH_REQUIRED"


def test_mcp_serve_isolates_per_request_failures(monkeypatch):
    # A long-running stdio server must survive an unexpected error on one message
    # and keep answering later messages instead of crashing the whole loop.
    import nudge.commands.mcp as mcp_mod

    monkeypatch.setattr("nudge.cli.load_config", lambda: PUBLIC_CONFIG)
    monkeypatch.setattr("nudge.commands.mcp.load_config", lambda p=None: PUBLIC_CONFIG)

    original = mcp_mod._handle_message

    def flaky_handle_message(message, config):
        if message.get("id") == 1:
            raise RuntimeError("boom")
        return original(message, config)

    monkeypatch.setattr(mcp_mod, "_handle_message", flaky_handle_message)

    stdin = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize"})
        + "\n"
    )
    result = CliRunner().invoke(cli, ["mcp", "serve"], input=stdin, prog_name="nudge")
    responses = {
        r.get("id"): r
        for r in (json.loads(line) for line in result.output.splitlines() if line.strip())
    }

    assert result.exit_code == 0, result.output
    assert responses[1]["error"]["code"] == -32603
    assert "result" in responses[2]


def test_mcp_read_only_tools_do_not_require_auth(monkeypatch):
    monkeypatch.setenv("NUDGE_TEST_LOCAL_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr("nudge.cli.load_config", lambda: _auth_config())
    monkeypatch.setattr("nudge.commands.mcp.load_config", lambda p=None: _auth_config())
    monkeypatch.setattr(
        "nudge.commands.mcp.run_checks",
        lambda config: [CheckResult(status=PASS, name="config", message="ok")],
    )
    message = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {"name": "doctor_status", "arguments": {}},
    }

    result = CliRunner().invoke(cli, ["mcp", "serve"], input=json.dumps(message) + "\n", prog_name="nudge")
    responses = [json.loads(line) for line in result.output.splitlines() if line.strip()]

    assert result.exit_code == 0, result.output
    assert responses[0]["result"]["isError"] is False
