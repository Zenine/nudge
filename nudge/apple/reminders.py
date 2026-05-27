"""Apple Reminders integration via AppleScript."""

import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from nudge.apple.common import date_block, escape, run_applescript


# Swift startup plus EventKit's own 15s access/fetch waits can exceed a short CLI timeout.
DEFAULT_READ_TIMEOUT = 35
EVENTKIT_DUE_TODAY_SCRIPT = Path(__file__).with_name("eventkit_reminders_due_today.swift")
EVENTKIT_MUTATE_SCRIPT = Path(__file__).with_name("eventkit_reminders_mutate.swift")
REMINDER_EXTERNAL_ID_PREFIX = "nudge://reminder/"
REMINDER_EXTERNAL_ID_MARKER = "Nudge-ID:"


def make_reminder_external_id() -> str:
    """Return a stable Nudge-owned identifier for Apple Reminders correlation."""
    return f"{REMINDER_EXTERNAL_ID_PREFIX}{uuid4().hex}"


def reminder_external_id_marker(external_id: str) -> str:
    """Return the notes marker used as a fallback for Reminders URL matching."""
    return f"{REMINDER_EXTERNAL_ID_MARKER} {external_id}"


def _body_with_external_id(body: str | None, external_id: str | None) -> str | None:
    if not external_id:
        return body
    marker = reminder_external_id_marker(external_id)
    if body and marker in body:
        return body
    return f"{body.rstrip()}\n\n{marker}" if body else marker


def list_reminder_lists(timeout: int = 5) -> tuple[bool, list[str] | str]:
    """Return available Apple Reminders list names.

    This is read-only and intended for diagnostics. Returns (False, error) when
    Reminders or macOS permissions are unavailable.
    """
    ok, result = list_reminder_lists_eventkit(timeout=timeout)
    if ok:
        return True, result
    eventkit_error = str(result)

    script = """set output to ""
tell application "Reminders"
    launch
    repeat with lst in every list
        set output to output & (name of lst) & "\\n"
    end repeat
end tell
output"""
    ok, raw = run_applescript(script, timeout=timeout)
    if not ok:
        return False, f"EventKit failed: {eventkit_error}; AppleScript failed: {raw}"
    return True, [line.strip() for line in raw.splitlines() if line.strip()]


def list_reminder_lists_eventkit(timeout: int = 5) -> tuple[bool, list[str] | str]:
    """Return Reminders list names through EventKit without scripting Reminders.app."""
    cmd = ["/usr/bin/swift", str(EVENTKIT_DUE_TODAY_SCRIPT), "--lists"]
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
        return False, "EventKit reminder-list query timed out"

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or f"swift exited with code {result.returncode}"
        return False, error

    return True, [line.strip() for line in result.stdout.splitlines() if line.strip()]


def probe_reminders_read(list_name: str | None = None, timeout: int = DEFAULT_READ_TIMEOUT) -> tuple[bool, str]:
    """Verify that Reminders can read reminder objects, not just list names.

    Listing Reminders lists can succeed while object queries still hang because
    of macOS privacy prompts, Reminders/iCloud sync state, or a large local
    Reminders database. Doctor uses this as a bounded read probe so it does not
    report a false PASS when only list metadata is readable.
    """
    ok, result = query_due_today(list_name=list_name, timeout=timeout)
    if not ok:
        return False, str(result)
    return True, f"due_today query readable; count={len(result)}"


def query_due_today_eventkit(
    list_name: str | None = None,
    target_date: datetime | None = None,
    timeout: int = DEFAULT_READ_TIMEOUT,
) -> tuple[bool, list[dict] | str]:
    """Get reminders due today through EventKit.

    Reminders AppleScript can hang when applying `whose ... due date ...`
    filters to larger lists. EventKit provides the same "incomplete reminders
    due today" query through a native predicate and is the preferred read path
    for briefing/chat/doctor.
    """
    if target_date and not list_name:
        return False, "list_name is required when querying a specific date"
    cmd = ["/usr/bin/swift", str(EVENTKIT_DUE_TODAY_SCRIPT)]
    if list_name:
        cmd.append(list_name)
    if target_date:
        cmd.append(target_date.strftime("%Y-%m-%d"))

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
        return False, "EventKit due-today query timed out"

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or f"swift exited with code {result.returncode}"
        return False, error

    return True, _parse_due_today_rows(result.stdout)


