"""Tests for database backup, export, and restore commands."""

import json
import hashlib
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


def test_db_backup_command_preserves_pre_migration_source(monkeypatch, tmp_path):
    """备份不能先执行 runtime 的 schema 初始化。"""
    _isolate_db(monkeypatch, tmp_path)
    source = tmp_path / "nudge.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE actions (id TEXT PRIMARY KEY, summary TEXT)")
        conn.execute("INSERT INTO actions VALUES ('legacy', '迁移前记录')")
    before = (source.stat().st_mtime_ns, hashlib.sha256(source.read_bytes()).hexdigest())
    monkeypatch.setattr(
        "nudge.state._get_conn",
        lambda: (_ for _ in ()).throw(AssertionError("backup must not initialize")),
    )
    output = tmp_path / "pre-migration.db"

    result = CliRunner().invoke(cli, ["db", "backup", "--output", str(output), "--json"])

    assert result.exit_code == 0, result.output
    assert (source.stat().st_mtime_ns, hashlib.sha256(source.read_bytes()).hexdigest()) == before
    assert not (tmp_path / "nudge.db-wal").exists()
    with sqlite3.connect(output) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(actions)")}
        assert "reminder_list" not in columns
        assert conn.execute("SELECT summary FROM actions").fetchone()[0] == "迁移前记录"


def test_db_backup_command_missing_source_does_not_create_database(monkeypatch, tmp_path):
    _isolate_db(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "nudge.state._get_conn",
        lambda: (_ for _ in ()).throw(AssertionError("backup must not initialize")),
    )

    result = CliRunner().invoke(cli, ["db", "backup", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == "DB_BACKUP_FAILED"
    assert not (tmp_path / "nudge.db").exists()
    assert not (tmp_path / "backups").exists()


def test_db_backup_command_rejects_uncheckpointed_wal(monkeypatch, tmp_path):
    _isolate_db(monkeypatch, tmp_path)
    source = tmp_path / "nudge.db"
    writer = sqlite3.connect(source)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("CREATE TABLE actions (id TEXT PRIMARY KEY)")
        writer.execute("INSERT INTO actions VALUES ('in-wal')")
        writer.commit()
        wal = tmp_path / "nudge.db-wal"
        assert wal.stat().st_size > 0
        before = (source.stat().st_mtime_ns, wal.stat().st_size)
        output = tmp_path / "unsafe.db"

        result = CliRunner().invoke(cli, ["db", "backup", "--output", str(output), "--json"])

        assert result.exit_code == 1
        assert "non-empty WAL" in json.loads(result.output)["detail"]
        assert not output.exists()
        assert (source.stat().st_mtime_ns, wal.stat().st_size) == before
    finally:
        writer.close()


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
