"""Regression tests for AppleScript 字符串转义与 osascript 调用契约。"""

import subprocess


from nudge.apple.common import escape, run_applescript
from nudge.apple import notes


def test_escape_quotes_prevent_closing_applescript_string() -> None:
    payload = 'Lunch" & tell application "Finder" to delete every file & "'

    escaped = escape(payload)
    script = f'set itemName to "{escaped}"'

    assert '\\"' in escaped
    assert 'Lunch\\" & tell application \\"Finder\\"' in script
    assert 'Lunch" & tell application "Finder"' not in script


def test_escape_backslashes_are_escaped() -> None:
    assert escape(r"folder\child\file") == r"folder\\child\\file"


def test_escape_replaces_control_whitespace_with_spaces() -> None:
    assert escape("line one\nline two\rline three\tindented") == (
        "line one line two line three indented"
    )


def test_escape_combined_injection_payload_removes_raw_newlines_and_unescaped_quotes() -> None:
    payload = 'title"\ntell application "Calendar" to delete every event\n"tail'

    escaped = escape(payload)

    assert "\n" not in escaped
    assert "\r" not in escaped
    assert "\t" not in escaped
    assert '"' not in escaped.replace('\\"', '')
    assert '\\" tell application \\"Calendar\\"' in escaped


def test_create_note_converts_raw_multiline_body_to_html_before_applescript_escape(monkeypatch) -> None:
    escape_inputs: list[str | None] = []
    scripts: list[str] = []
    original_escape = notes.escape

    def recording_escape(text: str | None) -> str:
        escape_inputs.append(text)
        return original_escape(text)

    def fake_run_applescript(script: str, timeout: int = 30) -> tuple[bool, str]:
        scripts.append(script)
        return True, "Daily note"

    raw_body = "First paragraph\n\nSecond paragraph\n- keep this bullet"
    monkeypatch.setattr(notes, "escape", recording_escape)
    monkeypatch.setattr(notes, "run_applescript", fake_run_applescript)

    ok, result = notes.create_note(title="Daily note", body=raw_body)

    assert ok is True
    assert result == "Daily note"
    assert raw_body not in escape_inputs
    html_body = next(value for value in escape_inputs if value and value.startswith("<html>"))
    assert "First paragraph" in html_body
    assert "Second paragraph" in html_body
    assert "<li" in html_body and "keep this bullet" in html_body
    assert "First paragraph\n\nSecond paragraph" not in scripts[0]


def test_run_applescript_returns_failure_when_osascript_missing(monkeypatch) -> None:
    """非 macOS 环境缺少 osascript 时应返回契约元组而非抛异常。"""

    def fake_run(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "osascript")

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, message = run_applescript('display dialog "hi"')

    assert ok is False
    assert "osascript unavailable" in message
    assert "not found" in message


def test_run_applescript_returns_failure_on_os_error(monkeypatch) -> None:
    """osascript 存在但不可执行(权限等 OSError)时同样返回契约元组。"""

    def fake_run(*args, **kwargs):
        raise PermissionError(13, "Permission denied", "osascript")

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, message = run_applescript('display dialog "hi"')

    assert ok is False
    assert "osascript unavailable" in message
    assert "Permission denied" in message


def test_run_applescript_timeout_message_is_distinct_from_missing_binary(monkeypatch) -> None:
    """超时信息与缺少 osascript 的信息必须可区分。"""

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["osascript"], timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, message = run_applescript('display dialog "hi"', timeout=1)

    assert ok is False
    assert "timed out" in message
    assert "osascript unavailable" not in message
