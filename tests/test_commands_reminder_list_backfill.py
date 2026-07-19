"""CLI contracts for legacy Reminder list ownership backfill."""

import json
import sqlite3
import unicodedata
from datetime import date

import click
import pytest
from click.testing import CliRunner

from nudge.commands import reminder_list_backfill as command
from nudge.commands.reminders import reminders_command
from nudge.reminder_lists import ReminderListBackfillBatch


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


@pytest.mark.parametrize(
    "arguments",
    [
        ["backfill-lists", "--apply"],
        ["backfill-lists", "--apply", "--yes", "--json"],
    ],
)
def test_apply_is_unavailable_before_any_read_backup_or_write(monkeypatch, arguments) -> None:
    calls = {"config": 0, "read": 0, "query": 0, "backup": 0, "write": 0}

    def unexpected(name):
        def fail(*args, **kwargs):
            calls[name] += 1
            raise AssertionError(f"{name} must not run")

        return fail

    monkeypatch.setattr(command, "load_config", unexpected("config"))
    monkeypatch.setattr(command, "get_actions_readonly", unexpected("read"), raising=False)
    monkeypatch.setattr(command, "query_all_due_on_date", unexpected("query"))
    monkeypatch.setattr(command, "backup_database", unexpected("backup"))
    monkeypatch.setattr(command, "apply_reminder_list_backfill", unexpected("write"))

    result = CliRunner().invoke(reminders_command, arguments)

    assert result.exit_code == 1, result.output
    assert "REMINDER_LIST_BACKFILL_WRITE_FAILED" in result.output
    assert "unavailable" in result.output.lower()
    assert calls == {"config": 0, "read": 0, "query": 0, "backup": 0, "write": 0}


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


def test_programming_errors_are_not_mislabeled_as_sqlite_failures(monkeypatch) -> None:
    _install_read_only_spies(monkeypatch, actions=[])

    def fail_read():
        raise RuntimeError("programming bug")

    monkeypatch.setattr(command, "get_actions_readonly", fail_read, raising=False)

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--json"])

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    assert "REMINDER_LIST_BACKFILL_WRITE_FAILED" not in result.output
