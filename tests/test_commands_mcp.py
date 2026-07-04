"""Public-safe tests for the Nudge MCP stdio wrapper."""

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


def _run_mcp(messages, monkeypatch):
    monkeypatch.setattr("nudge.cli.load_config", lambda: PUBLIC_CONFIG)
    monkeypatch.setattr("nudge.commands.mcp.load_config", lambda p=None: PUBLIC_CONFIG)
    input_text = "\n".join(json.dumps(message) for message in messages) + "\n"
    result = CliRunner().invoke(cli, ["mcp", "serve"], input=input_text, prog_name="nudge")
    responses = [json.loads(line) for line in result.output.splitlines() if line.strip()]
    return result, responses


def test_mcp_serve_initialize_and_tools_list(monkeypatch):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]

    result, responses = _run_mcp(messages, monkeypatch)

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
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "apply_apple_actions", "arguments": {"actions": []}},
        },
    ]

    result, responses = _run_mcp(messages, monkeypatch)

    assert result.exit_code == 0, result.output
    assert responses[1]["result"]["isError"] is True
    assert responses[1]["result"]["structuredContent"]["ok"] is False
