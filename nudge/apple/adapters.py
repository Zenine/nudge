"""Configurable Apple integration backends.

Phase 1.7 keeps the existing macOS runtime unchanged:

- Calendar -> in-repo native implementation (EventKit read fast paths plus
  AppleScript write paths)
- Reminders -> in-repo native implementation (EventKit read/mutation fast paths
  plus AppleScript fallback/write paths)
- Notes -> in-repo native AppleScript implementation with a narrow write-only
  agent surface
- Clock -> Shortcuts bridge

This module adds the adapter boundary and selectors so future `ical` / `rem` /
`ekctl` / MCP backends can be added without leaking backend-specific behavior
into CLI commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from nudge.apple.calendar import (
    create_calendar_event,
    list_calendars,
    make_calendar_external_id,
)
from nudge.apple.clock import (
    DEFAULT_CREATE_ALARM_SHORTCUT,
    check_clock_shortcut,
    create_alarm,
)
from nudge.apple.notes import (
    DEFAULT_NOTES_FOLDER,
    create_note,
    list_note_folders,
)
from nudge.apple.reminders import (
    create_reminder,
    list_reminder_lists,
    make_reminder_external_id,
    probe_reminders_read,
)
from nudge.config import get_apple_backend_config


@dataclass(frozen=True)
class WriteResult:
    """Normalized result for write operations across Apple backends."""

    ok: bool
    message: str
    external_id: str | None = None


class UnsupportedAppleBackendError(ValueError):
    """Raised when config asks for an Apple backend that is not implemented."""

    def __init__(self, service: str, backend: str, supported: tuple[str, ...]):
        self.service = service
        self.backend = backend
        self.supported = supported
        super().__init__(
            f"Apple {service} backend `{backend}` 当前已实现范围外；"
            f"当前已实现：{', '.join(supported)}。"
        )


class CalendarBackend(Protocol):
    """Calendar adapter contract used by CLI command execution and doctor."""

    name: str

    def list_calendars(self) -> tuple[bool, list[str] | str]:
        """Return visible calendar names or an error string."""

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
        """Create one calendar event."""


class RemindersBackend(Protocol):
    """Reminders adapter contract used by CLI command execution and doctor."""

    name: str

    def list_lists(self) -> tuple[bool, list[str] | str]:
        """Return visible reminder list names or an error string."""

    def probe_read(self, list_name: str | None = None) -> tuple[bool, str]:
        """Verify reminder object read access."""

    def create_reminder(
        self,
        *,
        name: str,
        due_date: datetime,
        list_name: str,
        body: str | None = None,
        priority: int = 0,
        remind_date: datetime | None = None,
        external_id: str | None = None,
    ) -> WriteResult:
        """Create one reminder."""


class ClockBackend(Protocol):
    """Clock adapter contract used by CLI command execution and doctor."""

    name: str
    shortcut_name: str

    def check(self) -> tuple[bool, str]:
        """Return whether the configured alarm bridge is available."""

    def create_alarm(self, *, time: str, label: str) -> WriteResult:
        """Create one alarm."""


class NotesBackend(Protocol):
    """Notes adapter contract used by agent writes and doctor."""

    name: str

    def list_folders(self) -> tuple[bool, list[str] | str]:
        """Return visible Notes folder names or an error string."""

    def create_note(
        self,
        *,
        title: str,
        body: str,
        folder_name: str = DEFAULT_NOTES_FOLDER,
    ) -> WriteResult:
        """Create one note."""


@dataclass(frozen=True)
class NativeCalendarBackend:
    """Project-native Calendar backend."""

    name: str = "native"

    def list_calendars(self) -> tuple[bool, list[str] | str]:
        return list_calendars()

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
        ok, message = create_calendar_event(
            summary=summary,
            start=start,
            end=end,
            calendar_name=calendar_name,
            location=location,
            notes=notes,
        )
        external_id = make_calendar_external_id(calendar_name, message) if ok else None
        return WriteResult(ok=ok, message=message, external_id=external_id)


@dataclass(frozen=True)
class NativeRemindersBackend:
    """Project-native Reminders backend."""

    name: str = "native"

    def list_lists(self) -> tuple[bool, list[str] | str]:
        return list_reminder_lists()

    def probe_read(self, list_name: str | None = None) -> tuple[bool, str]:
        return probe_reminders_read(list_name)

    def create_reminder(
        self,
        *,
        name: str,
        due_date: datetime,
        list_name: str,
        body: str | None = None,
        priority: int = 0,
        remind_date: datetime | None = None,
        external_id: str | None = None,
    ) -> WriteResult:
        external_id = external_id or make_reminder_external_id()
        ok, message = create_reminder(
            name=name,
            due_date=due_date,
            list_name=list_name,
            body=body,
            priority=priority,
            remind_date=remind_date,
            external_id=external_id,
        )
        return WriteResult(ok=ok, message=message, external_id=external_id if ok else None)


@dataclass(frozen=True)
class ShortcutsClockBackend:
    """Clock backend through the macOS Shortcuts CLI."""

    shortcut_name: str = DEFAULT_CREATE_ALARM_SHORTCUT
    name: str = "shortcuts"

    def check(self) -> tuple[bool, str]:
        return check_clock_shortcut(self.shortcut_name)

    def create_alarm(self, *, time: str, label: str) -> WriteResult:
        ok, message = create_alarm(time=time, label=label, shortcut_name=self.shortcut_name)
        return WriteResult(ok=ok, message=message, external_id=message if ok else None)


@dataclass(frozen=True)
class NativeNotesBackend:
    """Project-native Notes backend."""

    name: str = "native"

    def list_folders(self) -> tuple[bool, list[str] | str]:
        return list_note_folders()

    def create_note(
        self,
        *,
        title: str,
        body: str,
        folder_name: str = DEFAULT_NOTES_FOLDER,
    ) -> WriteResult:
        ok, message = create_note(title=title, body=body, folder_name=folder_name)
        # Notes AppleScript does not give us a safe stable external ID. Keep
        # tracking by action summary for now.
        return WriteResult(ok=ok, message=message, external_id=None)


@dataclass(frozen=True)
class AppleBackends:
    """Resolved Apple backends for one command invocation."""

    calendar: CalendarBackend
    reminders: RemindersBackend
    notes: NotesBackend
    clock: ClockBackend


def get_calendar_backend(config: dict) -> CalendarBackend:
    """Resolve the Calendar backend from config."""
    service_config = get_apple_backend_config(config, "calendar", "native")
    backend = service_config["backend"]
    if backend == "native":
        return NativeCalendarBackend()
    raise UnsupportedAppleBackendError("calendar", backend, ("native",))


def get_reminders_backend(config: dict) -> RemindersBackend:
    """Resolve the Reminders backend from config."""
    service_config = get_apple_backend_config(config, "reminders", "native")
    backend = service_config["backend"]
    if backend == "native":
        return NativeRemindersBackend()
    raise UnsupportedAppleBackendError("reminders", backend, ("native",))


def get_clock_backend(config: dict) -> ClockBackend:
    """Resolve the Clock backend from config."""
    service_config = get_apple_backend_config(config, "clock", "shortcuts")
    backend = service_config["backend"]
    if backend == "shortcuts":
        return ShortcutsClockBackend(
            shortcut_name=service_config.get("shortcut_name", DEFAULT_CREATE_ALARM_SHORTCUT)
        )
    raise UnsupportedAppleBackendError("clock", backend, ("shortcuts",))


def get_notes_backend(config: dict) -> NotesBackend:
    """Resolve the Notes backend from config."""
    service_config = get_apple_backend_config(config, "notes", "native")
    backend = service_config["backend"]
    if backend == "native":
        return NativeNotesBackend()
    raise UnsupportedAppleBackendError("notes", backend, ("native",))


def resolve_apple_backends(config: dict) -> AppleBackends:
    """Resolve all Apple backends for one command invocation."""
    return AppleBackends(
        calendar=get_calendar_backend(config),
        reminders=get_reminders_backend(config),
        notes=get_notes_backend(config),
        clock=get_clock_backend(config),
    )
