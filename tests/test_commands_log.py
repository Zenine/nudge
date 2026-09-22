"""Tests for fast check-in / log commands."""

import json

from click.testing import CliRunner

from nudge.cli import cli


def _fake_get_actions(actions):
    def fake_get_actions(status=None):
        if status:
            return [action for action in actions if action["status"] == status]
        return actions

    return fake_get_actions


def _expected_feedback(source, channel, note, **extra):
    return {
        "schema_version": "nudge.feedback.v1",
        "source": source,
        "channel": channel,
        "source_type": "subjective",
        "note": note,
        **extra,
    }


def test_log_default_reminder_list_falls_back_to_current_default_when_setting_missing(monkeypatch):
    import nudge.commands.log as log

    monkeypatch.setattr(log, "load_config", lambda p=None: {"general": {}})

    assert log._default_reminder_list() == "Tasks"


def test_log_done_marks_most_recent_created_action(monkeypatch):
    from nudge.commands.log import log_command

    calls = []

    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {
                "id": "recent123",
                "summary": "阅读 30 分钟",
                "status": "created",
                "scheduled_at": "2026-04-26 21:00",
            }
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.complete_action",
        lambda action_id, feedback=None: calls.append((action_id, feedback)),
    )

    result = CliRunner().invoke(log_command, ["done"])

    assert result.exit_code == 0, result.output
    assert calls == [("recent123", _expected_feedback("nudge log", "cli.log", ""))]
    assert "✓ done" in result.output
    assert "阅读 30 分钟" in result.output


def test_log_done_completes_matching_apple_reminder(monkeypatch):
    from nudge.commands.log import log_command

    state_calls = []
    apple_calls = []

    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {
                "id": "r1",
                "type": "reminder",
                "summary": "[Nudge] 喝水",
                "status": "created",
                "scheduled_at": "2026-05-09 09:00",
            }
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.complete_action",
        lambda action_id, feedback=None: state_calls.append((action_id, feedback)),
    )
    monkeypatch.setattr(
        "nudge.commands.log.load_config",
        lambda p=None: {"general": {"default_reminder_list": "日常"}},
    )
    monkeypatch.setattr(
        "nudge.commands.log.complete_reminder",
        lambda title, list_name, due_date=None: apple_calls.append((title, list_name, due_date)) or (True, "matched=1 changed=1"),
    )

    result = CliRunner().invoke(log_command, ["done", "--id", "r1", "--json"])

    payload = json.loads(result.output)
    assert result.exit_code == 0, result.output
    assert state_calls == [("r1", _expected_feedback("nudge log", "cli.log", ""))]
    assert apple_calls == [("[Nudge] 喝水", "日常", "2026-05-09 09:00")]
    assert payload["apple_reminder"] == {
        "attempted": True,
        "ok": True,
        "list": "日常",
        "title": "[Nudge] 喝水",
        "message": "matched=1 changed=1",
    }


def test_log_done_reports_apple_sync_failure_without_failing_local_log(monkeypatch):
    from nudge.commands.log import log_command

    state_calls = []

    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {
                "id": "r1",
                "type": "reminder",
                "summary": "[Nudge] 喝水",
                "status": "created",
                "scheduled_at": "2026-05-09 09:00",
            }
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.complete_action",
        lambda action_id, feedback=None: state_calls.append((action_id, feedback)),
    )
    monkeypatch.setattr(
        "nudge.commands.log.load_config",
        lambda p=None: (_ for _ in ()).throw(FileNotFoundError("missing config")),
    )
    monkeypatch.setattr(
        "nudge.commands.log.complete_reminder",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Apple sync should not run without config")),
    )

    result = CliRunner().invoke(log_command, ["done", "--id", "r1", "--json"])

    payload = json.loads(result.output)
    assert result.exit_code == 0, result.output
    assert state_calls == [("r1", _expected_feedback("nudge log", "cli.log", ""))]
    assert payload["apple_reminder"]["attempted"] is True
    assert payload["apple_reminder"]["ok"] is False
    assert "missing config" in payload["apple_reminder"]["message"]


def test_log_skipped_can_select_action_by_match(monkeypatch):
    from nudge.commands.log import log_command

    calls = []

    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {"id": "a1", "summary": "阅读 30 分钟", "status": "created", "scheduled_at": ""},
            {"id": "a2", "summary": "跑步", "status": "created", "scheduled_at": ""},
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.skip_action",
        lambda action_id, feedback=None: calls.append((action_id, feedback)),
    )

    result = CliRunner().invoke(log_command, ["skipped", "下雨", "--match", "跑步"])

    assert result.exit_code == 0, result.output
    assert calls == [("a2", _expected_feedback("nudge log", "cli.log", "下雨"))]
    assert "✗ skipped" in result.output
    assert "跑步" in result.output


