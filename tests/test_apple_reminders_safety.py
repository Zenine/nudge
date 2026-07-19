"""Safety tests for AppleScript reminder mutation fallbacks."""

from nudge.apple import reminders


def _disable_eventkit(monkeypatch):
    monkeypatch.setattr(
        reminders,
        "_run_eventkit_mutation",
        lambda *args, **kwargs: (False, "EventKit unavailable"),
    )


def test_complete_fallback_does_not_bulk_complete_every_same_title(monkeypatch) -> None:
    _disable_eventkit(monkeypatch)
    scripts: list[str] = []

    def fake_run_applescript(script: str, timeout: int = 30) -> tuple[bool, str]:
        scripts.append(script)
        return True, "done"

    monkeypatch.setattr(reminders, "run_applescript", fake_run_applescript)

    reminders.complete_reminder("Drink water", "Nudge", prefer_eventkit=False)

    script = scripts[0]
    assert 'every reminder whose name is "Drink water" and completed is false' not in script
    assert "count of matchingReminders" in script
    assert "item 1 of matchingReminders" in script


def test_complete_fallback_uses_due_date_when_available(monkeypatch) -> None:
    _disable_eventkit(monkeypatch)
    scripts: list[str] = []

    def fake_run_applescript(script: str, timeout: int = 30) -> tuple[bool, str]:
        scripts.append(script)
        return True, "done"

    monkeypatch.setattr(reminders, "run_applescript", fake_run_applescript)

    reminders.complete_reminder(
        "Drink water",
        "Nudge",
        prefer_eventkit=False,
        due_date="2026-07-05 09:30",
    )

    script = scripts[0]
    assert "set targetDueDate to current date" in script
    assert "due date of r = targetDueDate" in script
    assert "set completed of (item 1 of matchingReminders) to true" in script


def test_complete_fallback_fails_when_same_title_is_ambiguous(monkeypatch) -> None:
    _disable_eventkit(monkeypatch)
    scripts: list[str] = []

    def fake_run_applescript(script: str, timeout: int = 30) -> tuple[bool, str]:
        scripts.append(script)
        if "count of matchingReminders" in script and "ambiguous reminder title" in script:
            return False, "ambiguous reminder title: Drink water matched 2 reminders; refusing bulk completion"
        return True, "done"

    monkeypatch.setattr(reminders, "run_applescript", fake_run_applescript)

    ok, message = reminders.complete_reminder("Drink water", "Nudge", prefer_eventkit=False)

    assert ok is False
    assert "ambiguous reminder title" in message
    assert "set completed of r to true" not in scripts[0]


def test_delete_fallback_allows_unique_title_without_bulk_delete(monkeypatch) -> None:
    _disable_eventkit(monkeypatch)
    scripts: list[str] = []

    def fake_run_applescript(script: str, timeout: int = 30) -> tuple[bool, str]:
        scripts.append(script)
        if "count of matchingReminders" in script:
            return True, "deleted"
        return False, "unsafe bulk delete script"

    monkeypatch.setattr(reminders, "run_applescript", fake_run_applescript)

    ok, message = reminders.delete_reminder("Drink water", "Nudge", prefer_eventkit=False)

    assert ok is True
    assert message == "deleted"
    assert "delete r" not in scripts[0]
    assert "delete (item 1 of matchingReminders)" in scripts[0]


def test_auto_skipped_reminder_completion_passes_scheduled_at_as_due_date(monkeypatch) -> None:
    from nudge.commands import reminders as reminder_commands

    calls: list[dict] = []

    def fake_complete_reminder(name: str, list_name: str, **kwargs) -> tuple[bool, str]:
        calls.append({"name": name, "list_name": list_name, **kwargs})
        return True, "done"

    monkeypatch.setattr(reminder_commands, "complete_reminder", fake_complete_reminder)

    ok, message = reminder_commands._complete_reminder_by_possible_titles(
        "Wind down",
        "2026-07-05 21:30",
        "Nudge",
    )

    assert ok is True
    assert message == "done"
    assert calls[0]["due_date"] == "2026-07-05 21:30"


def test_sync_completed_never_infers_completion_from_list_absence() -> None:
    from nudge.commands import reminders as reminder_commands

    actions = [
        {
            "id": "target-list",
            "type": "reminder",
            "summary": "Target task",
            "scheduled_at": "2026-07-13 09:00",
            "reminder_list": "Focus",
        },
        {
            "id": "other-list",
            "type": "reminder",
            "summary": "Family task",
            "scheduled_at": "2026-07-13 09:00",
            "reminder_list": "Family",
        },
        {
            "id": "legacy-unknown-list",
            "type": "reminder",
            "summary": "Legacy task",
            "scheduled_at": "2026-07-13 10:00",
            "reminder_list": None,
        },
    ]

    candidates, open_count = reminder_commands._completed_candidates(
        actions,
        incomplete=[],
        completed=[],
    )

    assert open_count == 0
    assert candidates == []


def test_sync_completed_accepts_positive_match_for_moved_or_legacy_reminder() -> None:
    from nudge.commands import reminders as reminder_commands

    actions = [
        {
            "id": "moved",
            "type": "reminder",
            "summary": "Moved task",
            "scheduled_at": "2026-07-13 09:00",
            "reminder_list": "Old list",
        },
        {
            "id": "legacy",
            "type": "reminder",
            "summary": "Legacy task",
            "scheduled_at": "2026-07-13 10:00",
            "reminder_list": None,
        },
    ]
    completed = [
        {
            "name": "Moved task",
            "due_time": "09:00",
            "due_at": "2026-07-13 09:00",
            "completed_at": "2026-07-13 09:05",
        },
        {
            "name": "Legacy task",
            "due_time": "10:00",
            "due_at": "2026-07-13 10:00",
            "completed_at": "2026-07-13 10:05",
        },
    ]

    candidates, open_count = reminder_commands._completed_candidates(
        actions,
        incomplete=[],
        completed=completed,
    )

    assert open_count == 0
    assert [item["id"] for item in candidates] == ["moved", "legacy"]


def test_complete_falls_back_to_due_date_limited_applescript_when_eventkit_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        reminders,
        "_run_eventkit_mutation",
        lambda *args, **kwargs: (False, "swift unavailable"),
    )
    scripts: list[str] = []

    def fake_run_applescript(script: str, timeout: int = 30) -> tuple[bool, str]:
        scripts.append(script)
        return True, "done"

    monkeypatch.setattr(reminders, "run_applescript", fake_run_applescript)

    ok, message = reminders.complete_reminder(
        "Drink water",
        "Nudge",
        due_date="2026-07-05 09:30",
    )

    assert ok is True
    assert message == "done"
    assert "due date of r = targetDueDate" in scripts[0]
