"""Runtime warning/error log for user-repairable issues."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from nudge.config import resolve_state_dir

RUNTIME_LOG_RELATIVE_PATH = Path("logs") / "nudge-runtime.jsonl"
DEFAULT_RUNTIME_LOG_MAX_BYTES = 1024 * 1024
RUNTIME_LOG_ROTATED_FILE_COUNT = 3


def runtime_log_path(config: dict | None = None) -> Path:
    """Return the runtime JSONL log path for a config."""
    return resolve_state_dir(config) / RUNTIME_LOG_RELATIVE_PATH


def append_runtime_log(entry: dict, config: dict | None = None) -> Path:
    """Append one sanitized runtime log entry and return the log path."""
    path = runtime_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_runtime_log_if_needed(path, _runtime_log_max_bytes(config))
    payload = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        **_sanitize_entry(entry),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def log_warning(source: str, message: str, *, hint: str = "", config: dict | None = None) -> Path:
    """Record one warning intended to help users repair local setup issues."""
    return append_runtime_log(
        {
            "level": "WARN",
            "source": source,
            "message": message,
            "hint": hint,
        },
        config=config,
    )


def log_error_report(source: str, error, *, config: dict | None = None) -> Path:
    """Record an ErrorReport without storing raw provider or AppleScript output."""
    return append_runtime_log(
        {
            "level": "ERROR",
            "source": source,
            "code": getattr(error, "code", "ERROR"),
            "message": getattr(error, "title", str(error)),
            "detail": getattr(error, "detail", ""),
            "next_steps": list(getattr(error, "next_steps", ()) or ()),
        },
        config=config,
    )


def log_doctor_checks(checks: Iterable, *, config: dict | None = None) -> Path | None:
    """Record WARN/FAIL doctor checks and return the log path when anything was written."""
    log_path = None
    for check in checks:
        status = getattr(check, "status", "")
        if status not in {"WARN", "FAIL"}:
            continue
        log_path = append_runtime_log(
            {
                "level": "ERROR" if status == "FAIL" else "WARN",
                "source": f"doctor.{getattr(check, 'name', 'unknown')}",
                "message": getattr(check, "message", ""),
                "hint": getattr(check, "hint", ""),
            },
            config=config,
        )
    return log_path


def _rotate_runtime_log_if_needed(path: Path, max_bytes: int) -> None:
    if not path.exists() or path.stat().st_size <= max_bytes:
        return

    oldest = path.with_name(f"{path.name}.{RUNTIME_LOG_ROTATED_FILE_COUNT}")
    if oldest.exists():
        oldest.unlink()

    for index in range(RUNTIME_LOG_ROTATED_FILE_COUNT - 1, 0, -1):
        rotated = path.with_name(f"{path.name}.{index}")
        if rotated.exists():
            rotated.replace(path.with_name(f"{path.name}.{index + 1}"))

    path.replace(path.with_name(f"{path.name}.1"))


def _runtime_log_max_bytes(config: dict | None) -> int:
    value = ((config or {}).get("runtime_log") or {}).get("max_bytes", DEFAULT_RUNTIME_LOG_MAX_BYTES)
    try:
        max_bytes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_RUNTIME_LOG_MAX_BYTES
    return max_bytes if max_bytes >= 0 else DEFAULT_RUNTIME_LOG_MAX_BYTES


def _sanitize_entry(entry: dict) -> dict:
    """Keep logs useful for repair while avoiding raw secrets or huge payloads."""
    sanitized = {}
    for key, value in entry.items():
        if value is None:
            continue
        if isinstance(value, str):
            sanitized[key] = value[:2000]
        elif isinstance(value, (int, float, bool)):
            sanitized[key] = value
        elif isinstance(value, list):
            sanitized[key] = [str(item)[:1000] for item in value[:10]]
        else:
            sanitized[key] = str(value)[:2000]
    return sanitized
