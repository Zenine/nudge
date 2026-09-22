"""Tests for nudge.apple.common module."""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from nudge.apple.common import date_block, escape, run_applescript


class TestEscape:
    def test_empty_string(self):
        assert escape("") == ""

    def test_none_returns_empty(self):
        assert escape(None) == ""

    def test_plain_text(self):
        assert escape("hello world") == "hello world"

    def test_double_quotes(self):
        assert escape('say "hello"') == 'say \\"hello\\"'

    def test_backslash(self):
        assert escape("path\\to\\file") == "path\\\\to\\\\file"

    def test_newlines_stripped(self):
        """Newlines are replaced with spaces to prevent AppleScript injection."""
        assert escape("line1\nline2\rline3") == "line1 line2 line3"

    def test_tabs_stripped(self):
        assert escape("col1\tcol2") == "col1 col2"

    def test_combined(self):
        result = escape('He said "hi"\nand left\\')
        assert result == 'He said \\"hi\\" and left\\\\'

    def test_chinese_text(self):
        assert escape("下午两点开会") == "下午两点开会"




class TestAppleScriptEscapingGeneratedScripts:
    def test_calendar_create_escapes_quote_newline_and_script_concatenation(self, monkeypatch):
        from nudge.apple import calendar

        captured = {}

        def fake_run(script, timeout=30):
            captured["script"] = script
            captured["timeout"] = timeout
            return True, "uid-1"

        monkeypatch.setattr(calendar, "run_applescript", fake_run)

        malicious = '会议" & do shell script "touch /tmp/nudge-pwn" & "\n下一行'
        ok, result = calendar.create_calendar_event(
            summary=malicious,
            start=datetime(2026, 7, 6, 9, 0),
            end=datetime(2026, 7, 6, 10, 0),
            calendar_name='个人" & do shell script "touch /tmp/cal-pwn" & "',
            location='A" & do shell script "touch /tmp/loc-pwn" & "',
            notes='备注" & do shell script "touch /tmp/note-pwn" & "\r换行',
        )

        assert ok is True
        assert result == "uid-1"
        script = captured["script"]
        assert 'summary:"会议\\" & do shell script \\"touch /tmp/nudge-pwn\\" & \\" 下一行"' in script
        assert 'tell calendar "个人\\" & do shell script \\"touch /tmp/cal-pwn\\" & \\""' in script
        assert 'location:"A\\" & do shell script \\"touch /tmp/loc-pwn\\" & \\""' in script
        assert 'description:"备注\\" & do shell script \\"touch /tmp/note-pwn\\" & \\" 换行"' in script
        assert re.search(r'(?<!\\)" & do shell script', script) is None
        assert re.search(r'touch /tmp/nudge-pwn(?<!\\)" &', script) is None

    def test_reminder_applescript_fallback_escapes_title_and_list(self, monkeypatch):
        from nudge.apple import reminders

        captured = {}

        def fake_run(script, timeout=30):
            captured["script"] = script
            captured["timeout"] = timeout
            return True, "done"

        monkeypatch.setattr(reminders, "run_applescript", fake_run)

        malicious_name = '买菜" & do shell script "touch /tmp/rem-pwn" & "\n补充'
        malicious_list = '日常" & do shell script "touch /tmp/list-pwn" & "'
        ok, result = reminders.complete_reminder(
            malicious_name,
            malicious_list,
            timeout=8,
            prefer_eventkit=False,
        )

        assert ok is True
        assert result == "done"
        script = captured["script"]
        assert 'tell list "日常\\" & do shell script \\"touch /tmp/list-pwn\\" & \\""' in script
        assert 'if name of r is "买菜\\" & do shell script \\"touch /tmp/rem-pwn\\" & \\" 补充"' in script
        assert re.search(r'(?<!\\)" & do shell script', script) is None

    def test_note_create_escapes_title_folder_and_html_body(self, monkeypatch):
        from nudge.apple import notes

        captured = {}

        def fake_run(script, timeout=30):
            captured["script"] = script
            captured["timeout"] = timeout
            return True, "标题"

        monkeypatch.setattr(notes, "run_applescript", fake_run)

        ok, result = notes.create_note(
            title='标题" & do shell script "touch /tmp/title-pwn" & "',
            body='正文" & do shell script "touch /tmp/body-pwn" & "\n- item',
            folder_name='Nudge" & do shell script "touch /tmp/folder-pwn" & "',
            timeout=9,
        )

        assert ok is True
        assert result == "标题"
        script = captured["script"]
        assert 'set targetFolderName to "Nudge\\" & do shell script \\"touch /tmp/folder-pwn\\" & \\""' in script
        assert 'name:"标题\\" & do shell script \\"touch /tmp/title-pwn\\" & \\""' in script
        assert 'touch /tmp/body-pwn' in script
        assert re.search(r'(?<!\\)" & do shell script', script) is None

    def test_escape_removes_unicode_line_separators(self):
        assert escape('a\u2028b\u2029c') == 'a b c'


