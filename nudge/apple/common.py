"""Shared AppleScript utilities."""

import subprocess
from datetime import datetime


def escape(text: str | None) -> str:
    """Escape string for safe embedding in AppleScript."""
    if not text:
        return ""
    return (text
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", " ")
            .replace("\r", " ")
            .replace("\t", " "))


def date_block(var_name: str, dt: datetime) -> str:
    """Generate AppleScript date construction block (locale-safe)."""
    return f"""set {var_name} to current date
set day of {var_name} to 1
set year of {var_name} to {dt.year}
set month of {var_name} to {dt.month}
set day of {var_name} to {dt.day}
set hours of {var_name} to {dt.hour}
set minutes of {var_name} to {dt.minute}
set seconds of {var_name} to 0"""


def run_applescript(script: str, timeout: int = 30) -> tuple[bool, str]:
    """Execute AppleScript and return (success, output/error)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "AppleScript execution timed out"
