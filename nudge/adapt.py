"""Safe adaptation planning and execution."""

from datetime import datetime, timedelta

from nudge.apple.calendar import (
    EXTERNAL_ID_SEPARATOR,
    create_calendar_event,
    delete_event_by_uid,
    make_calendar_external_id,
    update_event_by_uid,
)
from nudge.config import DEFAULT_CALENDAR_NAME
from nudge.state import log_action, update_action_status


SUPPORTED_TYPES = {"move", "reduce", "split", "delete", "keep", "increase"}
TYPE_ALIASES = {
    "reduce_scope": "reduce",
    "reschedule": "move",
    "remove": "delete",
}


def build_adaptation_plan(suggestions: list[dict], actions: list[dict]) -> list[dict]:
    """Convert LLM suggestions into safe, deterministic execution plan items."""
    return [
        _build_plan_item(suggestion, actions)
        for suggestion in suggestions
    ]


def apply_adaptation_plan(plan: list[dict]) -> list[dict]:
    """Apply safe adaptation plan items to Calendar and SQLite state."""
    results = []
    for item in plan:
        if not item.get("safe"):
            results.append({
                "ok": False,
                "action_id": item.get("action_id"),
                "operation": item.get("operation"),
                "message": "; ".join(item.get("problems", [])) or "unsafe item skipped",
            })
            continue

        operation = item.get("operation")
        if operation == "update":
            ok, message = update_event_by_uid(
                item["external_id"],
                summary=item.get("summary"),
                start=item.get("start"),
                end=item.get("end"),
            )
            if ok:
                _mark_replaced_and_log_new_action(item, status="adapted")
            results.append({"ok": ok, "action_id": item.get("action_id"), "operation": operation, "message": message})
        elif operation == "delete":
            ok, message = delete_event_by_uid(item["external_id"])
            if ok:
                update_action_status(
                    item["action_id"],
                    "deleted",
                    feedback={"source": "review weekly --adapt", "type": item.get("type"), "reason": item.get("reason", "")},
                )
            results.append({"ok": ok, "action_id": item.get("action_id"), "operation": operation, "message": message})
        elif operation == "create":
            ok, message = _create_plan_event(item)
            results.append({"ok": ok, "action_id": item.get("action_id"), "operation": operation, "message": message})
        elif operation == "split":
            ok, message = _apply_split_item(item)
            results.append({"ok": ok, "action_id": item.get("action_id"), "operation": operation, "message": message})
        elif operation == "noop":
            results.append({"ok": True, "action_id": item.get("action_id"), "operation": operation, "message": "no changes"})
        else:
            results.append({"ok": False, "action_id": item.get("action_id"), "operation": operation, "message": "unsupported operation"})
    return results


def _build_plan_item(suggestion: dict, actions: list[dict]) -> dict:
    suggestion_type = _normalize_type(str(suggestion.get("type", "keep")))
    action = _find_action(suggestion, actions)
    title = suggestion.get("title", suggestion.get("suggestion", suggestion_type))
    reason = suggestion.get("reason", "")

    if suggestion_type not in SUPPORTED_TYPES:
        return _manual_item(suggestion_type, title, reason, action, [f"unsupported type: {suggestion_type}"])

    if suggestion_type == "keep":
        return {
            "type": "keep",
            "title": title,
            "reason": reason,
            "operation": "noop",
            "safe": True,
            "action_id": action.get("id") if action else None,
            "external_id": action.get("external_id") if action else None,
            "summary": action.get("summary") if action else "",
            "problems": [],
        }

    if suggestion_type == "increase":
        return _build_create_item(suggestion, title, reason)

    if action is None:
        return _manual_item(suggestion_type, title, reason, None, ["target action not found"])

    if suggestion_type == "delete":
        return _targeted_item(suggestion_type, title, reason, "delete", action)
    if suggestion_type == "move":
        start = suggestion.get("start") or suggestion.get("new_start")
        end = suggestion.get("end") or suggestion.get("new_end")
        item = _targeted_item(suggestion_type, title, reason, "update", action)
        item.update({"start": start or "", "end": end or "", "summary": suggestion.get("summary") or action.get("summary", "")})
        if not start or not end:
            item["safe"] = False
            item["problems"].append("missing start/end")
        else:
            _validate_plan_time_range(item, start, end)
        return item
    if suggestion_type == "reduce":
        item = _targeted_item(suggestion_type, title, reason, "update", action)
        start = suggestion.get("start") or action.get("scheduled_at")
        end = suggestion.get("end")
        if not end and suggestion.get("duration_minutes") and start:
            try:
                end = _add_minutes(start, int(suggestion["duration_minutes"]))
            except (TypeError, ValueError):
                item["safe"] = False
                item["problems"].append("invalid duration_minutes")
        item.update({"start": start or "", "end": end or "", "summary": suggestion.get("summary") or action.get("summary", "")})
        if not start or not end:
            item["safe"] = False
            item["problems"].append("missing start/end or duration_minutes")
        else:
            _validate_plan_time_range(item, start, end)
        return item
    if suggestion_type == "split":
        return _build_split_item(suggestion, title, reason, action)

    return _manual_item(suggestion_type, title, reason, action, ["unsupported suggestion"])


