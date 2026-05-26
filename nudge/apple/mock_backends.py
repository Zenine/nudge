"""In-memory Apple backend examples for tests and non-macOS development."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from nudge.apple.adapters import AppleBackends, WriteResult
from nudge.apple.clock import DEFAULT_CREATE_ALARM_SHORTCUT
from nudge.apple.notes import DEFAULT_NOTES_FOLDER


@dataclass
class MockAppleStore:
    """Captured writes from mock Apple backends."""

    calendars: list[str] = field(default_factory=lambda: ["Personal"])
    reminder_lists: list[str] = field(default_factory=lambda: ["Tasks"])
    note_folders: list[str] = field(default_factory=lambda: [DEFAULT_NOTES_FOLDER])
    events: list[dict] = field(default_factory=list)
    reminders: list[dict] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)
    alarms: list[dict] = field(default_factory=list)


@dataclass
class MockCalendarBackend:
    """Calendar backend that records writes in memory."""

    store: MockAppleStore
    name: str = "mock-calendar"

    def list_calendars(self) -> tuple[bool, list[str] | str]:
        return True, list(self.store.calendars)

    def create_event(
        self,
        *,
        summary: str,
        start: datetime,
        end: datetime,
        calendar_name: str,
        location: str | None = None,
        notes: str | None = None,
    ) -> WriteResult:
        event = {
            "summary": summary,
            "start": start,
            "end": end,
            "calendar_name": calendar_name,
            "location": location,
            "notes": notes,
        }
        self.store.events.append(event)
        return WriteResult(
            ok=True,
            message="mock calendar event created",
            external_id=f"mock-calendar:{len(self.store.events)}",
        )


@dataclass
class MockRemindersBackend:
    """Reminders backend that records writes in memory."""

    store: MockAppleStore
    name: str = "mock-reminders"

    def list_lists(self) -> tuple[bool, list[str] | str]:
        return True, list(self.store.reminder_lists)

    def probe_read(self, list_name: str | None = None) -> tuple[bool, str]:
        target = list_name or ", ".join(self.store.reminder_lists)
        return True, f"mock reminders readable: {target}"

    def create_reminder(
        self,
        *,
        name: str,
        due_date: datetime,
        list_name: str,
        body: str | None = None,
        priority: int = 0,
        remind_date: datetime | None = None,
    ) -> WriteResult:
        reminder = {
            "name": name,
            "due_date": due_date,
            "list_name": list_name,
            "body": body,
            "priority": priority,
            "remind_date": remind_date,
        }
        self.store.reminders.append(reminder)
        return WriteResult(
            ok=True,
            message="mock reminder created",
            external_id=f"mock-reminder:{len(self.store.reminders)}",
        )


@dataclass
class MockNotesBackend:
    """Notes backend that records writes in memory."""

    store: MockAppleStore
    name: str = "mock-notes"

    def list_folders(self) -> tuple[bool, list[str] | str]:
        return True, list(self.store.note_folders)

    def create_note(
        self,
        *,
        title: str,
        body: str,
        folder_name: str = DEFAULT_NOTES_FOLDER,
    ) -> WriteResult:
        note = {"title": title, "body": body, "folder_name": folder_name}
        self.store.notes.append(note)
        return WriteResult(
            ok=True,
            message="mock note created",
            external_id=f"mock-note:{len(self.store.notes)}",
        )


@dataclass
class MockClockBackend:
    """Clock backend that records alarm writes in memory."""

    store: MockAppleStore
    shortcut_name: str = DEFAULT_CREATE_ALARM_SHORTCUT
    name: str = "mock-clock"

    def check(self) -> tuple[bool, str]:
        return True, f"mock shortcut available: {self.shortcut_name}"

    def create_alarm(self, *, time: str, label: str) -> WriteResult:
        alarm = {"time": time, "label": label, "shortcut_name": self.shortcut_name}
        self.store.alarms.append(alarm)
        return WriteResult(
            ok=True,
            message="mock alarm created",
            external_id=f"mock-alarm:{len(self.store.alarms)}",
        )


def build_mock_apple_backends(store: MockAppleStore | None = None) -> tuple[AppleBackends, MockAppleStore]:
    """Return protocol-compatible in-memory Apple backends and their store."""
    store = store or MockAppleStore()
    return (
        AppleBackends(
            calendar=MockCalendarBackend(store),
            reminders=MockRemindersBackend(store),
            notes=MockNotesBackend(store),
            clock=MockClockBackend(store),
        ),
        store,
    )
