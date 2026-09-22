"""Tests for the daily sync command."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from click.testing import CliRunner

from nudge.cli import cli
from nudge.json_contract import versioned_payload


@pytest.fixture(autouse=True)
def isolate_state_db(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.state.LEGACY_JSON", tmp_path / "state.json")
    monkeypatch.setattr("nudge.state._schema_initialized_for", None)
    monkeypatch.setattr("nudge.state._migrated", False)


def test_daily_sync_help_is_available():
    result = CliRunner().invoke(cli, ["daily", "sync", "--help"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    assert "Usage: nudge daily sync" in result.output
    assert "--apply" in result.output
    assert "--no-health" in result.output


def test_daily_sync_backfills_pending_reminder_dates(monkeypatch):
    import nudge.commands.daily as daily

    actions = [
        {
            "id": "old-reminder",
            "type": "reminder",
            "summary": "补录体重",
            "scheduled_at": "2026-04-28 06:40",
            "status": "created",
        },
        {
            "id": "calendar-event",
            "type": "calendar_event",
            "summary": "抗阻训练",
            "scheduled_at": "2026-04-28 18:30",
            "status": "created",
        },
    ]
    calls = []

    monkeypatch.setattr(daily, "load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr(daily, "get_actions", lambda **kwargs: actions)
    monkeypatch.setattr(
        daily,
        "sync_completed_for_date",
        lambda target_date, reminder_list, apply_changes: calls.append(
            (target_date.isoformat(), reminder_list, apply_changes)
        )
        or versioned_payload(
            {
                "ok": True,
                "dry_run": not apply_changes,
                "date": target_date.isoformat(),
                "list": reminder_list,
                "checked": 1,
                "open": 0,
                "candidates": [],
                "updated": 0,
                "auto_skipped_after_sleep": [],
                "warnings": [],
                "errors": [],
            }
        ),
    )

    result = CliRunner().invoke(
        cli,
        [
            "daily",
            "sync",
            "--date",
            "2026-04-30",
            "--lookback-days",
            "7",
            "--no-health",
            "--apply",
            "--json",
        ],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["dry_run"] is False
    assert payload["date"] == "2026-04-30"
    assert payload["reminders"]["list"] == "日常"
    assert payload["reminders"]["dates"] == ["2026-04-28", "2026-04-29", "2026-04-30"]
    assert calls == [
        ("2026-04-28", "日常", True),
        ("2026-04-29", "日常", True),
        ("2026-04-30", "日常", True),
    ]
    assert payload["health"] == {"ok": True, "skipped": True, "reason": "disabled"}
    assert payload["remaining_failures"]["summary"]["pending_overdue"] >= 1
    assert payload["human_needed"]




def test_daily_sync_promotes_reminder_human_needed_to_top_level(monkeypatch):
    import nudge.commands.daily as daily

    monkeypatch.setattr(daily, "load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr(daily, "get_actions", lambda **kwargs: [])
    monkeypatch.setattr(
        daily,
        "sync_completed_for_date",
        lambda target_date, reminder_list, apply_changes: versioned_payload(
            {
                "ok": True,
                "dry_run": not apply_changes,
                "date": target_date.isoformat(),
                "list": reminder_list,
                "checked": 1,
                "open": 0,
                "candidates": [],
                "human_needed": [
                    {
                        "id": "weight",
                        "summary": "称重",
                        "scheduled_at": f"{target_date.isoformat()} 06:40",
                        "reason": "missing_from_incomplete_without_completion_date",
                        "followup_commands": [
                            "nudge log done --id weight",
                            "nudge log skipped --id weight",
                            "nudge log partial --id weight",
                        ],
                    }
                ],
                "auto_apply_policy": "requires_apple_completion_date",
                "updated": 0,
                "auto_skipped_after_sleep": [],
                "warnings": [],
                "errors": [],
            }
        ),
    )

    result = CliRunner().invoke(
        cli,
        ["daily", "sync", "--date", "2026-04-30", "--no-health", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["human_needed"][0] == {
        "source": "reminders.sync_completed",
        "date": "2026-04-29",
        "id": "weight",
        "summary": "称重",
        "scheduled_at": "2026-04-29 06:40",
        "reason": "missing_from_incomplete_without_completion_date",
        "followup_commands": [
            "nudge log done --id weight",
            "nudge log skipped --id weight",
            "nudge log partial --id weight",
        ],
        "followup_command": "nudge log done --id weight",
    }

def test_daily_sync_reports_docs_audit_and_creates_maintenance_action_on_apply(monkeypatch):
    import nudge.commands.daily as daily

    created_actions = []
    audit_roots = []
    monkeypatch.setattr(daily, "load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr(daily, "get_actions", lambda **kwargs: [])
    monkeypatch.setattr(
        daily,
        "sync_completed_for_date",
        lambda target_date, reminder_list, apply_changes: versioned_payload(
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
        ),
    )
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
    monkeypatch.setattr(
        daily,
        "sync_completed_for_date",
        lambda target_date, reminder_list, apply_changes: versioned_payload(
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
        ),
    )
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
    monkeypatch.setattr(
        daily,
        "sync_completed_for_date",
        lambda target_date, reminder_list, apply_changes: versioned_payload(
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
        ),
    )
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
    monkeypatch.setattr(
        daily,
        "sync_completed_for_date",
        lambda target_date, reminder_list, apply_changes: versioned_payload(
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
        ),
    )
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


@dataclass
class _FakeHealthResult:
    source_path: str
    daily_summaries: list[dict]
    workouts: list[dict]
    ignored_route_files: int = 0
    export_xml_name: str = "health.json"

    @property
    def date_start(self):
        return "2026-04-29"

    @property
    def date_end(self):
        return "2026-04-30"


def test_daily_sync_imports_latest_health_export(monkeypatch, tmp_path):
    import nudge.commands.daily as daily

    older = tmp_path / "health-2026-04-29_060000.json"
    latest = tmp_path / "health-2026-04-30_064513.json"
    older.write_text('{"metrics": {}}', encoding="utf-8")
    latest.write_text('{"metrics": {}}', encoding="utf-8")

    parse_calls = []
    apply_calls = []

    monkeypatch.setattr(daily, "DEFAULT_HEALTH_EXPORT_DIR", tmp_path)
    monkeypatch.setattr(daily, "load_config", lambda p=None: {"general": {"default_reminder_list": "日常"}})
    monkeypatch.setattr(daily, "get_actions", lambda **kwargs: [])
    monkeypatch.setattr(
        daily,
        "sync_completed_for_date",
        lambda target_date, reminder_list, apply_changes: versioned_payload(
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
        ),
    )

    def fake_parse(path, *, date_from=None, date_to=None):
        parse_calls.append((path, date_from, date_to))
        return _FakeHealthResult(
            source_path=str(path),
            daily_summaries=[{"date": "2026-04-30", "body_weight_kg": 76.6}],
            workouts=[],
        )

    monkeypatch.setattr(daily, "parse_apple_health_export", fake_parse)
    monkeypatch.setattr(
        daily,
        "apply_health_import",
        lambda result: apply_calls.append(result.source_path) or {"daily_upserted": 1, "workouts_upserted": 0},
    )

    result = CliRunner().invoke(
        cli,
        ["daily", "sync", "--date", "2026-04-30", "--apply", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert parse_calls == [(str(latest), "2026-04-23", "2026-05-01")]
    assert apply_calls == [str(latest)]
    assert payload["health"]["ok"] is True
    assert payload["health"]["source"] == str(latest)
    assert payload["health"]["summary"] == {"daily": 1, "workouts": 0, "ignored_route_files": 0, "export_xml": "health.json"}
    assert payload["health"]["updated"] == {"daily_upserted": 1, "workouts_upserted": 0}
