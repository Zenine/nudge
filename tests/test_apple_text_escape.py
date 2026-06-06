from datetime import datetime

from nudge.apple.common import escape
from nudge.apple.notes import create_note
from nudge.apple.reminders import create_reminder


def test_escape_single_line_fields_normalize_whitespace():
    assert escape('Title\n"quoted"\\path\titem') == 'Title \\"quoted\\"\\\\path item'


def test_create_note_preserves_body_line_breaks_and_escapes_text(monkeypatch):
    captured = {}

    def fake_run_applescript(script, timeout=30):
        captured["script"] = script
        return True, "created"

    monkeypatch.setattr("nudge.apple.notes.run_applescript", fake_run_applescript)

    create_note(
        title='Daily\n"note"',
        body='Intro "quote"\\path\n- item\tone\n\nNext paragraph',
        folder_name="Nudge",
    )

    script = captured["script"]
    assert 'name:"Daily \\"note\\""' in script
    assert 'body:"<html>" & linefeed & "<body' in script
    assert "&quot;quote&quot;\\\\path" in script
    assert "item one" in script
    assert "</li>\" & linefeed & \"</ul>" in script
    assert "</p>\" & linefeed & \"</body>" in script


def test_create_reminder_preserves_body_and_external_id_marker_line_breaks(monkeypatch):
    captured = {}

    def fake_eventkit_mutation(*args, **kwargs):
        return False, "force AppleScript fallback"

    def fake_run_applescript(script, timeout=30):
        captured["script"] = script
        return True, "created"

    monkeypatch.setattr("nudge.apple.reminders._run_eventkit_mutation", fake_eventkit_mutation)
    monkeypatch.setattr("nudge.apple.reminders.run_applescript", fake_run_applescript)

    create_reminder(
        name="Review\nplan",
        due_date=datetime(2026, 6, 6, 9, 30),
        list_name="Nudge",
        body='First "line"\\path\n- item\tone',
        external_id="nudge://reminder/test-id",
    )

    script = captured["script"]
    assert 'name:"Review plan"' in script
    assert 'body:"First \\"line\\"\\\\path" & linefeed & "- item one"' in script
    assert '" & linefeed & linefeed & "Nudge-ID: nudge://reminder/test-id"' in script
