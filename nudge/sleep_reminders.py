"""Sleep-reminder completion rules.

A completed bedtime reminder is the terminal event for that night's sleep
workflow. Later sleep-related reminders should stop asking for feedback and
should not count as missed work.
"""

from __future__ import annotations

from datetime import datetime, timedelta

SLEEP_AFTER_SKIP_STATUS = "skipped_after_sleep"
SLEEP_AUTO_SKIP_LOOKAHEAD_HOURS = 8
PENDING_ACTION_STATUSES = {"created", "pending"}

_NON_TERMINAL_SLEEP_PHRASES = (
    "睡眠记录",
    "睡眠复盘",
    "睡眠总结",
    "睡眠报告",
    "记录睡眠",
    "sleep log",
    "sleep record",
    "sleep report",
    "sleep review",
)

_SLEEP_PREPARATION_PHRASES = (
    "准备睡",
    "睡前",
    "洗漱",
    "收尾",
    "prepare for bed",
    "wind down",
)

_SLEEP_TERMINAL_PHRASES = (
    "关机流程",
    "关机睡觉",
    "睡觉",
    "上床",
    "入睡",
    "就寝",
    "关灯睡",
    "睡眠模式",
    "bedtime",
    "go to bed",
    "lights out",
    "sleep mode",
)

_SLEEP_REMINDER_PHRASES = _SLEEP_TERMINAL_PHRASES + (
    "该睡",
    "该去睡",
    "不要熬夜",
    "别熬夜",
    "别晚睡",
    "熬夜",
    "晚睡",
    "准备睡",
    "准备休息",
)


def is_sleep_terminal_action(action: dict) -> bool:
    """Return True when an action means the user has started sleep."""
    if action.get("type") != "reminder":
        return False
    text = _summary_text(action)
    if not text or _contains_any(text, _NON_TERMINAL_SLEEP_PHRASES):
        return False
    if _contains_any(text, _SLEEP_PREPARATION_PHRASES):
        return False
    return _contains_any(text, _SLEEP_TERMINAL_PHRASES)


def is_sleep_reminder_action(action: dict) -> bool:
    """Return True for sleep/bedtime reminders that can be invalidated."""
    if action.get("type") != "reminder":
        return False
    text = _summary_text(action)
    if not text or _contains_any(text, _NON_TERMINAL_SLEEP_PHRASES):
        return False
    return _contains_any(text, _SLEEP_REMINDER_PHRASES)


def later_sleep_reminders_after(completed_action: dict, actions: list[dict]) -> list[dict]:
    """Return pending sleep reminders shortly after the completed action."""
    completed_at = _parse_action_time(completed_action)
    if completed_at is None or not is_sleep_terminal_action(completed_action):
        return []

    later: list[dict] = []
    for action in actions:
        if action.get("id") == completed_action.get("id"):
            continue
        if action.get("status") not in PENDING_ACTION_STATUSES:
            continue
        if not is_sleep_reminder_action(action):
            continue
        scheduled_at = _parse_action_time(action)
        if scheduled_at is None:
            continue
        delta = scheduled_at - completed_at
        if timedelta(0) < delta <= timedelta(hours=SLEEP_AUTO_SKIP_LOOKAHEAD_HOURS):
            later.append(action)
    return sorted(later, key=lambda action: str(action.get("scheduled_at") or ""))


def is_neutral_sleep_skip(action: dict) -> bool:
    """Return True when an action was skipped because sleep already started."""
    return action.get("status") == SLEEP_AFTER_SKIP_STATUS


def _summary_text(action: dict) -> str:
    return str(action.get("summary") or action.get("name") or "").strip().lower()


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _parse_action_time(action: dict) -> datetime | None:
    value = str(action.get("completed_at") or action.get("scheduled_at") or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None
