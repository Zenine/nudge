"""Public-safe tests for agent-facing Apple action relay behavior."""

import json

import pytest

from click.testing import CliRunner

from nudge.cli import cli
from nudge.commands.agent import _normalize_action, apply_agent_request
from nudge.config import get_defaults


BASE_CONFIG = {
    "general": {"default_calendar": "Family", "default_reminder_list": "日常"},
    "llm": {"provider": "qwen"},
    "apple": {
        "calendar": {"backend": "native"},
        "reminders": {"backend": "native"},
        "clock": {"backend": "shortcuts", "shortcut_name": "Nudge Test Alarm"},
    },
}


def isolate_confirmation_secret(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "nudge.commands.agent.CONFIRMATION_SECRET_PATH",
        tmp_path / "agent_confirm_secret",
    )


def isolate_state_db(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.commands.agent.STATE_DIR", tmp_path)


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



def test_confirmation_secret_replaces_empty_crash_residue():
    from nudge.commands.agent import CONFIRMATION_SECRET_PATH, _confirmation_secret

    CONFIRMATION_SECRET_PATH.write_text("", encoding="utf-8")
    CONFIRMATION_SECRET_PATH.chmod(0o600)

    secret = _confirmation_secret()

    assert secret
    assert secret != b""
    assert secret == CONFIRMATION_SECRET_PATH.read_text(encoding="utf-8").strip().encode("utf-8")
    assert (CONFIRMATION_SECRET_PATH.stat().st_mode & 0o777) == 0o600

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


def test_agent_apply_dry_run_from_file_outputs_contract_without_writes(monkeypatch, tmp_path):
    request = {
        "request_id": "req-dry-run",
        "source": "unit-test-agent",
        "dry_run": True,
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "项目会",
                "start": "2026-04-26 14:00",
                "end": "2026-04-26 15:00",
                "target": {"calendar": "Family"},
            }
        ],
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not write Calendar")),
    )
    monkeypatch.setattr(
        "nudge.commands.agent.log_action",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not log")),
    )

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--file", str(request_path), "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["request_id"] == "req-dry-run"
    assert payload["source"] == "unit-test-agent"
    assert payload["dry_run"] is True
    assert payload["total"] == 1
    assert payload["succeeded"] == 0
    assert payload["actions"][0] == {
        "index": 1,
        "type": "calendar_event.create",
        "status": "dry_run",
        "summary": "项目会",
        "scheduled_at": "2026-04-26 14:00",
        "target": {"kind": "Calendar", "name": "Family"},
    }
    assert payload["failures"] == []
    assert payload["errors"] == []


def test_agent_normalize_calendar_defaults_to_personal_calendar_without_config():
    normalized = _normalize_action(
        {
            "type": "calendar_event.create",
            "summary": "项目会",
            "start": "2026-05-12 14:00",
            "end": "2026-05-12 15:00",
        },
        {},
    )

    assert normalized["defaults"] == {"default_calendar": "Personal"}
    assert normalized["target"] == {"kind": "Calendar", "name": "Personal"}


def test_agent_normalize_reminder_defaults_to_daily_list_without_config():
    normalized = _normalize_action(
        {
            "type": "reminder.create",
            "name": "整理资料",
            "due_date": "2026-05-12 19:00",
        },
        {},
    )

    assert normalized["defaults"] == {"default_reminder_list": "Tasks"}
    assert normalized["target"] == {"kind": "Reminder list", "name": "Tasks"}


def test_agent_apply_reminder_summary_drops_duplicate_due_date(monkeypatch):
    request = {
        "request_id": "req-reminder-title",
        "source": "planner-agent",
        "dry_run": True,
        "actions": [
            {
                "type": "reminder.create",
                "name": "[Nudge Liver W1] 站立 / 走动 10 分钟 2026-04-27 10:00",
                "due_date": "2026-04-27 10:00",
                "target": {"list": "日常"},
            }
        ],
    }

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["actions"][0]["summary"] == "[Nudge Liver W1] 站立 / 走动 10 分钟"
    assert payload["actions"][0]["scheduled_at"] == "2026-04-27 10:00"


