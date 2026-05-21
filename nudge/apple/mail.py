"""Apple Mail integration via AppleScript (read-only + drafts)."""

from nudge.apple.common import run_applescript


def read_unread_count(timeout: int = 5) -> tuple[bool, int | str]:
    """Read total unread email count and preserve AppleScript failures."""
    ok, raw = run_applescript(
        'tell application "Mail" to get unread count of inbox',
        timeout=timeout,
    )
    if not ok:
        return False, raw
    try:
        return True, int(raw)
    except ValueError:
        return False, f"Unexpected unread count: {raw}"


def get_unread_count() -> int:
    """Get total unread email count across all accounts."""
    ok, result = read_unread_count()
    if ok:
        return int(result)
    return 0


def get_recent_messages(n: int = 5) -> list[dict]:
    """Get recent N messages from inbox.

    Returns list of {sender, subject, date} dicts.
    """
    n = max(1, int(n))
    script = f"""set output to ""
tell application "Mail"
    set msgs to messages 1 thru {n} of inbox
    repeat with m in msgs
        set output to output & (sender of m) & "\\t" & (subject of m) & "\\t" & (date received of m as string) & "\\n"
    end repeat
end tell
output"""

    ok, raw = run_applescript(script)
    if not ok:
        return []

    messages = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            messages.append({
                "sender": parts[0],
                "subject": parts[1],
                "date": parts[2],
            })
    return messages