def _build_split_item(suggestion: dict, title: str, reason: str, action: dict | None) -> dict:
    if action is None:
        return _manual_item("split", title, reason, None, ["target action not found"])

    item = _targeted_item("split", title, reason, "split", action)
    parts = suggestion.get("parts") or []
    calendar_name = (
        suggestion.get("calendar_name")
        or suggestion.get("calendar")
        or _calendar_name_from_external_id(action.get("external_id"))
    )
    problems = item["problems"]

    if not calendar_name:
        problems.append("missing calendar_name")
    if not isinstance(parts, list) or not (2 <= len(parts) <= 4):
        problems.append("parts must contain 2-4 items")
        parts = []

    normalized_parts = []
    for index, part in enumerate(parts, 1):
        if not isinstance(part, dict):
            problems.append(f"part {index} must be an object")
            continue
        summary = str(part.get("summary") or "").strip()
        start = str(part.get("start") or "").strip()
        end = str(part.get("end") or "").strip()
        if not summary or not start or not end:
            problems.append(f"part {index} missing summary/start/end")
            continue
        try:
            start_dt = _parse_time(start)
            end_dt = _parse_time(end)
        except ValueError:
            problems.append(f"part {index} has invalid datetime")
            continue
        if end_dt <= start_dt:
            problems.append(f"part {index} end must be after start")
            continue
        normalized_parts.append({"summary": summary, "start": start, "end": end})

    item.update({
        "calendar_name": calendar_name or "",
        "parts": normalized_parts,
        "safe": not problems,
    })
    return item


def _targeted_item(suggestion_type: str, title: str, reason: str, operation: str, action: dict) -> dict:
    problems = []
    if not action.get("external_id"):
        problems.append("missing external_id")
    if action.get("type") != "calendar_event":
        problems.append(f"action type is {action.get('type')}")
    if action.get("status") not in ("created", "pending"):
        problems.append(f"action status is {action.get('status')}")
    return {
        "type": suggestion_type,
        "title": title,
        "reason": reason,
        "operation": operation,
        "safe": not problems,
        "action_id": action.get("id"),
        "external_id": action.get("external_id"),
        "summary": action.get("summary", ""),
        "problems": problems,
    }


def _manual_item(suggestion_type: str, title: str, reason: str, action: dict | None, problems: list[str]) -> dict:
    return {
        "type": suggestion_type,
        "title": title,
        "reason": reason,
        "operation": "manual",
        "safe": False,
        "action_id": action.get("id") if action else None,
        "external_id": action.get("external_id") if action else None,
        "summary": action.get("summary") if action else "",
        "problems": problems,
    }


def _build_create_item(suggestion: dict, title: str, reason: str) -> dict:
    start = suggestion.get("start")
    end = suggestion.get("end")
    summary = suggestion.get("summary") or title
    calendar_name = suggestion.get("calendar_name") or DEFAULT_CALENDAR_NAME
    problems = []
    if not start or not end:
        problems.append("missing start/end")
    if start and end:
        try:
            start_dt = _parse_time(str(start))
            end_dt = _parse_time(str(end))
        except (TypeError, ValueError):
            problems.append("invalid start/end datetime")
        else:
            if end_dt <= start_dt:
                problems.append("end must be after start")
    return {
        "type": "increase",
        "title": title,
        "reason": reason,
        "operation": "create",
        "safe": not problems,
        "action_id": None,
        "external_id": None,
        "summary": summary,
        "start": start or "",
        "end": end or "",
        "calendar_name": calendar_name,
        "problems": problems,
    }