def test_log_partial_records_note_by_id(monkeypatch):
    from nudge.commands.log import log_command

    calls = []

    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {"id": "a1", "summary": "阅读 30 分钟", "status": "created", "scheduled_at": ""},
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.partial_action",
        lambda action_id, feedback=None: calls.append((action_id, feedback)),
    )

    result = CliRunner().invoke(log_command, ["partial", "只做了一半", "--id", "a1"])

    assert result.exit_code == 0, result.output
    assert calls == [("a1", _expected_feedback("nudge log", "cli.log", "只做了一半"))]
    assert "◐ partial" in result.output
    assert "只做了一半" in result.output


def test_log_deferred_records_reason_and_next_action(monkeypatch):
    from nudge.commands.log import log_command

    calls = []

    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {"id": "a1", "summary": "整理发票", "status": "created", "scheduled_at": ""},
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.update_action_status",
        lambda action_id, status, feedback=None: calls.append((action_id, status, feedback)),
    )

    result = CliRunner().invoke(
        log_command,
        [
            "deferred",
            "今晚没时间",
            "--id",
            "a1",
            "--reason",
            "no_time",
            "--next-action",
            "reschedule",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "a1",
            "deferred",
            _expected_feedback(
                "nudge log",
                "cli.log",
                "今晚没时间",
                reason="no_time",
                next_action="reschedule",
            ),
        )
    ]
    assert "↷ deferred" in result.output
    assert "reason: no_time" in result.output
    assert "next: reschedule" in result.output


def test_log_blocked_records_structured_feedback(monkeypatch):
    from nudge.commands.log import log_command

    calls = []

    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {"id": "a1", "summary": "等对方确认合同", "status": "created", "scheduled_at": ""},
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.update_action_status",
        lambda action_id, status, feedback=None: calls.append((action_id, status, feedback)),
    )

    result = CliRunner().invoke(
        log_command,
        ["blocked", "还在等回复", "--reason", "waiting_on_other", "--next-action", "keep"],
    )

    assert result.exit_code == 0, result.output
    assert calls[0][1] == "blocked"
    assert calls[0][2]["reason"] == "waiting_on_other"
    assert calls[0][2]["next_action"] == "keep"
    assert "⛔ blocked" in result.output


def test_check_in_alias_uses_same_behavior(monkeypatch):
    from nudge.commands.log import check_in_command

    calls = []

    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {"id": "a1", "summary": "写周报", "status": "created", "scheduled_at": ""},
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.complete_action",
        lambda action_id, feedback=None: calls.append((action_id, feedback)),
    )

    result = CliRunner().invoke(check_in_command, ["done"])

    assert result.exit_code == 0, result.output
    assert calls == [("a1", _expected_feedback("nudge check-in", "cli.check-in", ""))]
    assert "写周报" in result.output


def test_root_cli_lists_log_and_check_in_commands(monkeypatch):
    monkeypatch.setattr("nudge.cli.load_config", lambda: {"llm": {"provider": "qwen"}})

    result = CliRunner().invoke(cli, ["--help"], prog_name="nudge")

    assert result.exit_code == 0
    assert "log" in result.output
    assert "check-in" in result.output


def test_log_defaults_to_latest_pending_action_across_created_and_pending(monkeypatch):
    from nudge.commands.log import log_command

    calls = []
    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {"id": "pending-newer", "summary": "最新 pending", "status": "pending", "scheduled_at": ""},
            {"id": "created-older", "summary": "较早 created", "status": "created", "scheduled_at": ""},
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.complete_action",
        lambda action_id, feedback=None: calls.append((action_id, feedback)),
    )

    result = CliRunner().invoke(log_command, ["done"])

    assert result.exit_code == 0, result.output
    assert calls[0][0] == "pending-newer"
    assert "最新 pending" in result.output


def test_log_parse_uses_llm_result_to_select_and_complete_action(monkeypatch):
    from nudge.commands.log import log_command

    calls = []
    raw_text = "阅读完成了，读了 30 分钟，体感 7 分"
    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {"id": "a1", "summary": "跑步", "status": "created", "scheduled_at": ""},
            {"id": "a2", "summary": "阅读 30 分钟", "status": "created", "scheduled_at": ""},
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.parse_check_in_feedback",
        lambda text: {
            "status": "done",
            "match": "阅读",
            "note": "读完第一章",
            "metrics": {"minutes": 30, "effort": 7},
        },
    )
    monkeypatch.setattr(
        "nudge.commands.log.complete_action",
        lambda action_id, feedback=None: calls.append((action_id, feedback)),
    )

    result = CliRunner().invoke(log_command, ["parse", raw_text])

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "a2",
            _expected_feedback(
                "nudge log parse",
                "cli.log.parse",
                "读完第一章",
                raw_text=raw_text,
                metrics={"minutes": 30, "effort": 7},
            ),
        )
    ]
    assert "✓ done" in result.output
    assert "阅读 30 分钟" in result.output
    assert "effort=7" in result.output