def test_agent_apply_writes_all_supported_action_types_and_logs_successes(monkeypatch):
    request = {
        "request_id": "req-write",
        "source": "planner-agent",
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "项目会",
                "start": "2026-04-26 14:00",
                "end": "2026-04-26 15:00",
                "target": {"calendar": "Family"},
                "notes": "由 agent 生成",
            },
            {
                "type": "reminder.create",
                "name": "买菜",
                "due_date": "2026-04-26 18:00",
                "target": {"list": "日常"},
            },
            {
                "type": "alarm.create",
                "time": "07:00",
                "label": "晨起称重",
            },
        ],
    }
    calendar_calls = []
    reminder_calls = []
    alarm_calls = []
    log_calls = []

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: calendar_calls.append(kwargs) or (True, "uid-123"),
    )
    monkeypatch.setattr(
        "nudge.apple.adapters.create_reminder",
        lambda **kwargs: reminder_calls.append(kwargs) or (True, "reminder-object"),
    )
    monkeypatch.setattr(
        "nudge.apple.adapters.create_alarm",
        lambda time, label, shortcut_name: alarm_calls.append((time, label, shortcut_name)) or (True, f"Clock::{shortcut_name}::{time}::{label}"),
    )
    monkeypatch.setattr("nudge.commands.agent.log_action", lambda **kwargs: log_calls.append(kwargs))

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["request_id"] == "req-write"
    assert payload["succeeded"] == 3
    assert payload["actions"][0]["external_id"] == "Family::uid-123"
    assert payload["actions"][1]["external_id"].startswith("nudge://reminder/")
    assert payload["actions"][2]["external_id"] == "Clock::Nudge Test Alarm::07:00::晨起称重"
    assert calendar_calls[0]["calendar_name"] == "Family"
    assert reminder_calls[0]["list_name"] == "日常"
    assert alarm_calls == [("07:00", "晨起称重", "Nudge Test Alarm")]
    assert log_calls == [
        {
            "action_type": "calendar_event",
            "summary": "项目会",
            "scheduled_at": "2026-04-26 14:00",
            "external_id": "Family::uid-123",
            "reminder_list": None,
        },
        {
            "action_type": "reminder",
            "summary": "买菜",
            "scheduled_at": "2026-04-26 18:00",
            "external_id": payload["actions"][1]["external_id"],
            "reminder_list": "日常",
        },
        {
            "action_type": "alarm",
            "summary": "晨起称重",
            "scheduled_at": "07:00",
            "external_id": "Clock::Nudge Test Alarm::07:00::晨起称重",
            "reminder_list": None,
        },
    ]


def test_agent_apply_config_state_dir_writes_action_log_to_configured_state_dir(monkeypatch, tmp_path):
    """`nudge agent apply --config` should use that config's [state].dir."""
    from nudge.state import get_actions

    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)

    default_state_dir = tmp_path / "default-state"
    configured_state_dir = tmp_path / "configured-state"
    config_path = tmp_path / "custom.toml"
    config = {
        **BASE_CONFIG,
        "state": {"dir": str(configured_state_dir)},
    }
    request = {
        "request_id": "req-config-state",
        "source": "unit-test-agent",
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "项目会",
                "start": "2026-04-26 14:00",
                "end": "2026-04-26 15:00",
                "target": {"calendar": "Family"},
            }
        ],
    }

    monkeypatch.setattr("nudge.state.STATE_DIR", default_state_dir)
    monkeypatch.setattr("nudge.state.DB_PATH", default_state_dir / "nudge.db")
    monkeypatch.setattr("nudge.commands.agent.STATE_DIR", default_state_dir)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: config)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (True, "uid-config-state"),
    )

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--config", str(config_path), "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert not (default_state_dir / "nudge.db").exists()
    assert (configured_state_dir / "nudge.db").exists()
    actions = get_actions()
    assert [action["summary"] for action in actions] == ["项目会"]


def test_agent_apply_writes_note_create_and_logs_success(monkeypatch):
    request = {
        "request_id": "req-note",
        "source": "planner-agent",
        "actions": [
            {
                "type": "note.create",
                "title": "本周计划",
                "body": "计划正文",
                "target": {"folder": "Nudge"},
            }
        ],
    }
    note_calls = []
    log_calls = []

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_note",
        lambda **kwargs: note_calls.append(kwargs) or (True, "本周计划"),
    )
    monkeypatch.setattr("nudge.commands.agent.log_action", lambda **kwargs: log_calls.append(kwargs))

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["succeeded"] == 1
    assert payload["actions"][0] == {
        "index": 1,
        "type": "note.create",
        "status": "succeeded",
        "summary": "本周计划",
        "scheduled_at": None,
        "target": {"kind": "Notes folder", "name": "Nudge"},
    }
    assert note_calls == [
        {
            "title": "本周计划",
            "body": "计划正文",
            "folder_name": "Nudge",
        }
    ]
    assert log_calls == [
        {
            "action_type": "note",
            "summary": "本周计划",
            "scheduled_at": None,
            "external_id": None,
            "reminder_list": None,
        }
    ]


