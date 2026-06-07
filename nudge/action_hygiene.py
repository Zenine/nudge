"""Small normalization helpers for executable actions."""

from __future__ import annotations

import re


def normalize_reminder_action(action: dict) -> dict:
    """Return a reminder action with duplicate due-date suffix removed from title."""
    if action.get("type") != "reminder":
        return action
    normalized = dict(action)
    normalized["name"] = normalize_reminder_title(
        action.get("name", ""),
        action.get("due_date"),
    )
    return normalized


def normalize_reminder_title(name: object, due_date: object | None) -> str:
    """Keep Reminder titles short when the due date already carries scheduling."""
    title = str(name or "").strip()
    if not title or not due_date:
        return title

    cleaned = title
    for suffix in _due_suffixes(str(due_date)):
        cleaned = _strip_trailing_suffix(cleaned, suffix)
    return cleaned or title


def _due_suffixes(due_date: str) -> list[str]:
    due = due_date.strip()
    if not due:
        return []
    date_part = due.split(" ", 1)[0]
    suffixes = [due]
    if date_part != due:
        suffixes.append(date_part)
    return sorted(set(suffixes), key=len, reverse=True)


def _strip_trailing_suffix(title: str, suffix: str) -> str:
    escaped = re.escape(suffix)
    pattern = rf"(?:[\s,，、-]+{escaped}|[（(]\s*{escaped}\s*[）)])$"
    return re.sub(pattern, "", title).strip()
