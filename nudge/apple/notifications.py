"""macOS notification display via AppleScript."""

from nudge.apple.common import escape, run_applescript


def notify(title: str, message: str, subtitle: str | None = None,
           sound: str = "default") -> tuple[bool, str]:
    """Display a macOS notification."""
    parts = [f'"{escape(message)}"', f'with title "{escape(title)}"']
    if subtitle:
        parts.append(f'subtitle "{escape(subtitle)}"')
    parts.append(f'sound name "{sound}"')

    script = f"display notification {' '.join(parts)}"
    return run_applescript(script)
