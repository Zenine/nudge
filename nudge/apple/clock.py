"""Apple Clock integration through macOS Shortcuts."""

import json
import re
import subprocess
import tempfile
from pathlib import Path

from nudge.config import DEFAULT_CLOCK_SHORTCUT_NAME

DEFAULT_CREATE_ALARM_SHORTCUT = DEFAULT_CLOCK_SHORTCUT_NAME
SHORTCUTS_BIN = "/usr/bin/shortcuts"


def check_clock_shortcut(
    shortcut_name: str = DEFAULT_CREATE_ALARM_SHORTCUT,
    timeout: int = 5,
) -> tuple[bool, str]:
    """Return whether the required Clock alarm Shortcut is installed."""
    try:
        result = subprocess.run(
            [SHORTCUTS_BIN, "list"],
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "macOS Shortcuts CLI not found at /usr/bin/shortcuts"
    except subprocess.TimeoutExpired:
        return False, "shortcuts list timed out"

    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "shortcuts list failed").strip()

    shortcuts = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    if shortcut_name not in shortcuts:
        return False, f'Shortcut "{shortcut_name}" not found'
    return True, f"Shortcut found: {shortcut_name}"


def create_alarm(
    time: str,
    label: str,
    shortcut_name: str = DEFAULT_CREATE_ALARM_SHORTCUT,
    enabled: bool = True,
    timeout: int = 30,
) -> tuple[bool, str]:
    """Create a Clock alarm by running a local Shortcut with JSON input."""
    if not _valid_alarm_time(time):
        return False, f"Alarm time must use HH:MM 24-hour format, got: {time}"

    payload = {"time": time, "label": label, "enabled": enabled}
    temp_path = _write_payload(payload)
    try:
        result = subprocess.run(
            [SHORTCUTS_BIN, "run", shortcut_name, "--input-path", str(temp_path)],
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "macOS Shortcuts CLI not found at /usr/bin/shortcuts"
    except subprocess.TimeoutExpired:
        return False, f'shortcuts run "{shortcut_name}" timed out'
    finally:
        temp_path.unlink(missing_ok=True)

    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "shortcuts run failed").strip()

    return True, make_clock_external_id(shortcut_name, time, label)


def make_clock_external_id(shortcut_name: str, time: str, label: str) -> str:
    """Build a local tracking id for Clock alarms created through Shortcuts."""
    clean_label = " ".join(str(label or "").split())
    return f"Clock::{shortcut_name}::{time}::{clean_label}"


def _write_payload(payload: dict) -> Path:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as temp:
        json.dump(payload, temp, ensure_ascii=False)
        temp.write("\n")
        return Path(temp.name)


def _valid_alarm_time(value: str) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
        return False
    hour, minute = (int(part) for part in value.split(":", 1))
    return 0 <= hour <= 23 and 0 <= minute <= 59