def test_agent_apply_note_create_requires_title_and_body(monkeypatch):
    request = {
        "request_id": "req-note-invalid",
        "source": "planner-agent",
        "actions": [{"type": "note.create", "title": "缺正文"}],
    }

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_note",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("invalid note must not write")),
    )

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["errors"][0]["code"] == "AGENT_REQUEST_INVALID"
    assert "note.create missing fields: body" in payload["errors"][0]["detail"]


def test_agent_apply_partial_failure_returns_nonzero_parseable_json(monkeypatch):
    request = {
        "request_id": "req-partial",
        "source": "planner-agent",
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "成功会议",
                "start": "2026-04-26 14:00",
                "end": "2026-04-26 15:00",
                "target": {"calendar": "Family"},
            },
            {
                "type": "calendar_event.create",
                "summary": "失败会议",
                "start": "2026-04-26 16:00",
                "end": "2026-04-26 17:00",
                "target": {"calendar": "Missing"},
            },
        ],
    }

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (
            (True, "uid-ok")
            if kwargs["summary"] == "成功会议"
            else (False, 'Can’t get calendar "Missing".')
        ),
    )
    monkeypatch.setattr("nudge.commands.agent.log_action", lambda **kwargs: None)

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["succeeded"] == 1
    assert payload["actions"][0]["status"] == "succeeded"
    assert payload["actions"][1]["status"] == "failed"
    assert payload["failures"] == [
        {
            "index": 2,
            "summary": "失败会议",
            "error_code": "APPLE_TARGET_NOT_FOUND",
            "error": "目标 Calendar 不存在：Missing",
        }
    ]
    assert payload["errors"][0]["code"] == "APPLE_TARGET_NOT_FOUND"


def test_agent_apply_invalid_request_returns_json_error(monkeypatch):
    request = {"request_id": "req-invalid", "source": "bad-agent", "actions": [{"type": "calendar_event.create"}]}

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("invalid request must not write")),
    )

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["request_id"] == "req-invalid"
    assert payload["errors"][0]["code"] == "AGENT_REQUEST_INVALID"
    assert "missing fields" in payload["errors"][0]["detail"]


def test_agent_apply_invalid_datetime_returns_json_error_without_throwing(monkeypatch):
    request = {
        "request_id": "req-invalid-date",
        "source": "planner-agent",
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "坏时间会议",
                "start": "tomorrow 9am",
                "end": "tomorrow 10am",
                "target": {"calendar": "Family"},
            }
        ],
    }

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("invalid date must not write")),
    )

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["request_id"] == "req-invalid-date"
    assert payload["errors"][0]["code"] == "AGENT_REQUEST_INVALID"
    assert "Invalid start time format" in payload["errors"][0]["detail"]


def test_agent_apply_dry_run_confirmation_returns_token_and_no_writes(monkeypatch):
    request = {
        "request_id": "req-confirm",
        "source": "planner-agent",
        "dry_run": True,
        "require_confirmation": True,
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "需要确认的会议",
                "start": "2026-04-26 14:00",
                "end": "2026-04-26 15:00",
                "target": {"calendar": "Family"},
            }
        ],
    }

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("confirmation dry-run must not write")),
    )

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["confirmation_required"] is True
    assert payload["dry_run_token"].startswith("nudge.agent.confirm.v1:")


def test_agent_apply_plan_driven_requires_text_plan_confirmation_before_dry_run(monkeypatch):
    request = {
        "request_id": "req-plan-needs-text-confirm",
        "source": "planner-agent",
        "plan_driven": True,
        "dry_run": True,
        "require_confirmation": True,
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "计划型会议",
                "start": "2026-04-26 14:00",
                "end": "2026-04-26 15:00",
                "target": {"calendar": "Family"},
            }
        ],
    }

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("missing text confirmation must block writes")),
    )
    monkeypatch.setattr(
        "nudge.commands.agent.log_action",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("missing text confirmation must not log")),
    )

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["dry_run"] is True
    assert payload["plan_driven"] is True
    assert payload["text_plan_confirmed"] is False
    assert "dry_run_token" not in payload
    assert payload["errors"][0]["code"] == "AGENT_TEXT_PLAN_CONFIRMATION_REQUIRED"


