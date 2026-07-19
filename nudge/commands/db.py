"""Database maintenance commands for local Nudge SQLite state."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import click

import nudge.state as state
from nudge.json_contract import versioned_payload


@click.group("db")
def db_command():
    """Backup, export, and restore the local SQLite database."""


@db_command.command("backup")
@click.option("--output", "-o", type=click.Path(dir_okay=False), default=None, help="Destination .db path")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON")
def backup_command(output: str | None, json_output: bool):
    """Create a consistent SQLite .db backup."""
    try:
        path = backup_database(Path(output).expanduser() if output else None)
        payload = versioned_payload({
            "ok": True,
            "path": str(path),
            "source": str(state.DB_PATH),
            "integrity_check": _integrity_check(path),
        })
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        payload = versioned_payload({"ok": False, "error": "DB_BACKUP_FAILED", "detail": str(exc)})
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)
    _emit(payload, json_output)


@db_command.command("export")
@click.option("--output", "-o", type=click.Path(dir_okay=False), default=None, help="Destination .sql path")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON")
def export_command(output: str | None, json_output: bool):
    """Export the SQLite database as a portable SQL dump."""
    try:
        path = export_database(Path(output).expanduser() if output else None)
        payload = versioned_payload({"ok": True, "path": str(path), "source": str(state.DB_PATH)})
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        payload = versioned_payload({"ok": False, "error": "DB_EXPORT_FAILED", "detail": str(exc)})
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)
    _emit(payload, json_output)


@db_command.command("restore")
@click.argument("source", type=click.Path(exists=True, dir_okay=False))
@click.option("--yes", is_flag=True, help="Required confirmation for replacing the current DB")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON")
def restore_command(source: str, yes: bool, json_output: bool):
    """Restore the current SQLite database from a .db backup or .sql dump."""
    if not yes:
        payload = versioned_payload({
            "ok": False,
            "error": "RESTORE_CONFIRMATION_REQUIRED",
            "detail": "Restore replaces the current Nudge database. Re-run with --yes after confirming the source.",
        })
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)

    try:
        result = restore_database(Path(source).expanduser())
        payload = versioned_payload({"ok": True, **result})
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        payload = versioned_payload({"ok": False, "error": "DB_RESTORE_FAILED", "detail": str(exc)})
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)
    _emit(payload, json_output)


def backup_database(output: Path | None = None, *, initialize: bool = True) -> Path:
    """Create a consistent .db copy using SQLite's online backup API."""
    source_identity = None
    if initialize:
        _ensure_db_exists()
    elif not state.DB_PATH.is_file():
        raise FileNotFoundError(state.DB_PATH)
    else:
        source_identity = _backup_source_identity()
    destination = output or (
        state.STATE_DIR / "backups" / f"nudge-{_timestamp()}-{uuid4().hex}.db"
    )
    source_resolved = state.DB_PATH.resolve()
    destination_resolved = destination.resolve()
    if destination_resolved == source_resolved:
        raise ValueError("backup destination must differ from source database")
    if os.path.lexists(destination):
        try:
            if os.path.samefile(destination, state.DB_PATH):
                raise ValueError("backup destination must differ from source database")
        except FileNotFoundError:
            pass
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.partial-{uuid4().hex}")
    staging_created = False

    try:
        staging_fd = os.open(staging, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        staging_created = True
        os.close(staging_fd)
        os.chmod(staging, 0o600)
        source_database = str(state.DB_PATH)
        source_connect_kwargs = {}
        if source_identity is not None:
            source_database = f"{state.DB_PATH.resolve().as_uri()}?mode=ro&immutable=1"
            source_connect_kwargs = {"uri": True}
        with sqlite3.connect(source_database, **source_connect_kwargs) as source, sqlite3.connect(str(staging)) as target:
            if source_identity is not None:
                _assert_backup_source_unchanged(source_identity)
            source.backup(target)
            if source_identity is not None:
                _assert_backup_source_unchanged(source_identity)

        if _integrity_check(staging) != "ok":
            raise RuntimeError(f"backup integrity check failed: {destination}")
        os.link(staging, destination)
    finally:
        if staging_created and staging.exists():
            staging.unlink()
    return destination


def _backup_source_identity() -> tuple:
    """Snapshot the source DB and sidecars without opening or recovering SQLite."""
    wal_path = state.DB_PATH.with_name(f"{state.DB_PATH.name}-wal")
    shm_path = state.DB_PATH.with_name(f"{state.DB_PATH.name}-shm")
    journal_path = state.DB_PATH.with_name(f"{state.DB_PATH.name}-journal")
    database_identity = state._readonly_db_identity(state.DB_PATH)
    wal_identity = state._readonly_optional_identity(wal_path)
    shm_identity = state._readonly_optional_identity(shm_path)
    journal_identity = state._readonly_optional_identity(journal_path)
    if wal_identity is not None and wal_identity[2] > 0:
        raise sqlite3.OperationalError("backup source has a non-empty WAL")
    if journal_identity is not None and journal_identity[2] > 0:
        raise sqlite3.OperationalError("backup source has a non-empty rollback journal")
    return database_identity, wal_identity, shm_identity, journal_identity


def _assert_backup_source_unchanged(expected: tuple) -> None:
    if _backup_source_identity() != expected:
        raise sqlite3.OperationalError("backup source changed during backup")


def export_database(output: Path | None = None) -> Path:
    """Write a SQL dump of the current database."""
    _ensure_db_exists()
    destination = output or state.STATE_DIR / "exports" / f"nudge-{_timestamp()}.sql"
    destination.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(state.DB_PATH)) as conn:
        dump = "\n".join(conn.iterdump())
    destination.write_text(dump + "\n", encoding="utf-8")
    return destination


