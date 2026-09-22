"""Tests for database backup, export, and restore commands."""

import json
import sqlite3

from click.testing import CliRunner

from nudge.cli import cli


def _isolate_db(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.state.LEGACY_JSON", tmp_path / "state.json")


def _insert_action(summary: str):
    from nudge.state import log_action

    log_action("reminder", summary, "2026-05-06 08:00")


def _action_summaries(db_path):
    with sqlite3.connect(db_path) as conn:
        return [row[0] for row in conn.execute("SELECT summary FROM actions ORDER BY summary")]


def test_db_backup_command_creates_restorable_db(monkeypatch, tmp_path):
    _isolate_db(monkeypatch, tmp_path)
    _insert_action("备份测试")
    output = tmp_path / "manual-backup.db"

    result = CliRunner().invoke(cli, ["db", "backup", "--output", str(output), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["path"] == str(output)
    assert payload["integrity_check"] == "ok"
    assert _action_summaries(output) == ["备份测试"]


def test_db_export_command_writes_sql_dump(monkeypatch, tmp_path):
    _isolate_db(monkeypatch, tmp_path)
    _insert_action("导出测试")
    output = tmp_path / "dump.sql"

    result = CliRunner().invoke(cli, ["db", "export", "--output", str(output), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["path"] == str(output)
    dump = output.read_text(encoding="utf-8")
    assert "CREATE TABLE actions" in dump
    assert "导出测试" in dump


def test_db_restore_requires_explicit_yes(monkeypatch, tmp_path):
    _isolate_db(monkeypatch, tmp_path)
    _insert_action("当前库")
    backup = tmp_path / "backup.db"
    sqlite3.connect(backup).close()

    result = CliRunner().invoke(cli, ["db", "restore", str(backup), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"] == "RESTORE_CONFIRMATION_REQUIRED"


def test_db_restore_from_backup_replaces_current_db_and_keeps_pre_restore_backup(monkeypatch, tmp_path):
    _isolate_db(monkeypatch, tmp_path)
    _insert_action("旧数据")
    backup = tmp_path / "restore-source.db"

    result = CliRunner().invoke(cli, ["db", "backup", "--output", str(backup), "--json"])
    assert result.exit_code == 0, result.output

    from nudge.state import log_action

    log_action("reminder", "新数据", "2026-05-06 09:00")

    result = CliRunner().invoke(cli, ["db", "restore", str(backup), "--yes", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["restored_from"] == str(backup)
    assert payload["pre_restore_backup"]
    assert _action_summaries(tmp_path / "nudge.db") == ["旧数据"]
    assert (tmp_path / "backups").exists()


def test_root_cli_lists_db_command(monkeypatch):
    monkeypatch.setattr("nudge.cli.load_config", lambda: {"llm": {"provider": "qwen"}})

    result = CliRunner().invoke(cli, ["--help"], prog_name="nudge")

    assert result.exit_code == 0
    assert "db" in result.output