def query_due_on_date(
    list_name: str,
    target_date,
    timeout: int = DEFAULT_READ_TIMEOUT,
) -> tuple[bool, list[dict] | str]:
    """Get incomplete reminders due on one local date from one list."""
    if not hasattr(target_date, "strftime"):
        return False, "target_date must be a date or datetime"
    return query_due_today_eventkit(
        list_name=list_name,
        target_date=target_date,
        timeout=timeout,
    )


def query_completed_on_date(
    list_name: str,
    target_date,
    timeout: int = DEFAULT_READ_TIMEOUT,
) -> tuple[bool, list[dict] | str]:
    """Get reminders completed on one local date from one list."""
    if not hasattr(target_date, "strftime"):
        return False, "target_date must be a date or datetime"

    cmd = [
        "/usr/bin/swift",
        str(EVENTKIT_DUE_TODAY_SCRIPT),
        list_name,
        target_date.strftime("%Y-%m-%d"),
        "completed",
    ]

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
        return False, "EventKit completed-reminders query timed out"

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or f"swift exited with code {result.returncode}"
        return False, error

    return True, _parse_due_today_rows(result.stdout)


def _parse_due_today_rows(raw: str) -> list[dict]:
    """Parse tab-separated due-today rows from Swift/EventKit or AppleScript."""
    reminders = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            reminder = {
                "name": parts[0],
                "due_time": parts[1],
                "list": parts[2],
            }
            if len(parts) >= 4 and parts[3]:
                reminder["completed_at"] = parts[3]
            if len(parts) >= 5 and parts[4]:
                reminder["due_at"] = parts[4]
            reminders.append(reminder)
    return reminders


def _run_eventkit_mutation(
    operation: str,
    name: str,
    list_name: str,
    timeout: int = 30,
    due_date: str | None = None,
    body: str | None = None,
    priority: int = 0,
    remind_date: str | None = None,
    external_id: str | None = None,
) -> tuple[bool, str]:
    """Run an EventKit reminder mutation and return (success, message)."""
    cmd = [
        "/usr/bin/swift",
        str(EVENTKIT_MUTATE_SCRIPT),
        operation,
        list_name,
        name,
    ]
    if due_date:
        cmd.append(due_date)
    if operation == "create":
        cmd.extend([
            str(priority),
            remind_date or "",
            external_id or "",
            body or "",
        ])
    elif operation == "set-id":
        cmd.extend([
            str(priority),
            remind_date or "",
            external_id or "",
            body or "",
        ])
    elif external_id and operation != "complete-id":
        cmd.append(external_id)
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
        return False, f"EventKit {operation} reminder timed out"

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or f"swift exited with code {result.returncode}"
        return False, error

    return True, result.stdout.strip() or "changed"


