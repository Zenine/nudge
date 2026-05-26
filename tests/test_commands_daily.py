"""Tests for the daily sync command."""

from __future__ import annotations

import json

from click.testing import CliRunner

from nudge.cli import cli
from nudge.json_contract import versioned_payload


def _empty_reminder_payload(target_date, reminder_list, apply_changes):
    return versioned_payload(
        {
            "ok": True,
            "dry_run": not apply_changes,
            "date": target_date.isoformat(),
            "list": reminder_list,
            "checked": 0,
            "open": 0,
            "candidates": [],
            "updated": 0,
            "auto_skipped_after_sleep": [],
            "warnings": [],
            "errors": [],
        }
    )


def test_daily_sync_reports_docs_audit_and_creates_maintenance_action_on_apply(monkeypatch):
    import nudge.commands.daily as daily

    created_actions = []
    audit_roots = []
    monkeypatch.setattr(daily, "load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr(daily, "get_actions", lambda **kwargs: [])
    monkeypatch.setattr(daily, "sync_completed_for_date", _empty_reminder_payload)
    monkeypatch.setattr(
        daily,
        "audit_docs",
        lambda root: audit_roots.append(root)
        or {
            "ok": False,
            "summary": {"errors": 1, "warnings": 1, "suggestions": 0},
            "errors": [{"code": "DOCS_BROKEN_LINK", "message": "broken"}],
            "warnings": [{"code": "DOCS_STALE_PLAN", "message": "old"}],
            "suggestions": [],
        },
    )
    monkeypatch.setattr(
        daily,
        "log_action",
        lambda **kwargs: created_actions.append(kwargs) or "docs-action",
    )

    result = CliRunner().invoke(
        cli,
        ["daily", "sync", "--date", "2026-04-30", "--no-health", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["docs"]["ok"] is True
    assert payload["docs"]["report"]["ok"] is False
    assert payload["docs"]["attention_required"] is True
    assert payload["docs"]["action_created"] is True
    assert payload["docs"]["action_id"] == "docs-action"
    assert payload["docs"]["maintenance_policy"] == {
        "action_triggers": ["errors", "warnings"],
        "suggestions": "suggestions_only",
    }
    assert audit_roots == [daily.PROJECT_ROOT]
    assert created_actions == [
        {
            "action_type": "maintenance",
            "summary": "[Nudge Docs] 本周文档需要维护",
            "scheduled_at": "2026-04-30 09:00",
            "status": "created",
        }
    ]


def test_daily_sync_does_not_duplicate_open_docs_maintenance_action(monkeypatch):
    import nudge.commands.daily as daily

    monkeypatch.setattr(daily, "load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr(
        daily,
        "get_actions",
        lambda **kwargs: [
            {
                "id": "existing",
                "type": "maintenance",
                "summary": "[Nudge Docs] 本周文档需要维护",
                "scheduled_at": "2026-04-30 09:00",
                "status": "created",
            }
        ],
    )
    monkeypatch.setattr(daily, "sync_completed_for_date", _empty_reminder_payload)
    monkeypatch.setattr(
        daily,
        "audit_docs",
        lambda root: {
            "ok": False,
            "summary": {"errors": 1, "warnings": 0, "suggestions": 0},
            "errors": [{"code": "DOCS_BROKEN_LINK", "message": "broken"}],
            "warnings": [],
            "suggestions": [],
        },
    )
    monkeypatch.setattr(
        daily,
        "log_action",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("duplicate action must not be created")),
    )

    result = CliRunner().invoke(
        cli,
        ["daily", "sync", "--date", "2026-04-30", "--no-health", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["docs"]["action_created"] is False
    assert payload["docs"]["existing_action_id"] == "existing"


def test_daily_sync_uses_project_root_for_docs_audit_from_arbitrary_cwd(monkeypatch, tmp_path):
    import nudge.commands.daily as daily

    audit_roots = []
    monkeypatch.setattr(daily, "load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr(daily, "get_actions", lambda **kwargs: [])
    monkeypatch.setattr(daily, "sync_completed_for_date", _empty_reminder_payload)
    monkeypatch.setattr(
        daily,
        "audit_docs",
        lambda root: audit_roots.append(root)
        or {
            "ok": True,
            "summary": {"errors": 0, "warnings": 0, "suggestions": 0},
            "errors": [],
            "warnings": [],
            "suggestions": [],
        },
    )

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["daily", "sync", "--date", "2026-04-30", "--no-health", "--json"],
            prog_name="nudge",
        )

    assert result.exit_code == 0, result.output
    assert audit_roots == [daily.PROJECT_ROOT]


def test_daily_sync_creates_docs_maintenance_action_for_warning_only_report(monkeypatch):
    import nudge.commands.daily as daily

    created_actions = []
    monkeypatch.setattr(daily, "load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr(daily, "get_actions", lambda **kwargs: [])
    monkeypatch.setattr(daily, "sync_completed_for_date", _empty_reminder_payload)
    monkeypatch.setattr(
        daily,
        "audit_docs",
        lambda root: {
            "ok": True,
            "summary": {"errors": 0, "warnings": 1, "suggestions": 0},
            "errors": [],
            "warnings": [{"code": "DOCS_STALE_PLAN", "message": "old"}],
            "suggestions": [],
        },
    )
    monkeypatch.setattr(
        daily,
        "log_action",
        lambda **kwargs: created_actions.append(kwargs) or "docs-warning-action",
    )

    result = CliRunner().invoke(
        cli,
        ["daily", "sync", "--date", "2026-04-30", "--no-health", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["docs"]["report"]["ok"] is True
    assert payload["docs"]["attention_required"] is True
    assert payload["docs"]["action_created"] is True
    assert payload["docs"]["action_id"] == "docs-warning-action"
    assert created_actions == [
        {
            "action_type": "maintenance",
            "summary": "[Nudge Docs] 本周文档需要维护",
            "scheduled_at": "2026-04-30 09:00",
            "status": "created",
        }
    ]


def test_daily_sync_keeps_docs_suggestions_read_only(monkeypatch):
    import nudge.commands.daily as daily

    monkeypatch.setattr(daily, "load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr(daily, "get_actions", lambda **kwargs: [])
    monkeypatch.setattr(daily, "sync_completed_for_date", _empty_reminder_payload)
    monkeypatch.setattr(
        daily,
        "audit_docs",
        lambda root: {
            "ok": True,
            "summary": {"errors": 0, "warnings": 0, "suggestions": 1},
            "errors": [],
            "warnings": [],
            "suggestions": [{"code": "DOCS_LONG_ENTRYPOINT", "message": "long"}],
        },
    )
    monkeypatch.setattr(
        daily,
        "log_action",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("suggestions must not create actions")),
    )

    result = CliRunner().invoke(
        cli,
        ["daily", "sync", "--date", "2026-04-30", "--no-health", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["docs"]["attention_required"] is False
    assert payload["docs"]["action_created"] is False
    assert payload["docs"]["maintenance_policy"]["suggestions"] == "suggestions_only"


def test_daily_sync_configures_state_for_explicit_config(monkeypatch):
    import nudge.commands.daily as daily

    configured = []
    config = {
        "state": {"dir": "/tmp/nudge-daily-state"},
        "general": {"default_reminder_list": "日常"},
    }
    monkeypatch.setattr(daily, "load_config", lambda p=None: config)
    monkeypatch.setattr(daily, "configure_state", lambda loaded: configured.append(loaded))
    monkeypatch.setattr(daily, "get_actions", lambda **kwargs: [])
    monkeypatch.setattr(daily, "sync_completed_for_date", _empty_reminder_payload)
    monkeypatch.setattr(
        daily,
        "audit_docs",
        lambda root: {
            "ok": True,
            "summary": {"errors": 0, "warnings": 0, "suggestions": 0},
            "errors": [],
            "warnings": [],
            "suggestions": [],
        },
    )

    result = CliRunner().invoke(
        cli,
        ["daily", "sync", "--date", "2026-04-30", "--no-health", "--config", "custom.toml", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert configured == [config]