def test_log_parse_accepts_deferred_reason_and_next_action(monkeypatch):
    from nudge.commands.log import log_command

    calls = []
    raw_text = "今晚太累了，阅读延期到明天"
    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {"id": "a1", "summary": "阅读 30 分钟", "status": "created", "scheduled_at": ""},
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.parse_check_in_feedback",
        lambda text: {
            "status": "deferred",
            "match": "阅读",
            "note": "延期到明天",
            "reason": "low_energy",
            "next_action": "reschedule",
            "metrics": {},
        },
    )
    monkeypatch.setattr(
        "nudge.commands.log.update_action_status",
        lambda action_id, status, feedback=None: calls.append((action_id, status, feedback)),
    )

    result = CliRunner().invoke(log_command, ["parse", raw_text])

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "a1",
            "deferred",
            _expected_feedback(
                "nudge log parse",
                "cli.log.parse",
                "延期到明天",
                raw_text=raw_text,
                reason="low_energy",
                next_action="reschedule",
            ),
        )
    ]
    assert "↷ deferred" in result.output


def test_log_parse_json_dry_run_does_not_update_action(monkeypatch):
    from nudge.commands.log import log_command

    calls = []
    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {"id": "a1", "summary": "读书", "status": "created", "scheduled_at": "2026-04-26 21:00"},
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.parse_check_in_feedback",
        lambda text: {"status": "partial", "note": "只读了一半", "metrics": {}, "match": None},
    )
    monkeypatch.setattr(
        "nudge.commands.log.partial_action",
        lambda action_id, feedback=None: calls.append((action_id, feedback)),
    )

    result = CliRunner().invoke(log_command, ["parse", "读书只读了一半，明天继续", "--dry-run", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["parsed"]["status"] == "partial"
    assert payload["action"]["id"] == "a1"
    assert calls == []


def test_log_parse_json_reports_invalid_llm_status(monkeypatch):
    from nudge.commands.log import log_command

    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {"id": "a1", "summary": "读书", "status": "created", "scheduled_at": ""},
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.parse_check_in_feedback",
        lambda text: {"status": "finished", "note": "done", "metrics": {}, "match": None},
    )

    result = CliRunner().invoke(log_command, ["parse", "读完了", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "CHECK_IN_PARSE_INVALID"


def test_log_parse_json_reports_missing_pending_action(monkeypatch):
    from nudge.commands.log import log_command

    monkeypatch.setattr("nudge.commands.log.get_actions", _fake_get_actions([]))
    monkeypatch.setattr(
        "nudge.commands.log.parse_check_in_feedback",
        lambda text: {"status": "done", "note": "完成了", "metrics": {}, "match": None},
    )

    result = CliRunner().invoke(log_command, ["parse", "完成了", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "CHECK_IN_ACTION_NOT_FOUND"


def test_log_can_update_existing_blocked_action_by_id(monkeypatch):
    from nudge.commands.log import log_command

    calls = []
    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {"id": "block1", "summary": "等医生回复", "status": "blocked", "scheduled_at": "2026-04-27 09:00"},
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.update_action_status",
        lambda action_id, status, feedback=None: calls.append((action_id, status, feedback)),
    )

    result = CliRunner().invoke(
        log_command,
        ["blocked", "继续等待", "--id", "block1", "--reason", "waiting_on_other", "--next-action", "keep"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "block1",
            "blocked",
            _expected_feedback(
                "nudge log",
                "cli.log",
                "继续等待",
                reason="waiting_on_other",
                next_action="keep",
            ),
        )
    ]
    assert "等医生回复" in result.output


def test_log_feedback_uses_shared_schema(monkeypatch):
    from nudge.commands.log import log_command
    from nudge.feedback import FEEDBACK_SCHEMA_VERSION

    calls = []
    monkeypatch.setattr(
        "nudge.commands.log.get_actions",
        _fake_get_actions([
            {"id": "a1", "summary": "阅读 30 分钟", "status": "created", "scheduled_at": ""},
        ]),
    )
    monkeypatch.setattr(
        "nudge.commands.log.complete_action",
        lambda action_id, feedback=None: calls.append((action_id, feedback)),
    )

    result = CliRunner().invoke(log_command, ["done", "读完了", "--id", "a1"])

    assert result.exit_code == 0, result.output
    feedback = calls[0][1]
    assert feedback["schema_version"] == FEEDBACK_SCHEMA_VERSION
    assert feedback["source_type"] == "subjective"
    assert feedback["channel"] == "cli.log"
    assert feedback["source"] == "nudge log"
    assert feedback["note"] == "读完了"