def create_reminder(
    name: str,
    due_date: datetime,
    list_name: str,
    body: str | None = None,
    priority: int = 0,
    remind_date: datetime | None = None,
    timeout: int = 30,
    external_id: str | None = None,
) -> tuple[bool, str]:
    """Create a Reminder. Returns (success, id/error)."""
    if external_id:
        remind_text = remind_date.strftime("%Y-%m-%d %H:%M") if remind_date else ""
        ok, result = _run_eventkit_mutation(
            "create",
            name,
            list_name,
            timeout=timeout,
            due_date=due_date.strftime("%Y-%m-%d %H:%M"),
            body=_body_with_external_id(body, external_id),
            priority=priority,
            remind_date=remind_text,
            external_id=external_id,
        )
        if ok:
            return True, external_id
        eventkit_error = result
    else:
        eventkit_error = ""

    date_blocks = [date_block("dueDate", due_date)]
    props = [
        f'name:"{escape(name)}"',
        "due date:dueDate",
    ]
    fallback_body = _body_with_external_id(body, external_id)
    if fallback_body:
        props.append(f'body:"{escape(fallback_body)}"')
    if priority > 0:
        props.append(f"priority:{priority}")
    if remind_date:
        date_blocks.append(date_block("remindDate", remind_date))
        props.append("remind me date:remindDate")

    props_str = ", ".join(props)
    dates_str = "\n\n".join(date_blocks)

    script = f"""{dates_str}

tell application "Reminders"
    tell list "{escape(list_name)}"
        make new reminder with properties {{{props_str}}}
    end tell
end tell"""

    ok, result = run_applescript(script, timeout=timeout)
    if ok and external_id:
        return True, external_id
    if not ok and eventkit_error:
        return False, f"EventKit failed: {eventkit_error}; AppleScript failed: {result}"
    return ok, result


def get_reminders(
    list_name: str,
    include_completed: bool = False,
    timeout: int = DEFAULT_READ_TIMEOUT,
) -> list[dict]:
    """Get reminders from a specific list.

    Returns list of {name, due_date, completed} dicts.

    Raises:
        RuntimeError: if Reminders AppleScript read fails. Returning an empty
            list would hide permission, timeout, or sync failures as "no
            reminders".
    """
    completed_filter = "" if include_completed else "whose completed is false"

    script = f"""set output to ""
tell application "Reminders"
    tell list "{escape(list_name)}"
        set rems to every reminder {completed_filter}
        repeat with r in rems
            set rName to name of r
            set rDone to completed of r
            set rDue to ""
            try
                set d to due date of r
                set y to year of d as string
                set m to text -2 thru -1 of ("0" & ((month of d as integer) as string))
                set dd to text -2 thru -1 of ("0" & (day of d as string))
                set h to text -2 thru -1 of ("0" & (hours of d as string))
                set n to text -2 thru -1 of ("0" & (minutes of d as string))
                set rDue to y & "-" & m & "-" & dd & " " & h & ":" & n
            end try
            set output to output & rName & "\\t" & rDue & "\\t" & (rDone as string) & "\\n"
        end repeat
    end tell
end tell
output"""

    ok, raw = run_applescript(script, timeout=timeout)
    if not ok:
        raise RuntimeError(raw)

    reminders = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            reminders.append({
                "name": parts[0],
                "due_date": parts[1] if parts[1] else None,
                "completed": parts[2] == "true",
            })
    return reminders


def query_due_today(
    list_name: str | None = None,
    timeout: int = DEFAULT_READ_TIMEOUT,
    prefer_eventkit: bool = True,
) -> tuple[bool, list[dict] | str]:
    """Get reminders due today across all lists."""
    if prefer_eventkit:
        ok, result = query_due_today_eventkit(list_name=list_name, timeout=timeout)
        if ok:
            return True, result
        eventkit_error = str(result)
    else:
        eventkit_error = ""

    from datetime import date, time

    today = date.today()
    start = datetime.combine(today, time.min)
    end = datetime.combine(today, time.max)

    if list_name:
        list_loop = f"""set lst to list "{escape(list_name)}"
set lstName to name of lst
set rems to (every reminder of lst whose completed is false and due date >= startRef and due date <= endRef)
repeat with r in rems
    set rName to name of r
    set d to due date of r
    set h to text -2 thru -1 of ("0" & (hours of d as string))
    set n to text -2 thru -1 of ("0" & (minutes of d as string))
    set output to output & rName & "\\t" & h & ":" & n & "\\t" & lstName & "\\n"
end repeat"""
    else:
        list_loop = """repeat with lst in every list
    set lstName to name of lst
    set rems to (every reminder of lst whose completed is false and due date >= startRef and due date <= endRef)
    repeat with r in rems
        set rName to name of r
        set d to due date of r
        set h to text -2 thru -1 of ("0" & (hours of d as string))
        set n to text -2 thru -1 of ("0" & (minutes of d as string))
        set output to output & rName & "\\t" & h & ":" & n & "\\t" & lstName & "\\n"
    end repeat
end repeat"""

    script = f"""{date_block("startRef", start)}
{date_block("endRef", end)}

set output to ""
tell application "Reminders"
    {list_loop}
end tell
output"""

    ok, raw = run_applescript(script, timeout=timeout)
    if not ok and eventkit_error:
        return False, f"EventKit failed: {eventkit_error}; AppleScript failed: {raw}"
    if not ok:
        return False, raw

    return True, _parse_due_today_rows(raw)


