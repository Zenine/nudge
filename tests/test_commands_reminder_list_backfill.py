"""CLI contracts for legacy Reminder list ownership backfill."""

import hashlib
import inspect
import json
import sqlite3
import unicodedata
from datetime import date
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from nudge.commands import db as db_commands
from nudge.commands import reminder_list_backfill as command
from nudge.commands.reminders import reminders_command
from nudge.reminder_lists import ReminderListBackfillBatch
import nudge.state as state


def test_backfill_lists_command_is_registered() -> None:
    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--help"])

    assert result.exit_code == 0, result.output
    assert "--from" in result.output
    assert "--apply" in result.output


def _action(
    action_id: str,
    *,
    summary: str = "Buy milk",
    scheduled_at: str = "2026-07-01 09:00",
) -> dict:
    return {
        "id": action_id,
        "type": "reminder",
        "summary": summary,
        "scheduled_at": scheduled_at,
        "status": "pending",
        "reminder_list": None,
        "notes": "private SQLite note",
    }


def _state_directory_snapshot(directory) -> dict:
    return {
        path.name: (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in directory.iterdir()
        if path.is_file()
    }


def _install_read_only_spies(monkeypatch, *, actions: list[dict]) -> dict:
    calls = {"configure": [], "backup": 0, "apply": 0}
    monkeypatch.setattr(
        command,
        "load_config",
        lambda path=None: {
            "state": {"dir": "/tmp/test-state"},
            "reminders": {"sync_lists": ["Tasks", "Health"]},
        },
    )
    monkeypatch.setattr(
        command,
        "configure_state",
        lambda config: calls["configure"].append(config),
    )
    monkeypatch.setattr(command, "get_actions_readonly", lambda: actions, raising=False)

    def unexpected_backup(*args, **kwargs):
        calls["backup"] += 1
        raise AssertionError("dry-run must not back up")

    def unexpected_apply(*args, **kwargs):
        calls["apply"] += 1
        raise AssertionError("dry-run must not write")

    monkeypatch.setattr(command, "backup_database", unexpected_backup)
    monkeypatch.setattr(command, "apply_reminder_list_backfill", unexpected_apply)
    return calls


def test_config_lists_dry_run_is_read_only_and_json_does_not_leak_notes(monkeypatch) -> None:
    calls = _install_read_only_spies(monkeypatch, actions=[_action("legacy")])
    monkeypatch.setattr(
        command,
        "query_all_due_on_date",
        lambda list_name, target_date: (
            True,
            [{
                "name": "Buy milk",
                "due_time": "09:00",
                "due_at": "2026-07-01 09:00",
                "list": list_name,
                "notes": "private Apple note",
                "private_extra": "never serialize",
            }] if list_name == "Tasks" else [],
        ),
    )

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["apply_allowed"] is True
    assert payload["lists"] == ["Tasks", "Health"]
    assert payload["candidates"] == [{
        "id": "legacy",
        "summary": "Buy milk",
        "scheduled_at": "2026-07-01 09:00",
        "status": "pending",
        "current_reminder_list": None,
        "target_list": "Tasks",
        "match_type": "exact_title",
    }]
    assert payload["updated"] == 0
    assert payload["backup"] is None
    assert payload["conflicts"] == []
    assert "private" not in result.output
    assert len(calls["configure"]) == 1
    assert calls["backup"] == 0
    assert calls["apply"] == 0


def test_text_emit_prints_all_classifications_conflicts_and_updated_without_notes() -> None:
    payload = {
        "schema_version": "nudge.cli.v1",
        "ok": False,
        "dry_run": True,
        "apply_allowed": False,
        "lists": ["Tasks", "Health"],
        "range": {"from": "2026-07-01", "to": "2026-08-01"},
        "limit": 100,
        "total_eligible": 4,
        "remaining": 2,
        "candidates": [{
            "id": "candidate",
            "scheduled_at": "2026-07-01 09:00",
            "summary": "Candidate title",
            "target_list": "Tasks",
            "match_type": "exact_title",
            "notes": "private candidate note",
        }],
        "missing": [{
            "id": "missing",
            "scheduled_at": "2026-07-01 10:00",
            "summary": "Missing title",
            "notes": "private missing note",
        }],
        "ambiguous": [{
            "id": "ambiguous",
            "scheduled_at": "2026-07-01 11:00",
            "summary": "Ambiguous title",
            "matches": 2,
            "matched_lists": ["Health", "Tasks"],
            "notes": "private ambiguous note",
        }],
        "invalid": [{
            "id": "invalid",
            "scheduled_at": "bad",
            "summary": "Invalid title",
            "reason": "invalid_summary_or_scheduled_at",
            "notes": "private invalid note",
        }],
        "updated": 3,
        "backup": {"path": "/tmp/backup.db", "integrity": "ok", "notes": "private backup note"},
        "conflicts": ["conflict-b", "conflict-a"],
        "errors": [{"code": "SAMPLE", "message": "Safe error", "notes": "private error note"}],
    }

    @click.command()
    def emit_payload() -> None:
        command._emit(payload, json_output=False)

    result = CliRunner().invoke(emit_payload)

    assert result.exit_code == 0, result.output
    assert "DRY-RUN Reminder list backfill · Tasks, Health" in result.output
    assert "eligible: 4" in result.output
    assert "candidates: 1" in result.output
    assert "missing: 1" in result.output
    assert "ambiguous: 1" in result.output
    assert "invalid: 1" in result.output
    assert "remaining: 2" in result.output
    assert "updated: 3" in result.output
    assert "/tmp/backup.db" in result.output
    assert "integrity: ok" in result.output
    for expected in (
        "candidate", "2026-07-01 09:00", "Candidate title", "Tasks", "exact_title",
        "missing", "Missing title", "ambiguous", "matches: 2", "Health, Tasks",
        "invalid", "invalid_summary_or_scheduled_at", "conflict-a", "conflict-b",
        "SAMPLE", "Safe error",
    ):
        assert expected in result.output
    assert "private" not in result.output


def test_repeated_lists_override_config_and_keep_list_then_date_query_order(monkeypatch) -> None:
    actions = [
        _action("later", scheduled_at="2026-07-02 09:00"),
        _action("earlier", scheduled_at="2026-07-01 09:00"),
    ]
    calls = _install_read_only_spies(monkeypatch, actions=actions)
    queries: list[tuple[str, date]] = []

    def fake_query(list_name, target_date):
        queries.append((list_name, target_date))
        return True, []

    monkeypatch.setattr(command, "query_all_due_on_date", fake_query)

    result = CliRunner().invoke(
        reminders_command,
        [
            "backfill-lists", "--list", "Zulu", "--list", "Alpha", "--list", "Zulu",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["lists"] == ["Zulu", "Alpha"]
    assert queries == [
        ("Zulu", date(2026, 7, 1)),
        ("Zulu", date(2026, 7, 2)),
        ("Alpha", date(2026, 7, 1)),
        ("Alpha", date(2026, 7, 2)),
    ]
    assert len(calls["configure"]) == 1


def test_query_failure_keeps_diagnostics_but_disables_apply(monkeypatch) -> None:
    actions = [
        _action("matched"),
        _action("missing", summary="No Apple row", scheduled_at="2026-07-02 10:00"),
    ]
    _install_read_only_spies(monkeypatch, actions=actions)

    def fake_query(list_name, target_date):
        if target_date == date(2026, 7, 2):
            return False, "private Apple adapter failure"
        if list_name == "Tasks":
            return True, [{
                "name": "Buy milk",
                "due_time": "09:00",
                "due_at": "2026-07-01 09:00",
                "list": "Tasks",
            }]
        return True, []

    monkeypatch.setattr(command, "query_all_due_on_date", fake_query)

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["apply_allowed"] is False
    assert [item["id"] for item in payload["candidates"]] == ["matched"]
    assert [item["id"] for item in payload["missing"]] == ["missing"]
    assert payload["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_QUERY_FAILED"
    assert payload["errors"][0]["list"] == "Tasks"
    assert payload["errors"][0]["date"] == "2026-07-02"
    assert payload["errors"][0]["message"] == "Unable to query this Reminder list and date."
    assert "private Apple adapter failure" not in result.output


def test_config_and_range_failures_are_separate_and_yes_without_apply_is_first(monkeypatch) -> None:
    load_calls: list[object] = []

    def fail_config(path=None):
        load_calls.append(path)
        raise ValueError("private config detail")

    monkeypatch.setattr(command, "load_config", fail_config)

    yes_result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--yes", "--json"],
    )
    assert yes_result.exit_code == 1
    assert json.loads(yes_result.output)["errors"][0]["code"] == (
        "REMINDER_LIST_BACKFILL_CONFIRMATION_INVALID"
    )
    assert load_calls == []

    range_result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--from", "2026-07-02", "--to", "2026-07-01", "--json"],
    )
    assert range_result.exit_code == 1
    range_payload = json.loads(range_result.output)
    assert range_payload["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_RANGE_INVALID"
    assert load_calls == []

    config_result = CliRunner().invoke(reminders_command, ["backfill-lists", "--json"])
    assert config_result.exit_code == 1
    config_payload = json.loads(config_result.output)
    assert config_payload["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_CONFIG_INVALID"
    assert "private config detail" not in config_result.output
    assert load_calls == [None]


def test_successful_config_load_configures_state_before_list_resolution(monkeypatch) -> None:
    calls: list[str] = []
    config = {"state": {"dir": "/tmp/custom-state"}}

    def load(path=None):
        calls.append("load")
        return config

    def configure(loaded):
        assert loaded is config
        calls.append("configure")

    def fail_resolve(explicit_names, loaded):
        assert loaded is config
        calls.append("resolve")
        raise ValueError("invalid lists")

    monkeypatch.setattr(command, "load_config", load)
    monkeypatch.setattr(command, "configure_state", configure)
    monkeypatch.setattr(command, "resolve_sync_lists", fail_resolve)

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--json"])

    assert result.exit_code == 1, result.output
    assert calls == ["load", "configure", "resolve"]
    assert json.loads(result.output)["errors"][0]["code"] == (
        "REMINDER_LIST_BACKFILL_CONFIG_INVALID"
    )


def test_sqlite_read_failure_has_stable_safe_error_and_zero_writes(monkeypatch) -> None:
    calls = _install_read_only_spies(monkeypatch, actions=[])

    def fail_read():
        raise sqlite3.OperationalError("private_table secret path")

    monkeypatch.setattr(command, "get_actions_readonly", fail_read, raising=False)

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["errors"] == [{
        "code": "REMINDER_LIST_BACKFILL_WRITE_FAILED",
        "message": "Unable to read Nudge actions.",
    }]
    assert payload["ok"] is False
    assert payload["apply_allowed"] is False
    assert "private_table" not in result.output
    assert "secret path" not in result.output
    assert calls["backup"] == 0
    assert calls["apply"] == 0


def test_each_unique_list_date_is_queried_once_and_rows_receive_unique_keys(monkeypatch) -> None:
    _install_read_only_spies(monkeypatch, actions=[_action("legacy")])
    batch = ReminderListBackfillBatch(
        actions=[_action("legacy")],
        query_dates=(date(2026, 7, 1), date(2026, 7, 1)),
        invalid=[],
        total_eligible=1,
        remaining=0,
    )
    monkeypatch.setattr(command, "select_list_backfill_actions", lambda *args, **kwargs: batch)
    query_calls: list[tuple[str, date]] = []

    def fake_query(list_name, target_date):
        query_calls.append((list_name, target_date))
        return True, [
            {
                "name": "Buy milk", "due_time": "09:00",
                "due_at": "2026-07-01 09:00", "list": list_name,
            },
            {
                "name": "Buy milk", "due_time": "09:00",
                "due_at": "2026-07-01 09:00", "list": list_name,
            },
        ]

    captured: dict = {}

    def fake_plan(actions, rows):
        captured["rows"] = list(rows)
        return {"candidates": [], "missing": [], "ambiguous": []}

    monkeypatch.setattr(command, "query_all_due_on_date", fake_query)
    monkeypatch.setattr(command, "plan_list_backfill", fake_plan)

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--list", "Tasks", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert query_calls == [("Tasks", date(2026, 7, 1))]
    assert len(captured["rows"]) == 2
    assert len({row["row_key"] for row in captured["rows"]}) == 2


@pytest.mark.parametrize(
    "bad_rows",
    [
        ["not an object"],
        [{
            "name": "Buy milk", "due_time": "09:00",
            "due_at": "2026-07-01 09:00", "list": "Other",
        }],
        [{
            "name": "Buy milk", "due_time": "09:01",
            "due_at": "2026-07-01 09:00", "list": "Tasks",
        }],
        [{
            "name": "Buy milk", "due_at": "2026-07-01 09:00", "list": "Tasks",
        }],
        [{
            "name": "Buy milk", "due_time": "09:00", "list": "Tasks",
        }],
    ],
)
def test_malformed_or_wrong_list_rows_are_query_failures(monkeypatch, bad_rows) -> None:
    _install_read_only_spies(monkeypatch, actions=[_action("legacy")])
    monkeypatch.setattr(command, "query_all_due_on_date", lambda *args: (True, bad_rows))

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--list", "Tasks", "--json"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["apply_allowed"] is False
    assert payload["candidates"] == []
    assert payload["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_QUERY_FAILED"
    assert "Other" not in repr(payload["candidates"])


def test_range_limit_and_versioned_schema_are_stable(monkeypatch) -> None:
    _install_read_only_spies(monkeypatch, actions=[])
    monkeypatch.setattr(command, "query_all_due_on_date", lambda *args: (True, []))
    selected: dict = {}
    real_select = command.select_list_backfill_actions

    def capture_select(actions, **kwargs):
        selected.update(kwargs)
        return real_select(actions, **kwargs)

    monkeypatch.setattr(command, "select_list_backfill_actions", capture_select)

    result = CliRunner().invoke(
        reminders_command,
        [
            "backfill-lists", "--from", "2026-07-01", "--to", "2026-08-01",
            "--limit", "500", "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert selected == {
        "date_from": date(2026, 7, 1),
        "date_to": date(2026, 8, 1),
        "limit": 500,
    }
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["range"] == {"from": "2026-07-01", "to": "2026-08-01"}
    assert payload["limit"] == 500
    for key in (
        "ok", "dry_run", "apply_allowed", "lists", "range", "limit",
        "total_eligible", "remaining", "candidates", "missing", "ambiguous",
        "invalid", "updated", "backup", "conflicts", "errors",
    ):
        assert key in payload


@pytest.mark.parametrize("limit", ["0", "501", "1.5", "hundred"])
def test_limit_is_manually_validated_with_stable_range_error(monkeypatch, limit) -> None:
    monkeypatch.setattr(
        command,
        "load_config",
        lambda path=None: (_ for _ in ()).throw(AssertionError("must validate before config")),
    )

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--limit", limit, "--json"],
    )

    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["errors"][0]["code"] == (
        "REMINDER_LIST_BACKFILL_RANGE_INVALID"
    )


def _install_single_candidate_plan(monkeypatch) -> dict:
    calls = _install_read_only_spies(monkeypatch, actions=[_action("legacy")])
    monkeypatch.setattr(
        command,
        "query_all_due_on_date",
        lambda list_name, target_date: (
            True,
            [{
                "name": "Buy milk",
                "due_time": "09:00",
                "due_at": "2026-07-01 09:00",
                "list": list_name,
            }] if list_name == "Tasks" else [],
        ),
    )
    return calls


@pytest.mark.parametrize(
    "arguments",
    [
        ["backfill-lists", "--apply"],
        ["backfill-lists", "--apply", "--json"],
    ],
)
def test_apply_without_yes_requires_confirmation_after_planning_and_before_backup(
    monkeypatch,
    arguments,
) -> None:
    calls = _install_single_candidate_plan(monkeypatch)
    monkeypatch.setattr(command, "_is_interactive_terminal", lambda: False, raising=False)

    result = CliRunner().invoke(reminders_command, arguments)

    assert result.exit_code == 1, result.output
    assert "REMINDER_LIST_BACKFILL_CONFIRMATION_REQUIRED" in result.output
    if "--json" in arguments:
        payload = json.loads(result.output)
        assert [item["id"] for item in payload["candidates"]] == ["legacy"]
        assert payload["dry_run"] is False
        assert payload["updated"] == 0
    assert calls["backup"] == 0
    assert calls["apply"] == 0


def test_tty_confirmation_no_cancels_after_final_summary_without_backup(monkeypatch) -> None:
    calls = _install_single_candidate_plan(monkeypatch)
    monkeypatch.setattr(command, "_is_interactive_terminal", lambda: True, raising=False)

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--apply"],
        input="n\n",
    )

    assert result.exit_code == 1, result.output
    assert "candidate: legacy" in result.output
    assert "确认仅回填以上 Nudge SQLite reminder_list？" in result.output
    assert "REMINDER_LIST_BACKFILL_CANCELLED" in result.output
    assert calls["backup"] == 0
    assert calls["apply"] == 0


def test_tty_confirmation_eof_is_stable_cancelled_without_backup(monkeypatch) -> None:
    calls = _install_single_candidate_plan(monkeypatch)
    monkeypatch.setattr(command, "_is_interactive_terminal", lambda: True, raising=False)

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--apply"],
        input="",
    )

    assert result.exit_code == 1, result.output
    assert "REMINDER_LIST_BACKFILL_CANCELLED" in result.output
    assert "Aborted!" not in result.output
    assert calls["backup"] == 0
    assert calls["apply"] == 0


def test_tty_confirmation_ctrl_c_is_stable_cancelled_without_backup(monkeypatch) -> None:
    calls = _install_single_candidate_plan(monkeypatch)
    monkeypatch.setattr(command, "_is_interactive_terminal", lambda: True, raising=False)
    monkeypatch.setattr(
        command.click,
        "confirm",
        lambda *args, **kwargs: (_ for _ in ()).throw(click.Abort()),
    )

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--apply"])

    assert result.exit_code == 1, result.output
    assert "REMINDER_LIST_BACKFILL_CANCELLED" in result.output
    assert "Aborted!" not in result.output
    assert calls["backup"] == 0
    assert calls["apply"] == 0


def test_apply_yes_backs_up_before_atomic_write_with_complete_snapshots(monkeypatch) -> None:
    _install_single_candidate_plan(monkeypatch)
    events: list[object] = []
    backup_path = Path("/tmp/nudge-test-backup.db")

    def backup(*, initialize=True):
        events.append(("backup", initialize))
        return backup_path

    def apply(updates, *, snapshots):
        events.append(("apply", updates, snapshots))
        return ["legacy"]

    monkeypatch.setattr(command, "backup_database", backup)
    monkeypatch.setattr(command, "apply_reminder_list_backfill", apply)

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--apply", "--yes", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is False
    assert payload["updated"] == 1
    assert payload["backup"] == {"path": str(backup_path), "integrity": "ok"}
    assert events[0] == ("backup", False)
    assert events[1][0] == "apply"
    assert events[1][1] == [{"id": "legacy", "target_list": "Tasks"}]
    snapshot = events[1][2]["legacy"]
    assert snapshot == _action("legacy")


def test_text_apply_reports_candidates_update_and_verified_backup_without_notes(
    monkeypatch,
) -> None:
    _install_single_candidate_plan(monkeypatch)
    backup_path = Path("/tmp/nudge\x1b[31m-backup.db")
    monkeypatch.setattr(command, "backup_database", lambda **kwargs: backup_path)
    monkeypatch.setattr(
        command,
        "apply_reminder_list_backfill",
        lambda updates, *, snapshots: ["legacy"],
    )

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--apply", "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert "APPLY Reminder list backfill" in result.output
    assert "candidate: legacy" in result.output
    assert "updated: 1" in result.output
    assert "backup: /tmp/nudge-backup.db" in result.output
    assert "integrity: ok" in result.output
    assert "private SQLite note" not in result.output
    assert "[31m" not in result.output


def test_apply_with_zero_candidates_skips_confirmation_backup_and_transaction(monkeypatch) -> None:
    calls = _install_read_only_spies(monkeypatch, actions=[])
    monkeypatch.setattr(command, "query_all_due_on_date", lambda *args: (True, []))
    monkeypatch.setattr(
        command,
        "_is_interactive_terminal",
        lambda: (_ for _ in ()).throw(AssertionError("must not inspect TTY")),
        raising=False,
    )

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--apply", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is False
    assert payload["candidates"] == []
    assert payload["updated"] == 0
    assert payload["backup"] is None
    assert calls["backup"] == 0
    assert calls["apply"] == 0


def test_backup_failure_is_safe_and_never_calls_apply(monkeypatch) -> None:
    calls = _install_single_candidate_plan(monkeypatch)

    def fail_backup(*, initialize=True):
        assert initialize is False
        raise sqlite3.OperationalError("private backup path and schema")

    monkeypatch.setattr(command, "backup_database", fail_backup)

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--apply", "--yes", "--json"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["errors"] == [{
        "code": "REMINDER_LIST_BACKFILL_BACKUP_FAILED",
        "message": "Unable to create a verified Nudge database backup.",
    }]
    assert payload["updated"] == 0
    assert payload["backup"] is None
    assert "private" not in result.output
    assert calls["apply"] == 0


def test_conflict_and_write_failure_keep_verified_backup_and_zero_updates(monkeypatch) -> None:
    backup_path = Path("/tmp/nudge-test-backup.db")

    for failure, expected_code, expected_conflicts in (
        (state.ReminderListBackfillConflictError(["legacy"]),
         "REMINDER_LIST_BACKFILL_CONFLICT", ["legacy"]),
        (sqlite3.OperationalError("private SQLite details"),
         "REMINDER_LIST_BACKFILL_WRITE_FAILED", []),
        (ValueError("private validation details"),
         "REMINDER_LIST_BACKFILL_WRITE_FAILED", []),
    ):
        _install_single_candidate_plan(monkeypatch)
        monkeypatch.setattr(command, "backup_database", lambda **kwargs: backup_path)

        def fail_apply(*args, _failure=failure, **kwargs):
            raise _failure

        monkeypatch.setattr(command, "apply_reminder_list_backfill", fail_apply)
        result = CliRunner().invoke(
            reminders_command,
            ["backfill-lists", "--apply", "--yes", "--json"],
        )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.output)
        assert payload["errors"][0]["code"] == expected_code
        assert payload["conflicts"] == expected_conflicts
        assert payload["updated"] == 0
        assert payload["backup"] == {"path": str(backup_path), "integrity": "ok"}
        assert "private" not in result.output


