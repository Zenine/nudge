import json

from click.testing import CliRunner

from nudge.cli import cli


PUBLIC_CONFIG = {
    "general": {
        "default_calendar": "Personal",
        "default_reminder_list": "Tasks",
    },
    "apple": {
        "calendar": {"backend": "native"},
        "reminders": {"backend": "native"},
    },
}


def _patch_chat_context(monkeypatch):
    monkeypatch.setattr("nudge.cli.configure_brain", lambda llm_config: None)
    monkeypatch.setattr("nudge.commands.chat.get_today_events", lambda calendar_names=None: [])
    monkeypatch.setattr("nudge.commands.chat.get_due_today", lambda: [])
    monkeypatch.setattr("nudge.commands.chat.get_actions", lambda **kwargs: [])
    monkeypatch.setattr("nudge.commands.chat.get_habit_streaks", lambda: {})


def _chat_response_with(action: dict) -> str:
    return "可以。\n```json\n" + json.dumps([action], ensure_ascii=False) + "\n```"


def test_chat_dry_run_json_uses_config_for_context_and_action_processing(monkeypatch, tmp_path):
    _patch_chat_context(monkeypatch)
    config_path = tmp_path / "config.toml"
    config_path.write_text("[general]\ndefault_calendar = 'Work'\n")
    load_config_calls = []
    apply_calls = []

    def fake_load_config(path=None):
        load_config_calls.append(path)
        return PUBLIC_CONFIG

    def fake_apply_agent_request(*, request, config, dry_run_override=False):
        apply_calls.append(
            {
                "request": request,
                "config": config,
                "dry_run_override": dry_run_override,
            }
        )
        return {
            "schema_version": "nudge.cli.v1",
            "ok": True,
            "dry_run": True,
            "actions": [
                {
                    "index": 1,
                    "type": "calendar_event.create",
                    "status": "dry_run",
                    "summary": "项目同步",
                    "scheduled_at": "2026-06-08 09:00",
                    "target": {"kind": "Calendar", "name": "Personal"},
                }
            ],
            "errors": [],
        }, 0

    monkeypatch.setattr("nudge.commands.chat.load_config", fake_load_config)
    monkeypatch.setattr(
        "nudge.commands.chat.call_llm",
        lambda system, prompt, task="default": _chat_response_with(
            {
                "type": "calendar_event",
                "summary": "项目同步",
                "start": "2026-06-08 09:00",
                "end": "2026-06-08 10:00",
            }
        ),
    )
    monkeypatch.setattr("nudge.commands.chat.apply_agent_request", fake_apply_agent_request)

    result = CliRunner().invoke(
        cli,
        ["chat", "--config", str(config_path), "--dry-run", "--json", "帮我安排项目同步"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert load_config_calls == [str(config_path)]
    assert apply_calls[0]["config"] is PUBLIC_CONFIG
    assert apply_calls[0]["dry_run_override"] is True
    assert apply_calls[0]["request"]["dry_run"] is True
    assert apply_calls[0]["request"]["actions"][0]["type"] == "calendar_event.create"
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["actions"][0]["status"] == "dry_run"


def test_chat_dry_run_does_not_write_apple_or_sqlite(monkeypatch):
    _patch_chat_context(monkeypatch)
    log_calls = []

    monkeypatch.setattr("nudge.commands.chat.load_config", lambda path=None: PUBLIC_CONFIG)
    monkeypatch.setattr(
        "nudge.commands.chat.call_llm",
        lambda system, prompt, task="default": _chat_response_with(
            {
                "type": "reminder",
                "name": "提交日报",
                "due_date": "2026-06-08 18:00",
            }
        ),
    )
    monkeypatch.setattr(
        "nudge.commands.agent.execute_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not write Apple")),
    )
    monkeypatch.setattr("nudge.commands.agent.log_action", lambda **kwargs: log_calls.append(kwargs))

    result = CliRunner().invoke(
        cli,
        ["chat", "--dry-run", "--json", "提醒我提交日报"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["actions"][0]["type"] == "reminder.create"
    assert payload["actions"][0]["status"] == "dry_run"
    assert log_calls == []


def test_chat_json_dry_run_bad_action_returns_stable_error(monkeypatch):
    _patch_chat_context(monkeypatch)

    monkeypatch.setattr("nudge.commands.chat.load_config", lambda path=None: PUBLIC_CONFIG)
    monkeypatch.setattr(
        "nudge.commands.chat.call_llm",
        lambda system, prompt, task="default": _chat_response_with(
            {
                "type": "calendar_event",
                "summary": "坏时间",
                "start": "tomorrow morning",
            }
        ),
    )

    result = CliRunner().invoke(
        cli,
        ["chat", "--dry-run", "--json", "帮我安排坏时间"],
        prog_name="nudge",
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert payload["dry_run"] is True
    assert payload["errors"][0]["code"] == "AGENT_REQUEST_INVALID"
    assert "missing fields" in payload["errors"][0]["detail"]


def test_chat_real_write_without_interactive_confirmation_does_not_write(monkeypatch):
    _patch_chat_context(monkeypatch)
    log_calls = []

    monkeypatch.setattr("nudge.commands.chat.load_config", lambda path=None: PUBLIC_CONFIG)
    monkeypatch.setattr(
        "nudge.commands.chat.call_llm",
        lambda system, prompt, task="default": _chat_response_with(
            {
                "type": "reminder",
                "name": "提交日报",
                "due_date": "2026-06-08 18:00",
            }
        ),
    )
    monkeypatch.setattr(
        "nudge.commands.agent.execute_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unconfirmed chat must not write Apple")),
    )
    monkeypatch.setattr("nudge.commands.agent.log_action", lambda **kwargs: log_calls.append(kwargs))

    result = CliRunner().invoke(
        cli,
        ["chat", "--json", "提醒我提交日报"],
        prog_name="nudge",
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["confirmation_required"] is True
    assert payload["errors"][0]["code"] == "AGENT_CONFIRMATION_REQUIRED"
    assert log_calls == []