def test_agent_apply_plan_driven_text_confirmation_binds_dry_run_token(monkeypatch):
    dry_run_request = {
        "request_id": "req-plan-confirmed",
        "source": "planner-agent",
        "plan_driven": True,
        "text_plan_confirmed": True,
        "text_plan_ref": "docs/plans/week-2-plan.md",
        "dry_run": True,
        "require_confirmation": True,
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "确认文本计划后的会议",
                "start": "2026-04-26 14:00",
                "end": "2026-04-26 15:00",
                "target": {"calendar": "Family"},
            }
        ],
    }
    changed_write_request = {
        **dry_run_request,
        "dry_run": False,
        "text_plan_ref": "docs/plans/changed-plan.md",
    }
    calendar_calls = []

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: calendar_calls.append(kwargs) or (True, "uid-plan"),
    )
    monkeypatch.setattr("nudge.commands.agent.log_action", lambda **kwargs: None)

    dry_result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(dry_run_request, ensure_ascii=False),
        prog_name="nudge",
    )
    assert dry_result.exit_code == 0, dry_result.output
    dry_payload = json.loads(dry_result.output)
    assert dry_payload["ok"] is True
    assert dry_payload["plan_driven"] is True
    assert dry_payload["text_plan_confirmed"] is True
    assert dry_payload["text_plan_ref"] == "docs/plans/week-2-plan.md"

    changed_write_request["dry_run_token"] = dry_payload["dry_run_token"]
    changed_result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(changed_write_request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert changed_result.exit_code == 1
    changed_payload = json.loads(changed_result.output)
    assert changed_payload["errors"][0]["code"] == "AGENT_CONFIRMATION_INVALID"
    assert calendar_calls == []

    write_request = {**dry_run_request, "dry_run": False, "dry_run_token": dry_payload["dry_run_token"]}
    write_result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(write_request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert write_result.exit_code == 0, write_result.output
    payload = json.loads(write_result.output)
    assert payload["ok"] is True
    assert payload["plan_driven"] is True
    assert payload["text_plan_confirmed"] is True
    assert payload["actions"][0]["external_id"] == "Family::uid-plan"


def test_agent_apply_requires_matching_dry_run_token_before_real_write(monkeypatch):
    dry_run_request = {
        "request_id": "req-confirm-write",
        "source": "planner-agent",
        "dry_run": True,
        "require_confirmation": True,
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "确认后写入会议",
                "start": "2026-04-26 14:00",
                "end": "2026-04-26 15:00",
                "target": {"calendar": "Family"},
            }
        ],
    }
    write_request = {**dry_run_request, "dry_run": False}
    calendar_calls = []
    log_calls = []

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: calendar_calls.append(kwargs) or (True, "uid-confirm"),
    )
    monkeypatch.setattr("nudge.commands.agent.log_action", lambda **kwargs: log_calls.append(kwargs))

    dry_result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(dry_run_request, ensure_ascii=False),
        prog_name="nudge",
    )
    token = json.loads(dry_result.output)["dry_run_token"]
    write_request["dry_run_token"] = token

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(write_request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is False
    assert payload["confirmation_required"] is True
    assert payload["actions"][0]["external_id"] == "Family::uid-confirm"
    assert calendar_calls[0]["summary"] == "确认后写入会议"
    assert log_calls[0]["external_id"] == "Family::uid-confirm"


def test_agent_apply_missing_confirmation_token_blocks_real_write(monkeypatch):
    request = {
        "request_id": "req-missing-token",
        "source": "planner-agent",
        "require_confirmation": True,
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "不能直接写入",
                "start": "2026-04-26 14:00",
                "end": "2026-04-26 15:00",
                "target": {"calendar": "Family"},
            }
        ],
    }

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("missing token must block writes")),
    )
    monkeypatch.setattr(
        "nudge.commands.agent.log_action",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("missing token must not log")),
    )

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "AGENT_CONFIRMATION_REQUIRED"