def restore_database(source: Path) -> dict:
    """Replace the current DB after creating a pre-restore backup."""
    if not source.exists():
        raise FileNotFoundError(source)

    _ensure_db_exists()
    pre_restore_backup = backup_database(state.STATE_DIR / "backups" / f"nudge-before-restore-{_timestamp()}.db")
    staging = state.STATE_DIR / f".restore-{_timestamp()}.db"
    staging.parent.mkdir(parents=True, exist_ok=True)

    try:
        if source.suffix.lower() == ".sql":
            _restore_sql_to_db(source, staging)
        else:
            if _integrity_check(source) != "ok":
                raise RuntimeError(f"source integrity check failed: {source}")
            with sqlite3.connect(str(source)) as source_conn, sqlite3.connect(str(staging)) as staging_conn:
                source_conn.backup(staging_conn)

        if _integrity_check(staging) != "ok":
            raise RuntimeError(f"staged restore integrity check failed: {staging}")

        _checkpoint_current_db()
        os.replace(staging, state.DB_PATH)
        _remove_sidecar_files(state.DB_PATH)
    finally:
        if staging.exists():
            staging.unlink()

    return {
        "restored_from": str(source),
        "path": str(state.DB_PATH),
        "pre_restore_backup": str(pre_restore_backup),
        "integrity_check": _integrity_check(state.DB_PATH),
    }


def _restore_sql_to_db(source: Path, destination: Path) -> None:
    if destination.exists():
        destination.unlink()
    with sqlite3.connect(str(destination)) as conn:
        conn.executescript(source.read_text(encoding="utf-8"))
        conn.commit()


def _ensure_db_exists() -> None:
    with state._get_conn():
        pass


def _checkpoint_current_db() -> None:
    if not state.DB_PATH.exists():
        return
    with sqlite3.connect(str(state.DB_PATH)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _remove_sidecar_files(db_path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{db_path}{suffix}")
        if sidecar.exists():
            sidecar.unlink()


def _integrity_check(path: Path) -> str:
    with sqlite3.connect(str(path)) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row else ""


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _emit(payload: dict, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    if payload.get("ok"):
        if "restored_from" in payload:
            click.echo(f"已恢复数据库: {payload['path']}")
            click.echo(f"恢复来源: {payload['restored_from']}")
            click.echo(f"恢复前备份: {payload['pre_restore_backup']}")
        else:
            click.echo(payload["path"])
        return

    click.echo(f"{payload['error']}: {payload.get('detail', '')}")
