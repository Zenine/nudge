"""Tests for nudge.commands.doctor — local setup diagnostics."""

import json
from types import SimpleNamespace

from click.testing import CliRunner

from nudge.commands.doctor import doctor_command


BASE_CONFIG = {
    "general": {
        "default_calendar": "Family",
        "default_reminder_list": "日常",
    },
    "llm": {
        "provider": "qwen",
        "models": {
            "fast": "qwen-plus",
            "default": "qwen-plus",
            "strong": "qwen-plus",
        },
    },
    "family": {
        "dad": {
            "aliases": ["爸爸"],
            "calendar": "Dad",
            "reminder_list": "家庭",
        }
    },
}


def _patch_common(monkeypatch, config=None, provider=None):
    monkeypatch.setattr("nudge.commands.doctor.load_config", lambda p=None: config or BASE_CONFIG)
    monkeypatch.setattr(
        "nudge.commands.doctor.create_provider",
        lambda llm_config: provider or SimpleNamespace(api_key="secret", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )
    monkeypatch.setattr("nudge.apple.adapters.list_calendars", lambda: (True, ["Family", "Dad"]))
    monkeypatch.setattr("nudge.apple.adapters.list_reminder_lists", lambda: (True, ["日常", "家庭"]))
    monkeypatch.setattr("nudge.apple.adapters.probe_reminders_read", lambda list_name=None: (True, "readable"))
    monkeypatch.setattr("nudge.apple.adapters.list_note_folders", lambda: (True, ["Nudge", "健康"]))
    monkeypatch.setattr("nudge.commands.doctor.read_unread_count", lambda timeout=5: (True, 0))
    monkeypatch.setattr("nudge.apple.adapters.check_clock_shortcut", lambda shortcut_name: (True, f"Shortcut found: {shortcut_name}"))


def test_doctor_reports_passes_for_available_local_setup(monkeypatch):
    _patch_common(monkeypatch)

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 0
    assert "Nudge Doctor" in result.output
    assert "PASS" in result.output
    assert "LLM" in result.output
    assert "qwen" in result.output
    assert "Calendar" in result.output
    assert "Reminders" in result.output
    assert "Notes" in result.output
    assert "Mail" in result.output
    assert "Clock" in result.output
    assert "secret" not in result.output
    assert "backend=native" in result.output
    assert "backend=shortcuts" in result.output


def test_doctor_json_reports_summary_and_checks(monkeypatch):
    _patch_common(monkeypatch)

    result = CliRunner().invoke(doctor_command, ["--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["summary"] == {"PASS": 7, "WARN": 0, "FAIL": 0}
    assert payload["errors"] == []
    assert {check["name"] for check in payload["checks"]} == {
        "Config",
        "LLM",
        "Calendar",
        "Reminders",
        "Notes",
        "Mail",
        "Clock",
    }
    assert all(set(check) == {"status", "name", "message", "hint"} for check in payload["checks"])
    assert "secret" not in result.output


def test_doctor_json_failure_exits_nonzero_with_payload(monkeypatch):
    _patch_common(monkeypatch, provider=SimpleNamespace(api_key="", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"))

    result = CliRunner().invoke(doctor_command, ["--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["summary"]["FAIL"] == 1
    assert payload["errors"][0]["code"] == "DOCTOR_CHECK_FAILED"
    assert payload["errors"][0]["check"] == "LLM"
    assert "LLM API key" in payload["errors"][0]["message"]


def test_doctor_warns_when_clock_shortcut_is_missing(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr("nudge.apple.adapters.check_clock_shortcut", lambda shortcut_name: (False, f'Shortcut "{shortcut_name}" not found'))

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 0
    assert "WARN" in result.output
    assert "Clock" in result.output
    assert "Nudge Create Alarm" in result.output



def test_doctor_passes_when_clock_is_explicitly_disabled(monkeypatch):
    config = {**BASE_CONFIG, "apple": {"clock": {"backend": "disabled"}}}
    _patch_common(monkeypatch, config=config)

    result = CliRunner().invoke(doctor_command, ["--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    clock = next(check for check in payload["checks"] if check["name"] == "Clock")
    assert clock["status"] == "PASS"
    assert "backend=disabled" in clock["message"]
    assert payload["summary"] == {"PASS": 7, "WARN": 0, "FAIL": 0}

def test_doctor_fails_when_llm_api_key_is_missing(monkeypatch):
    _patch_common(monkeypatch, provider=SimpleNamespace(api_key="", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"))

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert "LLM API key" in result.output
    assert "secrets.yaml" in result.output
    assert "DASHSCOPE_API_KEY" in result.output


def test_doctor_fails_when_configured_calendar_is_missing(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr("nudge.apple.adapters.list_calendars", lambda: (True, ["Work"]))

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert "Calendar" in result.output
    assert "Family" in result.output
    assert "Dad" in result.output


def test_doctor_fails_when_configured_reminder_list_is_missing(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr("nudge.apple.adapters.list_reminder_lists", lambda: (True, ["Inbox"]))

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert "Reminders" in result.output
    assert "日常" in result.output
    assert "家庭" in result.output


def test_doctor_prints_macos_permission_hint_when_calendar_access_fails(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr("nudge.apple.adapters.list_calendars", lambda: (False, "Not authorized"))

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 1
    assert "Calendar" in result.output
    assert "Not authorized" in result.output
    assert "系统设置 → 隐私与安全性 → 日历" in result.output


def test_doctor_warns_when_mail_access_fails(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr("nudge.commands.doctor.read_unread_count", lambda timeout=5: (False, "Mail denied"))

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 0
    assert "WARN" in result.output
    assert "Mail" in result.output
    assert "Mail denied" in result.output
    assert "系统设置 → 隐私与安全性 → 自动化" in result.output


def test_doctor_warns_when_notes_access_fails(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr("nudge.apple.adapters.list_note_folders", lambda: (False, "Notes denied"))

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 0
    assert "WARN" in result.output
    assert "Notes" in result.output
    assert "Notes denied" in result.output
    assert "系统设置 → 隐私与安全性 → 自动化" in result.output


def test_doctor_warns_when_reminders_access_times_out(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr("nudge.apple.adapters.list_reminder_lists", lambda: (False, "AppleScript execution timed out"))

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 0
    assert "WARN" in result.output
    assert "Reminders" in result.output
    assert "AppleScript execution timed out" in result.output
    assert "系统设置 → 隐私与安全性 → 提醒事项" in result.output


def test_doctor_warns_when_reminder_lists_work_but_data_read_times_out(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr("nudge.apple.adapters.probe_reminders_read", lambda list_name=None: (False, "AppleScript execution timed out"))

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 0
    assert "WARN" in result.output
    assert "Reminders" in result.output
    assert "Lists readable; reminder data read not verified" in result.output
    assert "probe list=" in result.output
    assert "读取提醒事项数据超时" in result.output


def test_doctor_uses_configured_clock_shortcut_name(monkeypatch):
    config = {
        **BASE_CONFIG,
        "apple": {"clock": {"backend": "shortcuts", "shortcut_name": "Nudge Test Alarm"}},
    }
    _patch_common(monkeypatch, config=config)
    calls = []
    monkeypatch.setattr(
        "nudge.apple.adapters.check_clock_shortcut",
        lambda shortcut_name: calls.append(shortcut_name) or (True, f"Shortcut found: {shortcut_name}"),
    )

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 0, result.output
    assert calls == ["Nudge Test Alarm"]
    assert "backend=shortcuts" in result.output
    assert "Nudge Test Alarm" in result.output


def test_doctor_fails_explicitly_for_unsupported_calendar_backend(monkeypatch):
    config = {
        **BASE_CONFIG,
        "apple": {"calendar": {"backend": "ical"}},
    }
    _patch_common(monkeypatch, config=config)

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert "Calendar" in result.output
    assert "backend `ical`" in result.output
    assert "backend = \"native\"" in result.output


def test_doctor_warns_for_inline_llm_api_key_without_printing_key(monkeypatch):
    config = {
        **BASE_CONFIG,
        "llm": {
            **BASE_CONFIG["llm"],
            "api_key": "inline-secret-value",
        },
    }
    _patch_common(
        monkeypatch,
        config=config,
        provider=SimpleNamespace(
            api_key="inline-secret-value",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    )

    result = CliRunner().invoke(doctor_command, ["--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    llm_check = next(check for check in payload["checks"] if check["name"] == "LLM")
    assert llm_check["status"] == "WARN"
    assert "[llm].api_key" in llm_check["message"]
    assert "inline-secret-value" not in result.output
    assert payload["summary"] == {"PASS": 6, "WARN": 1, "FAIL": 0}


def test_doctor_fails_when_secrets_file_is_unreadable_without_printing_contents(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        "nudge.commands.doctor.diagnose_backup_secrets",
        lambda llm_config: SimpleNamespace(
            status="unreadable",
            message="secrets.yaml at configured path cannot be read: PermissionError",
            hint="请检查文件权限；doctor 不会显示文件内容或密钥值。",
        ),
    )

    result = CliRunner().invoke(doctor_command, ["--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    llm_check = next(check for check in payload["checks"] if check["name"] == "LLM")
    assert llm_check["status"] == "FAIL"
    assert "PermissionError" in llm_check["message"]
    assert "密钥值" in llm_check["hint"]
    assert "secret" not in result.output.lower().replace("secrets.yaml", "")


def test_doctor_fails_when_secrets_file_is_not_utf8_without_printing_contents(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        "nudge.commands.doctor.diagnose_backup_secrets",
        lambda llm_config: SimpleNamespace(
            status="decode_error",
            message="secrets.yaml at configured path is not valid UTF-8",
            hint="请确认文件使用 UTF-8 文本编码；doctor 不会显示文件内容或密钥值。",
        ),
    )

    result = CliRunner().invoke(doctor_command, [])

    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert "UTF-8" in result.output
    assert "密钥值" in result.output
    assert "api-key-value" not in result.output
