"""Apple Calendar integration via EventKit with AppleScript fallback."""

import subprocess
from datetime import datetime
from pathlib import Path

from nudge.apple.common import date_block, escape, run_applescript


DEFAULT_READ_TIMEOUT = 10
EVENTKIT_CALENDAR_EVENTS_SCRIPT = Path(__file__).with_name("eventkit_calendar_events.swift")
EXTERNAL_ID_SEPARATOR = "::"


def open_calendar_app(timeout: int = 5) -> None:
    """Best-effort launch for AppleScript fallback paths."""
    try:
        subprocess.run(
            ["open", "-gj", "-a", "Calendar"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return


def make_calendar_external_id(calendar_name: str, uid: str) -> str:
    """Encode calendar name with Calendar UID for fast scoped mutations."""
    return f"{calendar_name}{EXTERNAL_ID_SEPARATOR}{uid}"


def _split_calendar_external_id(external_id: str) -> tuple[str | None, str]:
    """Return (calendar_name, uid) from a scoped or legacy external id."""
    if EXTERNAL_ID_SEPARATOR not in external_id:
        return None, external_id
    calendar_name, uid = external_id.split(EXTERNAL_ID_SEPARATOR, 1)
    return calendar_name or None, uid


def list_calendars(timeout: int = 5) -> tuple[bool, list[str] | str]:
    """Return available Apple Calendar names.

    This is read-only and intended for diagnostics. Returns (False, error) when
    Calendar or macOS permissions are unavailable.
    """
    ok, result = list_calendars_eventkit(timeout=timeout)
    if ok:
        return True, result
    eventkit_error = str(result)
    open_calendar_app(timeout=timeout)

    script = """set previousDelimiters to AppleScript's text item delimiters
tell application "Calendar"
    launch
    set calendarNames to name of calendars
end tell
set AppleScript's text item delimiters to "\\n"
set output to calendarNames as text
set AppleScript's text item delimiters to previousDelimiters
output"""
    ok, raw = run_applescript(script, timeout=timeout)
    if not ok:
        return False, f"EventKit failed: {eventkit_error}; AppleScript failed: {raw}"
    return True, [line.strip() for line in raw.splitlines() if line.strip()]


def list_calendars_eventkit(timeout: int = 5) -> tuple[bool, list[str] | str]:
    """Return Calendar names through EventKit without scripting Calendar.app."""
    cmd = ["/usr/bin/swift", str(EVENTKIT_CALENDAR_EVENTS_SCRIPT), "--lists"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "swift executable not found"
    except subprocess.TimeoutExpired:
        return False, "EventKit Calendar-list query timed out"

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or f"swift exited with code {result.returncode}"
        return False, error

    return True, [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _unique_names(names: list[str] | None) -> list[str]:
    """Return non-empty calendar names with duplicates removed in input order."""
    result = []
    seen = set()
    for name in names or []:
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _parse_event_rows(raw: str) -> list[dict]:
    """Parse tab-separated calendar event rows from Swift/EventKit or AppleScript."""
    events = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 4:
            events.append({
                "summary": parts[0],
                "start": parts[1],
                "end": parts[2],
                "calendar": parts[3],
            })
    return events


def query_events_eventkit(
    start_date: datetime,
    end_date: datetime,
    calendar_names: list[str] | None = None,
    timeout: int = DEFAULT_READ_TIMEOUT,
) -> tuple[bool, list[dict] | str]:
    """Get calendar events through EventKit.

    EventKit is much faster than Calendar AppleScript for scoped date-range
    reads, but macOS 14+ can grant write-only Calendar access. Write-only access
    is insufficient for reads, so the Swift helper returns a clear error and
    callers can fall back to AppleScript when needed.
    """
    cmd = [
        "/usr/bin/swift",
        str(EVENTKIT_CALENDAR_EVENTS_SCRIPT),
        start_date.strftime("%Y-%m-%d %H:%M"),
        end_date.strftime("%Y-%m-%d %H:%M"),
    ]
    cmd.extend(_unique_names(calendar_names))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "swift executable not found"
    except subprocess.TimeoutExpired:
        return False, "EventKit Calendar read timed out"

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or f"swift exited with code {result.returncode}"
        return False, error

    return True, _parse_event_rows(result.stdout)


def create_calendar_event(
    summary: str,
    start: datetime,
    end: datetime,
    calendar_name: str,
    location: str | None = None,
    notes: str | None = None,
) -> tuple[bool, str]:
    """Create a Calendar event. Returns (success, uid/error)."""
    props = [
        f'summary:"{escape(summary)}"',
        "start date:startDate",
        "end date:endDate",
    ]
    if location:
        props.append(f'location:"{escape(location)}"')
    if notes:
        props.append(f'description:"{escape(notes)}"')

    props_str = ", ".join(props)

    script = f"""{date_block("startDate", start)}

{date_block("endDate", end)}

tell application "Calendar"
    tell calendar "{escape(calendar_name)}"
        set newEvent to make new event with properties {{{props_str}}}
        uid of newEvent
    end tell
end tell"""

    return run_applescript(script)


def _coerce_datetime(value: datetime | str) -> datetime:
    """Accept datetime objects or the standard Nudge datetime string."""
    if isinstance(value, datetime):
        return value
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def update_event_by_uid(
    uid: str,
    summary: str | None = None,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    location: str | None = None,
    notes: str | None = None,
    timeout: int = 30,
) -> tuple[bool, str]:
    """Update one Calendar event by UID across all calendars."""
    date_blocks = []
    mutations = []
    if summary is not None:
        mutations.append(f'set summary of e to "{escape(summary)}"')
    if start is not None and end is not None:
        date_blocks.append(date_block("startDate", _coerce_datetime(start)))
        date_blocks.append(date_block("endDate", _coerce_datetime(end)))
        mutations.append("""if startDate > (end date of e) then
        set end date of e to endDate
        set start date of e to startDate
    else
        set start date of e to startDate
        set end date of e to endDate
    end if""")
    else:
        if start is not None:
            date_blocks.append(date_block("startDate", _coerce_datetime(start)))
            mutations.append("set start date of e to startDate")
        if end is not None:
            date_blocks.append(date_block("endDate", _coerce_datetime(end)))
            mutations.append("set end date of e to endDate")
    if location is not None:
        mutations.append(f'set location of e to "{escape(location)}"')
    if notes is not None:
        mutations.append(f'set description of e to "{escape(notes)}"')

    if not mutations:
        return True, "no changes"

    calendar_name, raw_uid = _split_calendar_external_id(uid)
    date_setup = "\n\n".join(date_blocks)
    mutation_script = "\n    ".join(mutations)

    if calendar_name:
        lookup = f"""tell calendar "{escape(calendar_name)}"
        set matches to every event whose uid is "{escape(raw_uid)}"
        if (count of matches) is 0 then error "Calendar event uid not found: {escape(raw_uid)}"
        set e to item 1 of matches
    end tell"""
    else:
        lookup = f"""set foundEvent to missing value
    repeat with cal in every calendar
        set matches to every event of cal whose uid is "{escape(raw_uid)}"
        if (count of matches) > 0 then
            set foundEvent to item 1 of matches
            exit repeat
        end if
    end repeat
    if foundEvent is missing value then error "Calendar event uid not found: {escape(raw_uid)}"
    set e to foundEvent"""

    script = f"""{date_setup}

tell application "Calendar"
    {lookup}
    {mutation_script}
end tell
"updated"
"""
    return run_applescript(script, timeout=timeout)


def delete_event_by_uid(uid: str, timeout: int = 30) -> tuple[bool, str]:
    """Delete one Calendar event by UID across all calendars."""
    calendar_name, raw_uid = _split_calendar_external_id(uid)
    if calendar_name:
        lookup = f"""tell calendar "{escape(calendar_name)}"
        set matches to every event whose uid is "{escape(raw_uid)}"
        if (count of matches) is 0 then error "Calendar event uid not found: {escape(raw_uid)}"
        set e to item 1 of matches
    end tell"""
    else:
        lookup = f"""set foundEvent to missing value
    repeat with cal in every calendar
        set matches to every event of cal whose uid is "{escape(raw_uid)}"
        if (count of matches) > 0 then
            set foundEvent to item 1 of matches
            exit repeat
        end if
    end repeat
    if foundEvent is missing value then error "Calendar event uid not found: {escape(raw_uid)}"
    set e to foundEvent"""

    script = f"""tell application "Calendar"
    {lookup}
    delete e
end tell
"deleted"
"""
    return run_applescript(script, timeout=timeout)


def get_events(
    start_date: datetime,
    end_date: datetime,
    calendar_name: str | None = None,
    calendar_names: list[str] | None = None,
    timeout: int = DEFAULT_READ_TIMEOUT,
    prefer_eventkit: bool = True,
) -> list[dict]:
    """Get calendar events in a date range.

    Returns list of {summary, start, end, calendar} dicts.
    """
    requested_names = _unique_names(calendar_names)
    if not requested_names and calendar_name:
        requested_names = [calendar_name]

    if prefer_eventkit and requested_names:
        ok, result = query_events_eventkit(
            start_date,
            end_date,
            calendar_names=requested_names,
            timeout=timeout,
        )
        if ok:
            return result

    if calendar_names:
        events = []
        for name in requested_names:
            events.extend(
                get_events(
                    start_date,
                    end_date,
                    calendar_name=name,
                    timeout=timeout,
                    prefer_eventkit=False,
                )
            )
        return events

    # Build AppleScript to iterate over events
    # When a specific calendar is given, use "tell calendar X"
    # Otherwise, iterate over all calendars with "repeat with cal"
    date_setup = f"""{date_block("startRef", start_date)}
{date_block("endRef", end_date)}"""

    if calendar_name:
        script = f"""{date_setup}

set output to ""
tell application "Calendar"
    tell calendar "{escape(calendar_name)}"
        set evts to (every event whose start date >= startRef and start date <= endRef)
        repeat with e in evts
            set eSummary to summary of e
            set eStart to start date of e
            set eEnd to end date of e
            set y1 to year of eStart as string
            set m1 to text -2 thru -1 of ("0" & ((month of eStart as integer) as string))
            set d1 to text -2 thru -1 of ("0" & (day of eStart as string))
            set h1 to text -2 thru -1 of ("0" & (hours of eStart as string))
            set n1 to text -2 thru -1 of ("0" & (minutes of eStart as string))
            set y2 to year of eEnd as string
            set m2 to text -2 thru -1 of ("0" & ((month of eEnd as integer) as string))
            set d2 to text -2 thru -1 of ("0" & (day of eEnd as string))
            set h2 to text -2 thru -1 of ("0" & (hours of eEnd as string))
            set n2 to text -2 thru -1 of ("0" & (minutes of eEnd as string))
            set output to output & eSummary & "\\t" & y1 & "-" & m1 & "-" & d1 & " " & h1 & ":" & n1 & "\\t" & y2 & "-" & m2 & "-" & d2 & " " & h2 & ":" & n2 & "\\t" & "{escape(calendar_name)}" & "\\n"
        end repeat
    end tell
end tell
output"""
    else:
        script = f"""{date_setup}

set output to ""
tell application "Calendar"
    repeat with cal in every calendar
        set calName to name of cal
        set evts to (every event of cal whose start date >= startRef and start date <= endRef)
        repeat with e in evts
            set eSummary to summary of e
            set eStart to start date of e
            set eEnd to end date of e
            set y1 to year of eStart as string
            set m1 to text -2 thru -1 of ("0" & ((month of eStart as integer) as string))
            set d1 to text -2 thru -1 of ("0" & (day of eStart as string))
            set h1 to text -2 thru -1 of ("0" & (hours of eStart as string))
            set n1 to text -2 thru -1 of ("0" & (minutes of eStart as string))
            set y2 to year of eEnd as string
            set m2 to text -2 thru -1 of ("0" & ((month of eEnd as integer) as string))
            set d2 to text -2 thru -1 of ("0" & (day of eEnd as string))
            set h2 to text -2 thru -1 of ("0" & (hours of eEnd as string))
            set n2 to text -2 thru -1 of ("0" & (minutes of eEnd as string))
            set output to output & eSummary & "\\t" & y1 & "-" & m1 & "-" & d1 & " " & h1 & ":" & n1 & "\\t" & y2 & "-" & m2 & "-" & d2 & " " & h2 & ":" & n2 & "\\t" & calName & "\\n"
        end repeat
    end repeat
end tell
output"""

    ok, raw = run_applescript(script, timeout=timeout)
    if not ok:
        raise RuntimeError(raw)

    return _parse_event_rows(raw)


def get_today_events(
    calendar_name: str | None = None,
    calendar_names: list[str] | None = None,
) -> list[dict]:
    """Get today's calendar events."""
    from datetime import date, time
    today = date.today()
    start = datetime.combine(today, time.min)
    end = datetime.combine(today, time.max)
    return get_events(start, end, calendar_name, calendar_names=calendar_names)


def get_week_events(
    calendar_name: str | None = None,
    calendar_names: list[str] | None = None,
) -> list[dict]:
    """Get this week's calendar events (Mon-Sun)."""
    from datetime import date, time, timedelta
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    start = datetime.combine(monday, time.min)
    end = datetime.combine(sunday, time.max)
    return get_events(start, end, calendar_name, calendar_names=calendar_names)


def delete_event(summary: str, calendar_name: str) -> tuple[bool, str]:
    """Delete event(s) by summary from a specific calendar."""
    script = f"""tell application "Calendar"
    tell calendar "{escape(calendar_name)}"
        set matchingEvents to every event whose summary is "{escape(summary)}"
        repeat with e in matchingEvents
            delete e
        end repeat
    end tell
end tell
"deleted"
"""
    return run_applescript(script)