def test_backup_without_initialize_never_opens_state_connection_and_cleans_partial(
    monkeypatch,
    tmp_path,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db_path = state_dir / "nudge.db"
    _create_conn = sqlite3.connect(db_path)
    try:
        _create_conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        _create_conn.execute("INSERT INTO sample (id) VALUES (1)")
        _create_conn.commit()
    finally:
        _create_conn.close()
    monkeypatch.setattr(state, "STATE_DIR", state_dir)
    monkeypatch.setattr(state, "DB_PATH", db_path)
    monkeypatch.setattr(
        state,
        "_get_conn",
        lambda: (_ for _ in ()).throw(AssertionError("must not initialize or migrate")),
    )

    destination = state_dir / "backups" / "verified.db"
    result = command.backup_database(destination, initialize=False)

    assert result == destination
    assert db_commands._integrity_check(destination) == "ok"
    with sqlite3.connect(destination) as conn:
        assert conn.execute("SELECT id FROM sample").fetchall() == [(1,)]

    partial = state_dir / "backups" / "partial.db"
    original_connect = sqlite3.connect

    class FailingSource:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.connection.close()

        def backup(self, target):
            raise sqlite3.Error("failed")

    connect_calls = 0

    def failing_connect(path, *args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        connection = original_connect(path, *args, **kwargs)
        if connect_calls == 1:
            return FailingSource(connection)
        return connection

    with pytest.MonkeyPatch.context() as cleanup_patch:
        cleanup_patch.setattr(db_commands.sqlite3, "connect", failing_connect)
        with pytest.raises(sqlite3.Error):
            command.backup_database(partial, initialize=False)
    assert not partial.exists()
    assert not list(partial.parent.glob(f".{partial.name}.partial-*"))


def test_backup_without_initialize_preserves_existing_destination_on_failure(
    monkeypatch,
    tmp_path,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db_path = state_dir / "nudge.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    monkeypatch.setattr(state, "STATE_DIR", state_dir)
    monkeypatch.setattr(state, "DB_PATH", db_path)
    monkeypatch.setattr(
        state,
        "_get_conn",
        lambda: (_ for _ in ()).throw(AssertionError("must not initialize or migrate")),
    )
    destination = state_dir / "backups" / "existing.db"
    destination.parent.mkdir()
    existing = b"existing valid backup sentinel"
    destination.write_bytes(existing)
    original_connect = sqlite3.connect
    connect_calls = 0

    class FailingSource:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.connection.close()

        def backup(self, target):
            raise sqlite3.Error("private failure")

    def failing_connect(path, *args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        connection = original_connect(path, *args, **kwargs)
        if connect_calls == 1:
            return FailingSource(connection)
        return connection

    with pytest.MonkeyPatch.context() as cleanup_patch:
        cleanup_patch.setattr(db_commands.sqlite3, "connect", failing_connect)
        with pytest.raises(sqlite3.Error):
            command.backup_database(destination, initialize=False)

    assert destination.read_bytes() == existing
    assert not list(destination.parent.glob(f".{destination.name}.partial-*"))


def test_backup_without_initialize_missing_source_creates_nothing(monkeypatch, tmp_path) -> None:
    state_dir = tmp_path / "missing"
    monkeypatch.setattr(state, "STATE_DIR", state_dir)
    monkeypatch.setattr(state, "DB_PATH", state_dir / "nudge.db")
    monkeypatch.setattr(
        state,
        "_get_conn",
        lambda: (_ for _ in ()).throw(AssertionError("must not initialize or migrate")),
    )
    destination = tmp_path / "backup.db"

    with pytest.raises(FileNotFoundError):
        command.backup_database(destination, initialize=False)

    assert not state_dir.exists()
    assert not destination.exists()


def test_reminder_list_backfill_command_has_no_apple_mutation_imports() -> None:
    source = inspect.getsource(command)

    for forbidden in (
        "complete_reminder", "delete_reminder", "create_reminder",
        "update_action_external_id", "set_external_id",
    ):
        assert forbidden not in source


def test_cross_date_query_row_is_rejected_before_planning(monkeypatch) -> None:
    actions = [
        _action("first", summary="First", scheduled_at="2026-07-01 08:00"),
        _action("cross-date", summary="Cross", scheduled_at="2026-07-02 09:00"),
    ]
    _install_read_only_spies(monkeypatch, actions=actions)

    def fake_query(list_name, target_date):
        if target_date == date(2026, 7, 1):
            return True, [{
                "name": "Cross",
                "due_time": "09:00",
                "due_at": "2026-07-02 09:00",
                "list": list_name,
            }]
        return True, []

    monkeypatch.setattr(command, "query_all_due_on_date", fake_query)

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--list", "Tasks", "--json"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["candidates"] == []
    assert {item["id"] for item in payload["missing"]} == {"first", "cross-date"}
    assert payload["errors"] == [{
        "code": "REMINDER_LIST_BACKFILL_QUERY_FAILED",
        "list": "Tasks",
        "date": "2026-07-01",
        "message": "Unable to query this Reminder list and date.",
    }]


@pytest.mark.parametrize(
    "bad_config",
    [
        'reminders = "private bad reminders"\n',
        "state = 1\n",
        'general = ["private bad general"]\n',
    ],
)
def test_real_toml_with_invalid_section_shapes_is_config_invalid(
    monkeypatch,
    tmp_path,
    bad_config,
) -> None:
    config_path = tmp_path / "bad.toml"
    config_path.write_text(bad_config, encoding="utf-8")
    monkeypatch.setattr(
        command,
        "configure_state",
        lambda config: pytest.fail("invalid config must not configure state"),
    )
    monkeypatch.setattr(
        command,
        "resolve_sync_lists",
        lambda names, config: pytest.fail("invalid config must not resolve lists"),
    )

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_CONFIG_INVALID"
    assert "Traceback" not in result.output
    assert "private bad" not in result.output


def test_missing_readonly_database_cli_does_not_create_or_migrate_state(tmp_path) -> None:
    state_dir = tmp_path / "missing-state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[state]\ndir = "{state_dir}"\n[reminders]\nsync_lists = ["Tasks"]\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["errors"][0]["code"] == (
        "REMINDER_LIST_BACKFILL_WRITE_FAILED"
    )
    assert not state_dir.exists()
    assert not (state_dir / "nudge.db").exists()
    assert not (state_dir / "state.json").exists()


def test_text_output_removes_terminal_controls_and_truncates_untrusted_fields() -> None:
    injection = "line1\r\nline2\t\x1b[31mRED\x1b[0m\x1b]8;;https://bad\x07OSC\x1b]8;;\x07\u202eEND"
    long_text = "X" * 700
    payload = {
        "schema_version": "nudge.cli.v1",
        "ok": False,
        "dry_run": True,
        "apply_allowed": False,
        "lists": [injection],
        "range": {"from": None, "to": None},
        "limit": 100,
        "total_eligible": 1,
        "remaining": 0,
        "candidates": [{
            "id": injection,
            "scheduled_at": injection,
            "summary": long_text,
            "target_list": injection,
            "match_type": injection,
        }],
        "missing": [],
        "ambiguous": [],
        "invalid": [{
            "id": injection,
            "scheduled_at": injection,
            "summary": injection,
            "reason": injection,
        }],
        "updated": 0,
        "backup": {"path": injection, "integrity": injection},
        "conflicts": [injection],
        "errors": [{"code": injection, "message": injection, "list": injection, "date": injection}],
    }

    @click.command()
    def emit_payload() -> None:
        command._emit(payload, json_output=False)

    result = CliRunner().invoke(emit_payload)

    assert result.exit_code == 0, result.output
    assert all(
        character in "\n" or not unicodedata.category(character).startswith("C")
        for character in result.output
    )
    assert "[31m" not in result.output
    assert "8;;https://bad" not in result.output
    assert "X" * 501 not in result.output


def test_json_output_sanitizes_all_public_strings_without_leaking_notes() -> None:
    injection = (
        "safe\x7f\x85\u202e\u2066\x1b[31mRED\x1b[0m"
        "\x1b]8;;https://bad\x07OSC\x1b]8;;\x07中文"
    )
    payload = {
        "schema_version": "nudge.cli.v1",
        "ok": False,
        "dry_run": False,
        "apply_allowed": False,
        "lists": [injection],
        "range": {"from": injection, "to": None},
        "limit": 100,
        "total_eligible": 1,
        "remaining": 0,
        "candidates": [{
            "id": injection,
            "summary": injection,
            "scheduled_at": injection,
            "status": injection,
            "current_reminder_list": None,
            "target_list": injection,
            "match_type": injection,
            "notes": "private candidate note",
        }],
        "missing": [],
        "ambiguous": [],
        "invalid": [],
        "updated": 0,
        "backup": {"path": injection, "integrity": injection, "notes": "private backup"},
        "conflicts": [injection, {"id": injection, "reason": injection, "notes": "private"}],
        "errors": [{
            "code": injection,
            "message": injection,
            "list": injection,
            "date": injection,
            "notes": "private error note",
        }],
    }

    @click.command()
    def emit_payload() -> None:
        command._emit(payload, json_output=True)

    result = CliRunner().invoke(emit_payload)

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)

    def public_strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                yield from public_strings(item)
        elif isinstance(value, dict):
            for item in value.values():
                yield from public_strings(item)

    strings = list(public_strings(parsed))
    assert all(
        not unicodedata.category(character).startswith("C")
        for value in strings
        for character in value
    )
    assert all("[31m" not in value and "8;;https://bad" not in value for value in strings)
    assert "\x7f" not in result.output
    assert "\x85" not in result.output
    assert "\u202e" not in result.output
    assert "private" not in result.output
    assert "中文" in parsed["lists"][0]
    assert parsed["limit"] == 100
    assert parsed["backup"] is not None


def test_programming_errors_are_not_mislabeled_as_sqlite_failures(monkeypatch) -> None:
    _install_read_only_spies(monkeypatch, actions=[])

    def fail_read():
        raise RuntimeError("programming bug")

    monkeypatch.setattr(command, "get_actions_readonly", fail_read, raising=False)

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--json"])

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    assert "REMINDER_LIST_BACKFILL_WRITE_FAILED" not in result.output


def test_unmigrated_actions_schema_fails_before_apple_query_without_file_changes(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("NUDGE_STATE_DIR", raising=False)
    state_dir = tmp_path / "old-state"
    state_dir.mkdir()
    db_path = state_dir / "nudge.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE actions (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                summary TEXT NOT NULL,
                scheduled_at TEXT,
                completed_at TEXT,
                status TEXT,
                external_id TEXT,
                feedback TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO actions (
                id, type, summary, scheduled_at, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy", "reminder", "Looks eligible", "2026-07-01 09:00",
                "pending", "2026-07-01 08:00",
            ),
        )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[state]\ndir = "{state_dir}"\n[reminders]\nsync_lists = ["Tasks"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(state, "STATE_DIR", state.STATE_DIR)
    monkeypatch.setattr(state, "DB_PATH", state.DB_PATH)
    monkeypatch.setattr(state, "LEGACY_JSON", state.LEGACY_JSON)
    query_calls = []

    def unexpected_query(*args):
        query_calls.append(args)
        return True, []

    monkeypatch.setattr(command, "query_all_due_on_date", unexpected_query)
    before = _state_directory_snapshot(state_dir)

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--config", str(config_path), "--json"],
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["apply_allowed"] is False
    assert payload["candidates"] == []
    assert payload["errors"] == [{
        "code": "REMINDER_LIST_BACKFILL_WRITE_FAILED",
        "message": "Unable to read Nudge actions.",
    }]
    assert query_calls == []
    assert str(state_dir) not in result.output
    assert "reminder_list" not in result.output
    assert _state_directory_snapshot(state_dir) == before
    with sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(actions)")]
    assert "reminder_list" not in columns
