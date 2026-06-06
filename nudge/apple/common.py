"""Shared AppleScript utilities."""

import subprocess
from datetime import datetime


def escape(text: str | None, *, preserve_newlines: bool = False) -> str:
    """Escape string for safe embedding in AppleScript."""
    if not text:
        return ""
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    if preserve_newlines:
        return _escape_preserving_newlines(normalized)
    return _escape_fragment(normalized.replace("\n", " "))


def _escape_fragment(text: str) -> str:
    """Escape an AppleScript string fragment that contains no line breaks."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", " ")


def _escape_preserving_newlines(text: str) -> str:
    """Escape text while keeping line breaks readable in AppleScript."""
    parts: list[str] = []
    chunk: list[str] = []
    newline_count = 0

    def flush_chunk() -> None:
        if chunk:
            parts.append(_escape_fragment("".join(chunk)))
            chunk.clear()

    def flush_newlines() -> None:
        nonlocal newline_count
        if newline_count:
            parts.append('" & ' + " & ".join(["linefeed"] * newline_count) + ' & "')
            newline_count = 0

    for char in text:
        if char == "\n":
            flush_chunk()
            newline_count += 1
        else:
            flush_newlines()
            chunk.append(char)
    flush_chunk()
    flush_newlines()
    return "".join(parts)


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