def get_due_today(timeout: int = DEFAULT_READ_TIMEOUT) -> list[dict]:
    """Get reminders due today across all lists, raising on read failure."""
    ok, result = query_due_today(timeout=timeout)
    if not ok:
        raise RuntimeError(result)
    return result


def complete_reminder(
    name: str,
    list_name: str,
    timeout: int = 30,
    prefer_eventkit: bool = True,
    due_date: str | None = None,
) -> tuple[bool, str]:
    """Mark incomplete reminder(s) with an exact title as completed."""
    if prefer_eventkit:
        ok, result = _run_eventkit_mutation(
            "complete",
            name,
            list_name,
            timeout=timeout,
            due_date=due_date,
        )
        if ok:
            return True, result
        eventkit_error = result
        if due_date:
            return False, f"EventKit failed for precise reminder completion: {eventkit_error}"
    else:
        eventkit_error = ""

    script = f"""tell application "Reminders"
    tell list "{escape(list_name)}"
        set matchingReminders to every reminder whose name is "{escape(name)}" and completed is false
        repeat with r in matchingReminders
            set completed of r to true
        end repeat
    end tell
end tell
"done"
"""
    ok, result = run_applescript(script, timeout=timeout)
    if ok:
        return True, result
    if eventkit_error:
        return False, f"EventKit failed: {eventkit_error}; AppleScript failed: {result}"
    return False, result


def complete_reminder_by_external_id(
    external_id: str,
    list_name: str,
    timeout: int = 30,
) -> tuple[bool, str]:
    """Mark one Nudge-owned Apple Reminder as completed by stable external id."""
    ok, result = _run_eventkit_mutation(
        "complete-id",
        external_id,
        list_name,
        timeout=timeout,
        external_id=external_id,
    )
    if ok:
        return True, result
    return False, f"EventKit failed for reminder external_id completion: {result}"


def set_reminder_external_id(
    name: str,
    list_name: str,
    due_date: str,
    external_id: str,
    timeout: int = 30,
) -> tuple[bool, str]:
    """Attach a stable Nudge external id to exactly one existing reminder."""
    ok, result = _run_eventkit_mutation(
        "set-id",
        name,
        list_name,
        timeout=timeout,
        due_date=due_date,
        external_id=external_id,
    )
    if ok:
        return True, result
    return False, f"EventKit failed for reminder external_id backfill: {result}"


def delete_reminder(
    name: str,
    list_name: str,
    timeout: int = 30,
    prefer_eventkit: bool = True,
) -> tuple[bool, str]:
    """Delete reminder(s) with an exact title from a list."""
    if prefer_eventkit:
        ok, result = _run_eventkit_mutation("delete", name, list_name, timeout=timeout)
        if ok:
            return True, result
        eventkit_error = result
    else:
        eventkit_error = ""

    script = f"""tell application "Reminders"
    tell list "{escape(list_name)}"
        set matchingReminders to every reminder whose name is "{escape(name)}"
        repeat with r in matchingReminders
            delete r
        end repeat
    end tell
end tell
"deleted"
"""
    ok, result = run_applescript(script, timeout=timeout)
    if ok:
        return True, result
    if eventkit_error:
        return False, f"EventKit failed: {eventkit_error}; AppleScript failed: {result}"
    return False, result
