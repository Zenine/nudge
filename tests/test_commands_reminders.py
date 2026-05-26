"""Tests for Reminders sync CLI state handling."""

from __future__ import annotations

import json
from datetime import date

from click.testing import CliRunner

from nudge.cli import cli
from nudge.json_contract import versioned_payload


def test_reminders_sync_completed_configures_state_for_explicit_config(monkeypatch):
    import nudge.commands.reminders as reminders

    configured = []
    config = {
        "state": {"dir": "/tmp/nudge-reminders-state"},
        "general": {"default_reminder_list": "日常"},
    }
    monkeypatch.setattr(reminders, "load_config", lambda p=None: config)
    monkeypatch.setattr(reminders, "configure_state", lambda loaded: configured.append(loaded))
    monkeypatch.setattr(
        reminders,
        "sync_completed_for_date",
        lambda *, target_date, reminder_list, apply_changes: versioned_payload(
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

    result = CliRunner().invoke(
        cli,
        [
            "reminders",
            "sync-completed",
            "--date",
            "2026-04-30",
            "--config",
            "custom.toml",
            "--json",
        ],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert configured == [config]
    payload = json.loads(result.output)
    assert payload["date"] == date(2026, 4, 30).isoformat()
    assert payload["list"] == "日常"