def test_agent_apply_changed_request_rejects_old_dry_run_token(monkeypatch):
    dry_run_request = {
        "request_id": "req-token-mismatch",
        "source": "planner-agent",
        "dry_run": True,
        "require_confirmation": True,
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "原始会议",
                "start": "2026-04-26 14:00",
                "end": "2026-04-26 15:00",
                "target": {"calendar": "Family"},
            }
        ],
    }
    changed_write_request = {
        **dry_run_request,
        "dry_run": False,
        "actions": [{**dry_run_request["actions"][0], "summary": "被篡改会议"}],
    }

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("mismatched token must block writes")),
    )

    dry_result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(dry_run_request, ensure_ascii=False),
        prog_name="nudge",
    )
    changed_write_request["dry_run_token"] = json.loads(dry_result.output)["dry_run_token"]

    result = CliRunner().invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(changed_write_request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "AGENT_CONFIRMATION_INVALID"


def test_agent_apply_repeated_confirmation_dry_run_returns_stable_token(monkeypatch):
    request = {
        "request_id": "req-stable-token",
        "source": "planner-agent",
        "dry_run": True,
        "require_confirmation": True,
        "actions": [
            {
                "type": "calendar_event.create",
                "summary": "稳定 token 会议",
                "start": "2026-04-26 14:00",
                "end": "2026-04-26 15:00",
                "target": {"calendar": "Family"},
            }
        ],
    }

    monkeypatch.setattr("nudge.cli.load_config", lambda: BASE_CONFIG)
    monkeypatch.setattr("nudge.commands.agent.load_config", lambda p=None: BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.apple.adapters.create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("dry-run token generation must not write")),
    )

    runner = CliRunner()
    first = runner.invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )
    second = runner.invoke(
        cli,
        ["agent", "apply", "--json"],
        input=json.dumps(request, ensure_ascii=False),
        prog_name="nudge",
    )

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    first_payload = json.loads(first.output)
    second_payload = json.loads(second.output)
    assert first_payload["dry_run_token"] == second_payload["dry_run_token"]
    assert first_payload["confirmation_required"] is True
    assert second_payload["confirmation_required"] is True


def test_agent_status_command_updates_all_supported_statuses_to_sqlite(tmp_path):
    from nudge.state import get_action, log_action

    action_id = log_action(
        action_type="calendar_event",
        summary="站立训练",
        scheduled_at="2026-04-27 07:00",
    )

    previous_status = "created"
    for status in ("done", "skipped", "partial", "deferred", "blocked"):
        request = {
            "action_id": action_id,
            "status": status,
            "source": "unit-test",
            "note": f"{status} note",
            "reason": "no_time",
            "next_action": "keep",
            "feedback": {"source_hint": "cli"},
        }
        request_file = tmp_path / f"status-{status}.json"
        request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")

        result = CliRunner().invoke(
            cli,
            ["agent", "status", "--file", str(request_file)],
            prog_name="nudge",
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["action"]["status"] == status
        assert payload["action"]["previous_status"] == previous_status
        record = get_action(action_id)
        assert record is not None
        assert record["status"] == status
        assert record["feedback"] is not None
        previous_status = status


def test_agent_status_dry_run_does_not_persist(tmp_path):
    from nudge.state import get_action, log_action

    action_id = log_action(
        action_type="calendar_event",
        summary="冥想",
        scheduled_at="2026-04-27 21:00",
    )
    request = {
        "action_id": action_id,
        "status": "skipped",
        "note": "明天再做",
        "reason": "low_energy",
    }
    request_file = tmp_path / "status-dry-run.json"
    request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        ["agent", "status", "--dry-run", "--file", str(request_file)],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["updated"] is None
    assert payload["feedback"]["note"] == "明天再做"
    assert payload["feedback"]["schema_version"] == "nudge.feedback.v1"
    assert payload["feedback"]["source_type"] == "agent"
    assert payload["feedback"]["channel"] == "agent.status"

    persisted = get_action(action_id)
    assert persisted is not None
    assert persisted["status"] == "created"
    assert persisted["feedback"] is None


@pytest.mark.parametrize(
    "request_payload, expected_code",
    [
        ({}, "AGENT_STATUS_INVALID"),
        ({"status": "done"}, "AGENT_STATUS_INVALID"),
        ({"action_id": "not-exist", "status": "done"}, "AGENT_ACTION_NOT_FOUND"),
        ({"action_id": "__ACTION_ID__", "status": "done", "reason": "bad"}, "AGENT_STATUS_INVALID"),
        ({"action_id": "__ACTION_ID__", "status": "done", "next_action": "invalid"}, "AGENT_STATUS_INVALID"),
        ({"action_id": "__ACTION_ID__", "status": "unknown"}, "AGENT_STATUS_INVALID"),
    ],
)
def test_agent_status_invalid_payload_cases(request_payload, expected_code, tmp_path):
    from nudge.state import log_action

    existing_action_id = log_action(
        action_type="calendar_event",
        summary="回写异常测试",
        scheduled_at="2026-04-27 08:00",
    )
    fixed = json.loads(
        json.dumps(request_payload, ensure_ascii=False).replace("__ACTION_ID__", existing_action_id)
    )
    status_file = tmp_path / "status-invalid.json"
    status_file.write_text(json.dumps(fixed, ensure_ascii=False), encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        ["agent", "status", "--file", str(status_file)],
        prog_name="nudge",
    )

    if expected_code == "AGENT_ACTION_NOT_FOUND":
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["errors"][0]["code"] == "AGENT_ACTION_NOT_FOUND"
        return

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["errors"][0]["code"] == expected_code