class TestDateBlock:
    def test_basic_date(self):
        dt = datetime(2026, 4, 14, 10, 30, 0)
        block = date_block("testDate", dt)
        assert "set testDate to current date" in block
        assert "set year of testDate to 2026" in block
        assert "set month of testDate to 4" in block
        assert "set day of testDate to 14" in block
        assert "set hours of testDate to 10" in block
        assert "set minutes of testDate to 30" in block
        assert "set seconds of testDate to 0" in block

    def test_midnight(self):
        dt = datetime(2026, 1, 1, 0, 0, 0)
        block = date_block("d", dt)
        assert "set hours of d to 0" in block
        assert "set minutes of d to 0" in block


class TestAppleListDiagnostics:
    def test_list_calendars_prefers_eventkit_without_applescript(self, monkeypatch):
        from nudge.apple import calendar

        calls = []

        monkeypatch.setattr(
            calendar,
            "list_calendars_eventkit",
            lambda timeout=5: calls.append(("eventkit", timeout)) or (True, ["Family", "Dad"]),
        )
        monkeypatch.setattr(
            calendar,
            "run_applescript",
            lambda script, timeout=30: (_ for _ in ()).throw(AssertionError("AppleScript should not run")),
        )

        ok, names = calendar.list_calendars(timeout=7)

        assert ok is True
        assert names == ["Family", "Dad"]
        assert calls == [("eventkit", 7)]

    def test_list_calendars_falls_back_to_applescript_bulk_name_query(self, monkeypatch):
        from nudge.apple import calendar

        captured = {}

        monkeypatch.setattr(
            calendar,
            "list_calendars_eventkit",
            lambda timeout=5: (False, "EventKit denied"),
        )
        open_calls = []
        monkeypatch.setattr(calendar, "open_calendar_app", lambda timeout=5: open_calls.append(timeout))

        def fake_run(script, timeout=30):
            captured["script"] = script
            captured["timeout"] = timeout
            return True, "Family\nDad\n"

        monkeypatch.setattr(calendar, "run_applescript", fake_run)

        ok, names = calendar.list_calendars()

        assert ok is True
        assert names == ["Family", "Dad"]
        assert "launch" in captured["script"]
        assert "name of calendars" in captured["script"]
        assert "text item delimiters" in captured["script"]
        assert "repeat with cal" not in captured["script"]
        assert captured["timeout"] == 5
        assert open_calls == [5]

    def test_list_reminder_lists_prefers_eventkit_without_applescript(self, monkeypatch):
        from nudge.apple import reminders

        calls = []

        monkeypatch.setattr(
            reminders,
            "list_reminder_lists_eventkit",
            lambda timeout=5: calls.append(("eventkit", timeout)) or (True, ["日常", "家庭"]),
        )
        monkeypatch.setattr(
            reminders,
            "run_applescript",
            lambda script, timeout=30: (_ for _ in ()).throw(AssertionError("AppleScript should not run")),
        )

        ok, names = reminders.list_reminder_lists(timeout=7)

        assert ok is True
        assert names == ["日常", "家庭"]
        assert calls == [("eventkit", 7)]

    def test_list_reminder_lists_falls_back_to_applescript(self, monkeypatch):
        from nudge.apple import reminders

        captured = {}

        monkeypatch.setattr(
            reminders,
            "list_reminder_lists_eventkit",
            lambda timeout=5: (False, "EventKit denied"),
        )

        def fake_run(script, timeout=30):
            captured["script"] = script
            captured["timeout"] = timeout
            return True, "日常\n家庭\n"

        monkeypatch.setattr(reminders, "run_applescript", fake_run)

        ok, names = reminders.list_reminder_lists()

        assert ok is True
        assert names == ["日常", "家庭"]
        assert '& "\\n"' in captured["script"]
        assert captured["timeout"] == 5

    def test_list_reminder_lists_eventkit_invokes_swift_list_mode(self, monkeypatch):
        from nudge.apple import reminders

        captured = {}

        def fake_run(cmd, capture_output, text, timeout):
            captured["cmd"] = cmd
            captured["timeout"] = timeout
            return SimpleNamespace(returncode=0, stdout="日常\n家庭\n", stderr="")

        monkeypatch.setattr(reminders.subprocess, "run", fake_run)

        ok, names = reminders.list_reminder_lists_eventkit(timeout=7)

        assert ok is True
        assert names == ["日常", "家庭"]
        assert captured["cmd"] == ["/usr/bin/swift", str(reminders.EVENTKIT_DUE_TODAY_SCRIPT), "--lists"]
        assert captured["timeout"] == 7

    def test_probe_reminders_read_checks_objects_not_just_lists(self, monkeypatch):
        from nudge.apple import reminders

        captured = {}
        monkeypatch.setattr(
            reminders,
            "query_due_today",
            lambda list_name=None, timeout=30: captured.update({"list_name": list_name, "timeout": timeout}) or (
                True,
                [{"name": "买菜", "due_time": "09:00", "list": "日常"}],
            ),
        )

        ok, message = reminders.probe_reminders_read("日常", timeout=7)

        assert ok is True
        assert message == "due_today query readable; count=1"
        assert captured["list_name"] == "日常"
        assert captured["timeout"] == 7

    def test_probe_reminders_read_reports_timeout(self, monkeypatch):
        from nudge.apple import reminders

        monkeypatch.setattr(
            reminders,
            "query_due_today",
            lambda list_name=None, timeout=30: (False, "AppleScript execution timed out"),
        )

        assert reminders.probe_reminders_read("日常") == (False, "AppleScript execution timed out")

    def test_query_due_today_eventkit_parses_rows_and_passes_list_name(self, monkeypatch):
        from nudge.apple import reminders

        captured = {}

        def fake_run(cmd, capture_output, text, timeout):
            captured["cmd"] = cmd
            captured["timeout"] = timeout
            return SimpleNamespace(returncode=0, stdout="买菜\t09:00\t日常\n", stderr="")

        monkeypatch.setattr(reminders.subprocess, "run", fake_run)

        ok, result = reminders.query_due_today_eventkit(list_name="日常", timeout=7)

        assert ok is True
        assert result == [{"name": "买菜", "due_time": "09:00", "list": "日常"}]
        assert captured["cmd"][0] == "/usr/bin/swift"
        assert captured["cmd"][-1] == "日常"
        assert captured["timeout"] == 7

    def test_query_due_today_eventkit_reports_timeout(self, monkeypatch):
        from nudge.apple import reminders

        def fake_run(cmd, capture_output, text, timeout):
            raise subprocess.TimeoutExpired(cmd, timeout)

        monkeypatch.setattr(reminders.subprocess, "run", fake_run)

        assert reminders.query_due_today_eventkit(list_name="日常") == (False, "EventKit due-today query timed out")

    def test_reminders_default_read_timeout_covers_eventkit_helper_wait(self):
        from nudge.apple import reminders

        assert reminders.DEFAULT_READ_TIMEOUT >= 30

    def test_run_eventkit_mutation_invokes_swift_helper(self, monkeypatch):
        from nudge.apple import reminders

        captured = {}

        def fake_run(cmd, capture_output, text, timeout):
            captured["cmd"] = cmd
            captured["timeout"] = timeout
            return SimpleNamespace(returncode=0, stdout="matched=1 changed=1\n", stderr="")

        monkeypatch.setattr(reminders.subprocess, "run", fake_run)

        assert reminders._run_eventkit_mutation("complete", "买菜", "日常", timeout=9) == (
            True,
            "matched=1 changed=1",
        )
        assert captured["cmd"][:2] == ["/usr/bin/swift", str(reminders.EVENTKIT_MUTATE_SCRIPT)]
        assert captured["cmd"][2:] == ["complete", "日常", "买菜"]
        assert captured["timeout"] == 9

    def test_run_eventkit_mutation_reports_timeout(self, monkeypatch):
        from nudge.apple import reminders

        def fake_run(cmd, capture_output, text, timeout):
            raise subprocess.TimeoutExpired(cmd, timeout)

        monkeypatch.setattr(reminders.subprocess, "run", fake_run)

        assert reminders._run_eventkit_mutation("delete", "买菜", "日常", timeout=3) == (
            False,
            "EventKit delete reminder timed out",
        )

    def test_complete_reminder_prefers_eventkit(self, monkeypatch):
        from nudge.apple import reminders

        calls = []
        monkeypatch.setattr(
            reminders,
            "_run_eventkit_mutation",
            lambda operation, name, list_name, timeout=30, due_date=None: calls.append((operation, name, list_name, timeout, due_date)) or (
                True,
                "matched=1 changed=1",
            ),
        )
        monkeypatch.setattr(reminders, "run_applescript", lambda script, timeout=30: (_ for _ in ()).throw(AssertionError("AppleScript should not run")))

        assert reminders.complete_reminder("买菜", "日常", timeout=6, due_date="2026-05-09 09:00") == (True, "matched=1 changed=1")
        assert calls == [("complete", "买菜", "日常", 6, "2026-05-09 09:00")]


    def test_complete_reminders_batch_invokes_one_eventkit_helper_and_parses_results(self, monkeypatch):
        from nudge.apple import reminders

        calls = []

        def fake_mutation(operation, name, list_name, timeout=30, **kwargs):
            calls.append((operation, name, list_name, timeout, kwargs))
            payload = json.loads(Path(name).read_text(encoding="utf-8"))
            assert payload == [
                {
                    "id": "late",
                    "titles": ["不要熬夜"],
                    "due_date": "2026-04-27 23:00",
                },
                {
                    "id": "latest",
                    "titles": ["最晚上床 2026-04-27 23:30", "最晚上床"],
                    "due_date": "2026-04-27 23:30",
                },
            ]
            return True, "late\ttrue\tmatched=1 changed=1\nlatest\tfalse\tPrecise reminder match expected 1, found 2"

        monkeypatch.setattr(reminders, "_run_eventkit_mutation", fake_mutation)

        result = reminders.complete_reminders_batch(
            [
                {"id": "late", "titles": ["不要熬夜"], "due_date": "2026-04-27 23:00"},
                {"id": "latest", "titles": ["最晚上床 2026-04-27 23:30", "最晚上床"], "due_date": "2026-04-27 23:30"},
            ],
            "日常",
            timeout=9,
        )

        assert result == {
            "late": (True, "matched=1 changed=1"),
            "latest": (False, "Precise reminder match expected 1, found 2"),
        }
        assert len(calls) == 1
        assert calls[0][0] == "complete-batch"
        assert calls[0][2] == "日常"
        assert calls[0][3] == 9

    def test_create_reminder_with_external_id_uses_eventkit_and_marker(self, monkeypatch):
        from datetime import datetime

        from nudge.apple import reminders

        calls = []
        def fake_mutation(*args, **kwargs):
            calls.append((args, kwargs))
            return True, "created"

        monkeypatch.setattr(reminders, "_run_eventkit_mutation", fake_mutation)
        monkeypatch.setattr(
            reminders,
            "run_applescript",
            lambda script, timeout=30: (_ for _ in ()).throw(AssertionError("AppleScript should not run")),
        )

        assert reminders.create_reminder(
            name="买菜",
            due_date=datetime(2026, 5, 9, 9, 0),
            list_name="日常",
            body="带袋子",
            external_id="nudge://reminder/abc",
        ) == (True, "nudge://reminder/abc")
        assert calls == [((
            "create",
            "买菜",
            "日常",
        ), {
            "timeout": 30,
            "due_date": "2026-05-09 09:00",
            "body": "带袋子\n\nNudge-ID: nudge://reminder/abc",
            "priority": 0,
            "remind_date": "2026-05-09 09:00",
            "external_id": "nudge://reminder/abc",
        })]

    def test_create_reminder_notify_false_omits_eventkit_alarm(self, monkeypatch):
        from nudge.apple import reminders

        calls = []
        monkeypatch.setattr(
            reminders,
            "_run_eventkit_mutation",
            lambda *args, **kwargs: calls.append((args, kwargs)) or (True, "created"),
        )

        assert reminders.create_reminder(
            name="仅作截止记录",
            due_date=datetime(2026, 7, 7, 9, 0),
            list_name="日常",
            notify=False,
            external_id="nudge://reminder/no-alarm",
        ) == (True, "nudge://reminder/no-alarm")
        assert calls[0][1]["remind_date"] == ""

    def test_create_reminder_notify_false_omits_applescript_alarm(self, monkeypatch):
        from nudge.apple import reminders

        captured = {}
        monkeypatch.setattr(
            reminders,
            "run_applescript",
            lambda script, timeout=30: captured.update(script=script, timeout=timeout) or (True, "created"),
        )

        assert reminders.create_reminder(
            name="仅作截止记录",
            due_date=datetime(2026, 7, 7, 9, 0),
            list_name="日常",
            notify=False,
        ) == (True, "created")
        assert "remind me date" not in captured["script"]

    def test_create_reminder_preserves_legacy_positional_timeout_and_external_id(self, monkeypatch):
        from nudge.apple import reminders

        calls = []
        monkeypatch.setattr(
            reminders,
            "_run_eventkit_mutation",
            lambda *args, **kwargs: calls.append((args, kwargs)) or (True, "created"),
        )

        result = reminders.create_reminder(
            "买菜",
            datetime(2026, 7, 7, 9, 0),
            "日常",
            None,
            0,
            None,
            17,
            "nudge://reminder/legacy",
        )

        assert result == (True, "nudge://reminder/legacy")
        assert calls[0][1]["timeout"] == 17

    def test_complete_reminder_by_external_id_uses_eventkit_id_match(self, monkeypatch):
        from nudge.apple import reminders

        calls = []
        monkeypatch.setattr(
            reminders,
            "_run_eventkit_mutation",
            lambda *args, **kwargs: calls.append((args, kwargs)) or (True, "matched=1 changed=1"),
        )

        assert reminders.complete_reminder_by_external_id("nudge://reminder/abc", "日常", timeout=6) == (
            True,
            "matched=1 changed=1",
        )
        assert calls == [(("complete-id", "nudge://reminder/abc", "日常"), {"timeout": 6, "external_id": "nudge://reminder/abc"})]

    def test_set_reminder_external_id_uses_precise_eventkit_mutation(self, monkeypatch):
        from nudge.apple import reminders

        calls = []
        monkeypatch.setattr(
            reminders,
            "_run_eventkit_mutation",
            lambda *args, **kwargs: calls.append((args, kwargs)) or (True, "matched=1 changed=1"),
        )

        assert reminders.set_reminder_external_id(
            "买菜",
            "日常",
            "2026-05-09 09:00",
            "nudge://reminder/abc",
            timeout=6,
        ) == (True, "matched=1 changed=1")
        assert calls == [(("set-id", "买菜", "日常"), {
            "timeout": 6,
            "due_date": "2026-05-09 09:00",
            "external_id": "nudge://reminder/abc",
        })]

    def test_complete_reminder_eventkit_precise_failure_does_not_fallback_to_applescript(self, monkeypatch):
        from nudge.apple import reminders

        calls = []
        monkeypatch.setattr(
            reminders,
            "_run_eventkit_mutation",
            lambda *args, **kwargs: calls.append((args, kwargs))
            or (False, "Precise reminder match expected 1, found 2"),
        )
        monkeypatch.setattr(
            reminders,
            "run_applescript",
            lambda script, timeout=30: (_ for _ in ()).throw(AssertionError("AppleScript fallback would be broad")),
        )

        assert reminders.complete_reminder("买菜", "日常") == (
            False,
            "EventKit failed for precise reminder completion: Precise reminder match expected 1, found 2",
        )
        assert calls == [(("complete", "买菜", "日常"), {"timeout": 30, "due_date": None})]

    def test_delete_reminder_eventkit_precise_failure_does_not_fallback_to_applescript(self, monkeypatch):
        from nudge.apple import reminders

        calls = []
        monkeypatch.setattr(
            reminders,
            "_run_eventkit_mutation",
            lambda *args, **kwargs: calls.append((args, kwargs))
            or (False, "Precise reminder match expected 1, found 2"),
        )
        monkeypatch.setattr(
            reminders,
            "run_applescript",
            lambda script, timeout=30: (_ for _ in ()).throw(AssertionError("AppleScript fallback would be broad")),
        )

        assert reminders.delete_reminder("买菜", "日常") == (
            False,
            "EventKit failed for precise reminder deletion: Precise reminder match expected 1, found 2",
        )
        assert calls == [(("delete", "买菜", "日常"), {"timeout": 30, "due_date": None})]

    def test_delete_reminder_passes_due_date_to_eventkit(self, monkeypatch):
        from nudge.apple import reminders

        calls = []
        monkeypatch.setattr(
            reminders,
            "_run_eventkit_mutation",
            lambda *args, **kwargs: calls.append((args, kwargs)) or (True, "matched=1 changed=1"),
        )
        monkeypatch.setattr(
            reminders,
            "run_applescript",
            lambda script, timeout=30: (_ for _ in ()).throw(AssertionError("AppleScript should not run")),
        )

        assert reminders.delete_reminder("买菜", "日常", timeout=6, due_date="2026-05-09 09:00") == (
            True,
            "matched=1 changed=1",
        )
        assert calls == [(("delete", "买菜", "日常"), {"timeout": 6, "due_date": "2026-05-09 09:00"})]

    def test_complete_reminder_falls_back_to_applescript_with_combined_error(self, monkeypatch):
        from nudge.apple import reminders

        monkeypatch.setattr(reminders, "_run_eventkit_mutation", lambda *args, **kwargs: (False, "EventKit denied"))
        monkeypatch.setattr(reminders, "run_applescript", lambda script, timeout=30: (False, "AppleScript execution timed out"))

        assert reminders.complete_reminder("买菜", "日常") == (
            False,
            "EventKit failed: EventKit denied; AppleScript failed: AppleScript execution timed out",
        )

    def test_delete_reminder_prefers_eventkit(self, monkeypatch):
        from nudge.apple import reminders

        calls = []
        monkeypatch.setattr(
            reminders,
            "_run_eventkit_mutation",
            lambda operation, name, list_name, timeout=30, due_date=None: calls.append((operation, name, list_name, timeout, due_date)) or (
                True,
                "matched=1 changed=1",
            ),
        )
        monkeypatch.setattr(reminders, "run_applescript", lambda script, timeout=30: (_ for _ in ()).throw(AssertionError("AppleScript should not run")))

        assert reminders.delete_reminder("买菜", "日常", timeout=6) == (True, "matched=1 changed=1")
        assert calls == [("delete", "买菜", "日常", 6, None)]

    def test_delete_reminder_can_force_applescript_backend(self, monkeypatch):
        from nudge.apple import reminders

        captured = {}

        def fake_run(script, timeout=30):
            captured["script"] = script
            captured["timeout"] = timeout
            return True, "deleted"

        monkeypatch.setattr(reminders, "run_applescript", fake_run)

        assert reminders.delete_reminder("买菜", "日常", timeout=8, prefer_eventkit=False) == (True, "deleted")
        assert 'tell list "日常"' in captured["script"]
        assert 'if name of r is "买菜"' in captured["script"]
        assert captured["timeout"] == 8

    def test_get_due_today_raises_read_error_with_bounded_timeout(self, monkeypatch):
        from nudge.apple import reminders

        captured = {}

        def fake_run(script, timeout=30):
            captured["timeout"] = timeout
            return False, "AppleScript execution timed out"

        monkeypatch.setattr(reminders, "run_applescript", fake_run)
        monkeypatch.setattr(reminders, "query_due_today_eventkit", lambda list_name=None, timeout=30: (False, "EventKit unavailable"))

        with pytest.raises(RuntimeError, match="EventKit unavailable"):
            reminders.get_due_today()
        assert captured["timeout"] == reminders.DEFAULT_READ_TIMEOUT

    def test_query_due_today_returns_error_instead_of_hiding_timeout(self, monkeypatch):
        from nudge.apple import reminders

        monkeypatch.setattr(reminders, "query_due_today_eventkit", lambda list_name=None, timeout=30: (False, "EventKit unavailable"))
        monkeypatch.setattr(reminders, "run_applescript", lambda script, timeout=30: (False, "AppleScript execution timed out"))

        assert reminders.query_due_today(list_name="日常") == (
            False,
            "EventKit failed: EventKit unavailable; AppleScript failed: AppleScript execution timed out",
        )

    def test_query_due_today_can_force_applescript_backend(self, monkeypatch):
        from nudge.apple import reminders

        captured = {}

        def fake_run(script, timeout=30):
            captured["script"] = script
            captured["timeout"] = timeout
            return True, "买菜\t09:00\t日常\n"

        monkeypatch.setattr(reminders, "run_applescript", fake_run)

        ok, result = reminders.query_due_today(list_name="日常", timeout=7, prefer_eventkit=False)

        assert ok is True
        assert result == [{"name": "买菜", "due_time": "09:00", "list": "日常"}]
        assert 'set lst to list "日常"' in captured["script"]
        assert "due date >= startRef" in captured["script"]
        assert captured["timeout"] == 7

    def test_get_reminders_raises_on_applescript_failure_with_bounded_timeout(self, monkeypatch):
        from nudge.apple import reminders

        captured = {}

        def fake_run(script, timeout=30):
            captured["timeout"] = timeout
            return False, "AppleScript execution timed out"

        monkeypatch.setattr(reminders, "run_applescript", fake_run)

        with pytest.raises(RuntimeError, match="AppleScript execution timed out"):
            reminders.get_reminders("日常")
        assert captured["timeout"] == reminders.DEFAULT_READ_TIMEOUT

    def test_list_calendars_returns_applescript_error(self, monkeypatch):
        from nudge.apple import calendar

        monkeypatch.setattr(
            calendar,
            "list_calendars_eventkit",
            lambda timeout=5: (False, "EventKit denied"),
        )
        monkeypatch.setattr(calendar, "run_applescript", lambda script, timeout=30: (False, "denied"))

        assert calendar.list_calendars() == (
            False,
            "EventKit failed: EventKit denied; AppleScript failed: denied",
        )

    def test_query_events_eventkit_parses_rows_and_passes_calendar_names(self, monkeypatch):
        from nudge.apple import calendar

        captured = {}

        def fake_run(cmd, capture_output, text, timeout):
            captured["cmd"] = cmd
            captured["timeout"] = timeout
            return SimpleNamespace(
                returncode=0,
                stdout="会议\t2026-04-25 09:00\t2026-04-25 10:00\tFamily\n",
                stderr="",
            )

        monkeypatch.setattr(calendar.subprocess, "run", fake_run)

        ok, result = calendar.query_events_eventkit(
            datetime(2026, 4, 25, 0, 0),
            datetime(2026, 4, 25, 23, 59),
            calendar_names=["Family", "个人"],
            timeout=7,
        )

        assert ok is True
        assert result == [
            {
                "summary": "会议",
                "start": "2026-04-25 09:00",
                "end": "2026-04-25 10:00",
                "calendar": "Family",
            }
        ]
        assert captured["cmd"][:2] == ["/usr/bin/swift", str(calendar.EVENTKIT_CALENDAR_EVENTS_SCRIPT)]
        assert captured["cmd"][2:4] == ["2026-04-25 00:00", "2026-04-25 23:59"]
        assert captured["cmd"][4:] == ["Family", "个人"]
        assert captured["timeout"] == 7

    def test_query_events_eventkit_reports_timeout(self, monkeypatch):
        from nudge.apple import calendar

        def fake_run(cmd, capture_output, text, timeout):
            raise subprocess.TimeoutExpired(cmd, timeout)

        monkeypatch.setattr(calendar.subprocess, "run", fake_run)

        assert calendar.query_events_eventkit(
            datetime(2026, 4, 25, 0, 0),
            datetime(2026, 4, 25, 23, 59),
            calendar_names=["Family"],
            timeout=3,
        ) == (False, "EventKit Calendar read timed out")


    def test_get_events_with_explicit_empty_calendar_names_does_not_scan_all_calendars(self, monkeypatch):
        from nudge.apple import calendar

        monkeypatch.setattr(
            calendar,
            "query_events_eventkit",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("EventKit should not run")),
        )
        monkeypatch.setattr(
            calendar,
            "run_applescript",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("AppleScript should not run")),
        )

        assert calendar.get_events(
            datetime(2026, 4, 25, 0, 0),
            datetime(2026, 4, 25, 23, 59),
            calendar_names=[],
        ) == []
        assert calendar.get_today_events(calendar_names=[]) == []
        assert calendar.get_week_events(calendar_names=[]) == []

    def test_get_events_prefers_eventkit_for_configured_calendar_names(self, monkeypatch):
        from nudge.apple import calendar

        calls = []
        monkeypatch.setattr(
            calendar,
            "query_events_eventkit",
            lambda start, end, calendar_names=None, timeout=30: calls.append((start, end, calendar_names, timeout))
            or (
                True,
                [
                    {
                        "summary": "会议",
                        "start": "2026-04-25 09:00",
                        "end": "2026-04-25 10:00",
                        "calendar": "Family",
                    }
                ],
            ),
        )
        monkeypatch.setattr(
            calendar,
            "run_applescript",
            lambda script, timeout=30: (_ for _ in ()).throw(AssertionError("AppleScript should not run")),
        )

        events = calendar.get_events(
            datetime(2026, 4, 25, 0, 0),
            datetime(2026, 4, 25, 23, 59),
            calendar_names=["Family"],
            timeout=8,
        )

        assert events == [
            {
                "summary": "会议",
                "start": "2026-04-25 09:00",
                "end": "2026-04-25 10:00",
                "calendar": "Family",
            }
        ]
        assert calls == [
            (
                datetime(2026, 4, 25, 0, 0),
                datetime(2026, 4, 25, 23, 59),
                ["Family"],
                8,
            )
        ]

    def test_get_events_falls_back_to_scoped_applescript_when_eventkit_unreadable(self, monkeypatch):
        from nudge.apple import calendar

        seen = []
        monkeypatch.setattr(
            calendar,
            "query_events_eventkit",
            lambda start, end, calendar_names=None, timeout=30: (
                False,
                "EventKit Calendar full access denied or not readable",
            ),
        )

        def fake_run(script, timeout=30):
            assert timeout == 6
            for name in ("Family", "个人"):
                if f'tell calendar "{name}"' in script:
                    seen.append(name)
                    return True, f"{name} event\t2026-04-25 09:00\t2026-04-25 10:00\t{name}\n"
            raise AssertionError(f"unexpected script: {script}")

        monkeypatch.setattr(calendar, "run_applescript", fake_run)

        events = calendar.get_events(
            datetime(2026, 4, 25, 0, 0),
            datetime(2026, 4, 25, 23, 59),
            calendar_names=["Family", "个人", "Family"],
            timeout=6,
        )

        assert seen == ["Family", "个人"]
        assert [event["calendar"] for event in events] == ["Family", "个人"]

    def test_get_events_raises_when_eventkit_and_applescript_fail(self, monkeypatch):
        from nudge.apple import calendar

        monkeypatch.setattr(
            calendar,
            "query_events_eventkit",
            lambda start, end, calendar_names=None, timeout=30: (
                False,
                "EventKit Calendar read timed out",
            ),
        )
        monkeypatch.setattr(
            calendar,
            "run_applescript",
            lambda script, timeout=30: (False, "AppleScript execution timed out"),
        )

        with pytest.raises(RuntimeError, match="AppleScript execution timed out"):
            calendar.get_events(
                datetime(2026, 4, 25, 0, 0),
                datetime(2026, 4, 25, 23, 59),
                calendar_names=["Family"],
                timeout=3,
            )

    def test_get_events_can_query_configured_calendar_names(self, monkeypatch):
        from nudge.apple import calendar

        seen = []
        original_get_events = calendar.get_events

        def fake_run(script, timeout=30):
            for name in ("Family", "个人"):
                if f'tell calendar "{name}"' in script:
                    seen.append(name)
                    return True, f"{name} event\t2026-04-25 09:00\t2026-04-25 10:00\t{name}\n"
            raise AssertionError(f"unexpected script: {script}")

        monkeypatch.setattr(calendar, "run_applescript", fake_run)

        events = original_get_events(
            datetime(2026, 4, 25, 0, 0),
            datetime(2026, 4, 25, 23, 59),
            calendar_names=["Family", "个人", "Family"],
            prefer_eventkit=False,
        )

        assert seen == ["Family", "个人"]
        assert [event["calendar"] for event in events] == ["Family", "个人"]

    def test_create_calendar_event_returns_uid(self, monkeypatch):
        from nudge.apple import calendar

        captured = {}

        def fake_run(script, timeout=30):
            captured["script"] = script
            return True, "uid-123"

        monkeypatch.setattr(calendar, "run_applescript", fake_run)

        ok, uid = calendar.create_calendar_event(
            "会议",
            datetime(2026, 4, 27, 9, 0),
            datetime(2026, 4, 27, 10, 0),
            "Family",
        )

        assert ok is True
        assert uid == "uid-123"
        assert "set newEvent to make new event" in captured["script"]
        assert "uid of newEvent" in captured["script"]

    def test_update_event_by_uid_uses_safe_uid_lookup(self, monkeypatch):
        from nudge.apple import calendar

        captured = {}

        def fake_run(script, timeout=30):
            captured["script"] = script
            captured["timeout"] = timeout
            return True, "updated"

        monkeypatch.setattr(calendar, "run_applescript", fake_run)

        ok, message = calendar.update_event_by_uid(
            "uid-123",
            summary="新标题",
            start=datetime(2026, 4, 27, 8, 0),
            end=datetime(2026, 4, 27, 8, 30),
            timeout=9,
        )

        assert ok is True
        assert message == "updated"
        assert 'whose uid is "uid-123"' in captured["script"]
        assert 'set summary of e to "新标题"' in captured["script"]
        assert "set start date of e to startDate" in captured["script"]
        assert "if startDate > (end date of e)" in captured["script"]
        assert captured["timeout"] == 9

    def test_update_event_by_scoped_external_id_limits_lookup_to_calendar(self, monkeypatch):
        from nudge.apple import calendar

        captured = {}
        monkeypatch.setattr(
            calendar,
            "run_applescript",
            lambda script, timeout=30: captured.update({"script": script}) or (True, "updated"),
        )

        scoped_id = calendar.make_calendar_external_id("Family", "uid-123")
        ok, _message = calendar.update_event_by_uid(
            scoped_id,
            start=datetime(2026, 4, 27, 8, 0),
            end=datetime(2026, 4, 27, 8, 30),
        )

        assert ok is True
        assert 'tell calendar "Family"' in captured["script"]
        assert 'whose uid is "uid-123"' in captured["script"]
        assert "repeat with cal in every calendar" not in captured["script"]

    def test_delete_event_by_uid_uses_safe_uid_lookup(self, monkeypatch):
        from nudge.apple import calendar

        captured = {}

        def fake_run(script, timeout=30):
            captured["script"] = script
            return True, "deleted"

        monkeypatch.setattr(calendar, "run_applescript", fake_run)

        assert calendar.delete_event_by_uid("uid-123") == (True, "deleted")
        assert 'whose uid is "uid-123"' in captured["script"]
        assert "delete e" in captured["script"]

    def test_delete_event_legacy_summary_requires_unique_match(self, monkeypatch):
        from nudge.apple import calendar

        captured = {}

        def fake_run(script, timeout=30):
            captured["script"] = script
            captured["timeout"] = timeout
            return True, "deleted"

        monkeypatch.setattr(calendar, "run_applescript", fake_run)

        assert calendar.delete_event("会议", "Family") == (True, "deleted")
        script = captured["script"]
        assert 'set matchingEvents to every event whose summary is "会议"' in script
        assert "set matchCount to count of matchingEvents" in script
        assert "if matchCount is 0 then error" in script
        assert "if matchCount is not 1 then error" in script
        assert "set e to item 1 of matchingEvents" in script
        assert "delete e" in script
        assert "repeat with e in matchingEvents" not in script

    def test_delete_event_by_scoped_external_id_limits_lookup_to_calendar(self, monkeypatch):
        from nudge.apple import calendar

        captured = {}
        monkeypatch.setattr(
            calendar,
            "run_applescript",
            lambda script, timeout=30: captured.update({"script": script, "timeout": timeout}) or (True, "deleted"),
        )

        scoped_id = calendar.make_calendar_external_id("Family", "uid-123")
        assert calendar.delete_event_by_uid(scoped_id, timeout=6) == (True, "deleted")
        assert 'tell calendar "Family"' in captured["script"]
        assert 'whose uid is "uid-123"' in captured["script"]
        assert "repeat with cal in every calendar" not in captured["script"]
        assert captured["timeout"] == 6

    def test_read_unread_count_reports_mail_applescript_error(self, monkeypatch):
        from nudge.apple import mail

        monkeypatch.setattr(mail, "run_applescript", lambda script, timeout=30: (False, "mail denied"))

        assert mail.read_unread_count() == (False, "mail denied")

    def test_read_unread_count_parses_integer_output(self, monkeypatch):
        from nudge.apple import mail

        monkeypatch.setattr(mail, "run_applescript", lambda script, timeout=30: (True, "7"))

        assert mail.read_unread_count() == (True, 7)


class TestRunApplescriptFailures:
    """回流自公开库 986b013：osascript 缺失或不可执行时必须返回契约元组而非抛异常。"""

    def test_returns_failure_when_osascript_missing(self, monkeypatch):
        def fake_run(*args, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", "osascript")

        monkeypatch.setattr(subprocess, "run", fake_run)

        ok, message = run_applescript('display dialog "hi"')

        assert ok is False
        assert "osascript unavailable" in message
        assert "not found" in message

    def test_returns_failure_on_os_error(self, monkeypatch):
        def fake_run(*args, **kwargs):
            raise PermissionError(13, "Permission denied", "osascript")

        monkeypatch.setattr(subprocess, "run", fake_run)

        ok, message = run_applescript('display dialog "hi"')

        assert ok is False
        assert "osascript unavailable" in message
        assert "Permission denied" in message

    def test_timeout_message_is_distinct_from_missing_binary(self, monkeypatch):
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=["osascript"], timeout=1)

        monkeypatch.setattr(subprocess, "run", fake_run)

        ok, message = run_applescript('display dialog "hi"', timeout=1)

        assert ok is False
        assert "timed out" in message
        assert "osascript unavailable" not in message
