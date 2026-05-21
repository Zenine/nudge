"""Apple ecosystem integration via AppleScript and EventKit."""

from nudge.apple.calendar import (
    create_calendar_event,
    delete_event_by_uid,
    delete_event,
    get_events,
    get_today_events,
    get_week_events,
    make_calendar_external_id,
    query_events_eventkit,
    update_event_by_uid,
)
from nudge.apple.mail import get_recent_messages, get_unread_count
from nudge.apple.notes import create_note, list_note_folders, list_nudge_note_summaries
from nudge.apple.notifications import notify
from nudge.apple.reminders import (
    complete_reminder,
    create_reminder,
    delete_reminder,
    get_due_today,
    get_reminders,
    probe_reminders_read,
    query_due_today,
)

__all__ = [
    "create_calendar_event",
    "delete_event_by_uid",
    "delete_event",
    "get_events",
    "get_today_events",
    "get_week_events",
    "make_calendar_external_id",
    "query_events_eventkit",
    "update_event_by_uid",
    "create_reminder",
    "get_reminders",
    "get_due_today",
    "query_due_today",
    "probe_reminders_read",
    "complete_reminder",
    "delete_reminder",
    "get_unread_count",
    "get_recent_messages",
    "create_note",
    "list_note_folders",
    "list_nudge_note_summaries",
    "notify",
]
