"""Public-safe tests for the Nudge MCP stdio wrapper."""

import json

from click.testing import CliRunner

from nudge.cli import cli
from nudge.commands.doctor import CheckResult


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
    monkeypatch.setattr("nudge.cli.load_config", lambda p=None: PUBLIC_CONFIG)
    monkeypatch.setattr("nudge.commands.mcp.load_config", lambda p=None: PUBLIC_CONFIG)
    input_text = "\n".join(json.dumps(message) for message in messages) + "\n"
    result = CliRunner().invoke(cli, ["mcp", "serve"], input=input_text, prog_name="nudge")
    responses = [json.loads(line) for line in result.output.splitlines() if line.strip()]
    return result, responses


def test_mcp_serve_accepts_top_level_config(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[state]",
                'dir = "state"',
                "",
                "[general]",
                'default_calendar = "Top Level Calendar"',
                'default_reminder_list = "Top Level Tasks"',
                "",
                "[apple.calendar]",
                'backend = "native"',
                "",
                "[apple.reminders]",
                'backend = "native"',
                "",
                "[apple.notes]",
                'backend = "native"',
                "",
                "[apple.clock]",
                'backend = "shortcuts"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("NUDGE_CONFIG", raising=False)
    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    result = CliRunner().invoke(
        cli,
        ["--config", str(config_path), "mcp", "serve"],
        input=json.dumps(message) + "\n",
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    responses = [json.loads(line) for line in result.output.splitlines() if line.strip()]
    assert responses[0]["result"]["tools"][0]["name"] == "apply_apple_actions"


def test_mcp_serve_initialize_and_tools_list(monkeypatch):
    monkeypatch.setattr("nudge.commands.mcp.get_version", lambda: "9.8.7", raising=False)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]

    result, responses = _run_mcp(messages, monkeypatch)

    assert result.exit_code == 0, result.output
    assert responses[0]["result"]["serverInfo"]["name"] == "nudge"
    assert responses[0]["result"]["serverInfo"]["version"] == "9.8.7"
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


def test_mcp_ping_returns_success(monkeypatch):
    messages = [{"jsonrpc": "2.0", "id": "ping-1", "method": "ping", "params": {}}]

    result, responses = _run_mcp(messages, monkeypatch)

    assert result.exit_code == 0, result.output
    assert responses == [{"jsonrpc": "2.0", "id": "ping-1", "result": {}}]


def test_mcp_unsupported_probe_methods_return_stable_errors(monkeypatch):
    messages = [
        {"jsonrpc": "2.0", "id": "prompts", "method": "prompts/list", "params": {}},
        {"jsonrpc": "2.0", "id": "resources", "method": "resources/list", "params": {}},
        {"jsonrpc": "2.0", "id": "unknown", "method": "nudge/unknown", "params": {}},
    ]

    result, responses = _run_mcp(messages, monkeypatch)

    assert result.exit_code == 0, result.output
    assert responses[0]["error"] == {
        "code": -32000,
        "message": "Unsupported MCP capability: prompts/list",
        "data": {"capability": "prompts", "supported": False},
    }
    assert responses[1]["error"] == {
        "code": -32000,
        "message": "Unsupported MCP capability: resources/list",
        "data": {"capability": "resources", "supported": False},
    }
    assert responses[2]["error"]["code"] == -32601


def test_mcp_doctor_status_returns_checks_and_keeps_llm_ping_disabled(monkeypatch):
    observed = {}

    def fake_run_checks(*, config, llm_ping):
        observed["config"] = config
        observed["llm_ping"] = llm_ping
        return [
            CheckResult("PASS", "Config", "config ok"),
            CheckResult("WARN", "SQLite", "state database not found"),
            CheckResult("FAIL", "Daemon", "dead_letter=1"),
        ]

    monkeypatch.setattr("nudge.commands.mcp.run_checks", fake_run_checks)
    messages = [
        {
            "jsonrpc": "2.0",
            "id": "doctor",
            "method": "tools/call",
            "params": {"name": "doctor_status", "arguments": {"include_pass": False}},
        }
    ]

    result, responses = _run_mcp(messages, monkeypatch)

    assert result.exit_code == 0, result.output
    assert observed == {"config": PUBLIC_CONFIG, "llm_ping": False}
    tool_result = responses[0]["result"]
    payload = tool_result["structuredContent"]
    assert tool_result["isError"] is True
    assert payload["tool"] == "doctor_status"
    assert payload["summary"] == {"PASS": 1, "WARN": 1, "FAIL": 1}
    assert [check["name"] for check in payload["checks"]] == ["SQLite", "Daemon"]
    assert json.loads(tool_result["content"][0]["text"]) == payload


def test_mcp_doctor_status_rejects_path_and_llm_ping_arguments_without_running_doctor(monkeypatch):
    def fail_run_checks(**kwargs):
        raise AssertionError(f"run_checks must not be called for rejected arguments: {kwargs}")

    monkeypatch.setattr("nudge.commands.mcp.run_checks", fail_run_checks)
    messages = [
        {
            "jsonrpc": "2.0",
            "id": "doctor",
            "method": "tools/call",
            "params": {
                "name": "doctor_status",
                "arguments": {
                    "config_path": "/tmp/private.toml",
                    "file": "/tmp/nudge.db",
                    "llm_ping": True,
                },
            },
        }
    ]

    result, responses = _run_mcp(messages, monkeypatch)

    assert result.exit_code == 0, result.output
    tool_result = responses[0]["result"]
    payload = tool_result["structuredContent"]
    assert tool_result["isError"] is True
    assert payload["ok"] is False
    assert payload["tool"] == "doctor_status"
    assert payload["checks"] == []
    assert payload["errors"][0]["code"] == "MCP_REQUEST_INVALID"
    assert "config_path" in payload["errors"][0]["detail"]
    assert "file" in payload["errors"][0]["detail"]
    assert "llm_ping" in payload["errors"][0]["detail"]
