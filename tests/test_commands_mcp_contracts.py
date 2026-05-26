"""MCP stdio JSON-RPC contract tests."""

import json

from click.testing import CliRunner

from nudge.cli import cli


PUBLIC_CONFIG = {
    "general": {"default_calendar": "Personal", "default_reminder_list": "Tasks"},
    "apple": {
        "calendar": {"backend": "native"},
        "reminders": {"backend": "native"},
        "notes": {"backend": "native"},
        "clock": {"backend": "shortcuts", "shortcut_name": "Nudge Create Alarm"},
    },
}


def test_initialize_returns_server_info_and_protocol_capabilities(monkeypatch):
    result, responses = _run_mcp(
        monkeypatch,
        [
            {
                "jsonrpc": "2.0",
                "id": "init-1",
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            }
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(responses) == 1
    assert responses[0] == {
        "jsonrpc": "2.0",
        "id": "init-1",
        "result": {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "nudge", "version": "0.5.0"},
        },
    }


def test_tools_list_exposes_expected_tools_and_read_only_annotations(monkeypatch):
    result, responses = _run_mcp(
        monkeypatch,
        [{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}],
    )

    assert result.exit_code == 0, result.output
    tools = {tool["name"]: tool for tool in responses[0]["result"]["tools"]}
    assert list(tools) == [
        "apply_apple_actions",
        "report_action_status",
        "doctor_status",
        "list_nudge_notes",
    ]

    assert tools["apply_apple_actions"]["annotations"]["readOnlyHint"] is False
    assert tools["report_action_status"]["annotations"]["readOnlyHint"] is False
    assert tools["doctor_status"]["annotations"]["readOnlyHint"] is True
    assert tools["doctor_status"]["annotations"]["destructiveHint"] is False
    assert tools["doctor_status"]["annotations"]["idempotentHint"] is True
    assert tools["list_nudge_notes"]["annotations"]["readOnlyHint"] is True
    assert tools["list_nudge_notes"]["annotations"]["destructiveHint"] is False
    assert tools["list_nudge_notes"]["annotations"]["idempotentHint"] is True


def test_apply_apple_actions_invalid_input_returns_tool_error_without_crashing(monkeypatch):
    _forbid_apple_writes(monkeypatch)
    result, responses = _run_mcp(
        monkeypatch,
        [
            {
                "jsonrpc": "2.0",
                "id": "bad-apply",
                "method": "tools/call",
                "params": {"name": "apply_apple_actions", "arguments": {"actions": []}},
            }
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(responses) == 1
    response = responses[0]
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "bad-apply"
    assert "error" not in response
    assert response["result"]["isError"] is True
    assert response["result"]["structuredContent"]["ok"] is False
    assert response["result"]["content"][0]["type"] == "text"
    assert json.loads(response["result"]["content"][0]["text"]) == response["result"]["structuredContent"]


def test_unknown_method_and_unknown_tool_keep_stdout_jsonrpc_pure(monkeypatch):
    _forbid_apple_writes(monkeypatch)
    result, responses = _run_mcp(
        monkeypatch,
        [
            {"jsonrpc": "2.0", "id": "missing-method", "method": "nudge/nope", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": "missing-tool",
                "method": "tools/call",
                "params": {"name": "definitely_not_a_tool", "arguments": {}},
            },
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(responses) == 2
    assert responses[0]["error"]["code"] == -32601
    assert responses[0]["error"]["message"] == "Method not found: nudge/nope"
    assert responses[1]["error"]["code"] == -32602
    assert responses[1]["error"]["message"] == "Unknown tool: definitely_not_a_tool"
    assert [line["jsonrpc"] for line in responses] == ["2.0", "2.0"]


def test_mcp_serve_configures_agent_state_for_explicit_config(monkeypatch):
    configured = []
    custom_config = {
        **PUBLIC_CONFIG,
        "state": {"dir": "/tmp/nudge-mcp-test-state"},
    }
    monkeypatch.setattr("nudge.cli.load_config", lambda: PUBLIC_CONFIG)
    monkeypatch.setattr("nudge.commands.mcp.load_config", lambda p=None: custom_config)
    monkeypatch.setattr(
        "nudge.commands.mcp._configure_agent_state",
        lambda config: configured.append(config),
    )

    input_text = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}) + "\n"
    result = CliRunner().invoke(
        cli,
        ["mcp", "serve", "--config", "custom.toml"],
        input=input_text,
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert configured == [custom_config]


def _run_mcp(monkeypatch, messages):
    monkeypatch.setattr("nudge.cli.load_config", lambda: PUBLIC_CONFIG)
    monkeypatch.setattr("nudge.commands.mcp.load_config", lambda p=None: PUBLIC_CONFIG)
    input_text = "\n".join(json.dumps(message) for message in messages) + "\n"
    result = CliRunner().invoke(cli, ["mcp", "serve"], input=input_text, prog_name="nudge")
    responses = [json.loads(line) for line in result.output.splitlines() if line.strip()]
    return result, responses


def _forbid_apple_writes(monkeypatch):
    def fail_write(**kwargs):
        raise AssertionError("MCP contract tests must not touch real Apple apps")

    monkeypatch.setattr("nudge.apple.adapters.create_calendar_event", fail_write)
    monkeypatch.setattr("nudge.apple.adapters.create_reminder", fail_write)
    monkeypatch.setattr("nudge.apple.adapters.create_note", fail_write)
    monkeypatch.setattr("nudge.apple.adapters.create_alarm", fail_write)