def _find_action(suggestion: dict, actions: list[dict]) -> dict | None:
    action_id = suggestion.get("action_id")
    if action_id:
        return next((action for action in actions if action.get("id") == action_id), None)

    match_text = suggestion.get("match") or suggestion.get("target") or suggestion.get("summary")
    if not match_text:
        return None
    match_text = str(match_text).lower()
    matches = [action for action in actions if match_text in str(action.get("summary", "")).lower()]
    return matches[0] if len(matches) == 1 else None


def _normalize_type(value: str) -> str:
    return TYPE_ALIASES.get(value, value)


def _add_minutes(start: str, minutes: int) -> str:
    start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M")
    return (start_dt + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")


def _validate_plan_time_range(item: dict, start: str, end: str) -> None:
    """Mark a planned Calendar mutation unsafe when its time range is invalid."""
    try:
        start_dt = _parse_time(str(start))
        end_dt = _parse_time(str(end))
    except (TypeError, ValueError):
        item["safe"] = False
        item["problems"].append("invalid start/end datetime")
        return
    if end_dt <= start_dt:
        item["safe"] = False
        item["problems"].append("end must be after start")


def _apply_split_item(item: dict) -> tuple[bool, str]:
    parts = item.get("parts") or []
    if len(parts) < 2:
        return False, "split requires at least 2 parts"

    first = parts[0]
    ok, message = update_event_by_uid(
        item["external_id"],
        summary=first["summary"],
        start=first["start"],
        end=first["end"],
    )
    if not ok:
        return False, message

    external_ids = [item["external_id"]]
    for part in parts[1:]:
        ok, message = create_calendar_event(
            summary=part["summary"],
            start=_parse_time(part["start"]),
            end=_parse_time(part["end"]),
            calendar_name=item["calendar_name"],
            notes=f"Nudge split adaptation: {item.get('reason', '')}",
        )
        if not ok:
            return False, message
        external_ids.append(make_calendar_external_id(item["calendar_name"], message))

    update_action_status(
        item["action_id"],
        "adapted",
        feedback={"source": "review weekly --adapt", "type": "split", "reason": item.get("reason", "")},
    )
    for part, external_id in zip(parts, external_ids, strict=True):
        log_action(
            action_type="calendar_event",
            summary=part["summary"],
            scheduled_at=part["start"],
            external_id=external_id,
            status="created",
        )
    return True, f"split into {len(parts)} parts"


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def _calendar_name_from_external_id(external_id: str | None) -> str | None:
    if not external_id or EXTERNAL_ID_SEPARATOR not in external_id:
        return None
    calendar_name, _uid = external_id.split(EXTERNAL_ID_SEPARATOR, 1)
    return calendar_name or None


def _create_plan_event(item: dict) -> tuple[bool, str]:
    calendar_name = item.get("calendar_name") or DEFAULT_CALENDAR_NAME
    ok, message = create_calendar_event(
        summary=item["summary"],
        start=datetime.strptime(item["start"], "%Y-%m-%d %H:%M"),
        end=datetime.strptime(item["end"], "%Y-%m-%d %H:%M"),
        calendar_name=calendar_name,
        notes=f"Nudge adaptation: {item.get('reason', '')}",
    )
    if ok:
        log_action(
            action_type="calendar_event",
            summary=item["summary"],
            scheduled_at=item["start"],
            external_id=make_calendar_external_id(calendar_name, message),
            status="created",
        )
    return ok, message


def _mark_replaced_and_log_new_action(item: dict, status: str) -> None:
    update_action_status(
        item["action_id"],
        status,
        feedback={"source": "review weekly --adapt", "type": item.get("type"), "reason": item.get("reason", "")},
    )
    log_action(
        action_type="calendar_event",
        summary=item["summary"],
        scheduled_at=item["start"],
        external_id=item["external_id"],
        status="created",
    )
