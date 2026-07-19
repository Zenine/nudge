"""Pure selection and matching helpers for Reminder list ownership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from nudge.action_hygiene import normalize_reminder_title
from nudge.config import DEFAULT_REMINDER_LIST, get_defaults


@dataclass(frozen=True)
class ReminderListBackfillBatch:
    """A bounded batch of legacy actions and dates needed to inspect it."""

    actions: list[dict]
    query_dates: tuple[date, ...]
    invalid: list[dict]
    total_eligible: int
    remaining: int


def resolve_sync_lists(explicit_names, config: dict) -> list[str]:
    """Resolve an ordered, duplicate-free set of lists for completion sync."""
    configured = (config.get("reminders") or {}).get("sync_lists")
    if explicit_names:
        raw_names = list(explicit_names)
    elif configured is not None:
        if not isinstance(configured, list):
            raise ValueError("[reminders].sync_lists must be an array of list names")
        raw_names = configured
    else:
        defaults = get_defaults(config)
        raw_names = [defaults.get("default_reminder_list", DEFAULT_REMINDER_LIST)]

    result: list[str] = []
    for raw_name in raw_names:
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError("reminder list names must be non-empty strings")
        name = raw_name.strip()
        if name not in result:
            result.append(name)
    if not result:
        raise ValueError("at least one reminder list is required")
    return result


def parse_strict_minute(value: object) -> datetime | None:
    """Parse only the canonical SQLite/Apple local minute representation."""
    if not isinstance(value, str) or len(value) != 16:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return parsed if parsed.strftime("%Y-%m-%d %H:%M") == value else None


def select_list_backfill_actions(
    actions: Iterable[dict],
    *,
    date_from: date | None,
    date_to: date | None,
    limit: int = 100,
) -> ReminderListBackfillBatch:
    """Select a deterministic, bounded batch of unowned legacy reminders."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be an integer from 1 to 500")
    if date_from is not None and date_to is not None and date_to <= date_from:
        raise ValueError("--to must be later than --from")

    eligible: list[tuple[datetime, dict]] = []
    invalid: list[dict] = []
    for action in actions:
        if action.get("type") != "reminder" or action.get("status") not in {"created", "pending"}:
            continue

        reminder_list = action.get("reminder_list")
        if reminder_list is not None:
            if reminder_list == "":
                invalid.append(_invalid_action(action, "empty_reminder_list"))
            continue

        summary = action.get("summary")
        scheduled = parse_strict_minute(action.get("scheduled_at"))
        if not isinstance(summary, str) or not summary.strip() or scheduled is None:
            invalid.append(_invalid_action(action, "invalid_summary_or_scheduled_at"))
            continue
        if date_from is not None and scheduled.date() < date_from:
            continue
        if date_to is not None and scheduled.date() >= date_to:
            continue
        eligible.append((scheduled, action))

    eligible.sort(key=lambda item: (item[0], str(item[1].get("id") or "")))
    selected = eligible[:limit]
    selected_actions = [action for _, action in selected]
    query_dates = tuple(sorted({scheduled.date() for scheduled, _ in selected}))
    total_eligible = len(eligible)
    return ReminderListBackfillBatch(
        actions=selected_actions,
        query_dates=query_dates,
        invalid=invalid,
        total_eligible=total_eligible,
        remaining=total_eligible - len(selected_actions),
    )


def plan_list_backfill(
    actions: Iterable[dict],
    apple_rows: Iterable[dict],
) -> dict[str, list[dict]]:
    """Plan only globally unique action-to-Apple-row list assignments."""
    action_items = list(actions)
    rows = list(apple_rows)
    matches_by_action: list[list[tuple[int, str]]] = []
    claimants_by_row: dict[int, list[int]] = {}

    for action_index, action in enumerate(action_items):
        matches: list[tuple[int, str]] = []
        for row_index, row in enumerate(rows):
            match_type = _match_type(action, row)
            if match_type is None:
                continue
            matches.append((row_index, match_type))
            claimants_by_row.setdefault(row_index, []).append(action_index)
        matches_by_action.append(matches)

    candidates: list[dict] = []
    missing: list[dict] = []
    ambiguous: list[dict] = []
    for action_index, action in enumerate(action_items):
        matches = matches_by_action[action_index]
        basic = _backfill_action(action)
        if not matches:
            missing.append(basic)
            continue

        if len(matches) != 1 or len(claimants_by_row[matches[0][0]]) != 1:
            matched_lists = sorted({str(rows[row_index].get("list") or "") for row_index, _ in matches})
            ambiguous.append({
                **basic,
                "matched_lists": matched_lists,
                "matches": len(matches),
            })
            continue

        row_index, match_type = matches[0]
        candidates.append({
            **basic,
            "current_reminder_list": None,
            "target_list": rows[row_index].get("list"),
            "match_type": match_type,
        })

    return {
        "candidates": candidates,
        "missing": missing,
        "ambiguous": ambiguous,
    }


def _match_type(action: dict, apple_row: dict) -> str | None:
    scheduled_at = action.get("scheduled_at")
    due_at = apple_row.get("due_at")
    scheduled_minute = parse_strict_minute(scheduled_at)
    due_minute = parse_strict_minute(due_at)
    if scheduled_minute is None or due_minute is None or scheduled_minute != due_minute:
        return None

    summary = action.get("summary")
    name = apple_row.get("name")
    if isinstance(summary, str) and summary and summary == name:
        return "exact_title"

    normalized_summary = normalize_reminder_title(summary, scheduled_at)
    normalized_name = normalize_reminder_title(name, due_at)
    if normalized_summary and normalized_summary == normalized_name:
        return "normalized_trailing_date"
    return None


def _backfill_action(action: dict) -> dict:
    return {
        "id": action.get("id"),
        "summary": action.get("summary"),
        "scheduled_at": action.get("scheduled_at"),
        "status": action.get("status"),
    }


def _invalid_action(action: dict, reason: str) -> dict:
    return {
        "id": action.get("id"),
        "summary": action.get("summary"),
        "scheduled_at": action.get("scheduled_at"),
        "reason": reason,
    }
