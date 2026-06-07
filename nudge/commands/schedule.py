"""Schedule command — recommend free time slots from calendar availability."""

import json
import re
from datetime import datetime, date, timedelta

import click

from nudge.apple.calendar import get_week_events
from nudge.config import get_configured_calendar_names, get_user_profile, load_config
from nudge.errors import classify_apple_error


@click.command("schedule")
@click.argument("request", required=False)
@click.option("--config", "-c", "config_path", default=None)
@click.option("--json", "json_output", is_flag=True, help="Output stable JSON.")
def schedule_command(request, config_path, json_output):
    """Recommend a free time slot.

    Example: nudge.py schedule "找2小时深度工作时间"
    """
    config = load_config(config_path)
    profile = get_user_profile(config)
    schedule_prefs = profile.get("schedule", {})

    plan = _parse_request(request or "", schedule_prefs)

    if not json_output:
        click.echo(f"查找可用时间段：{plan['label']}，至少 {plan['duration_minutes']} 分钟...\n")

    calendar_names = get_configured_calendar_names(config)
    try:
        events = get_week_events(calendar_names=calendar_names)
    except Exception as exc:
        target = ", ".join(calendar_names) if calendar_names else "configured calendars"
        raise click.ClickException(
            classify_apple_error("Calendar", "Calendar", target, str(exc)).render()
        )

    candidate_slots = _candidate_slots(events, plan)
    recommended_slot = candidate_slots[0] if candidate_slots else None
    payload = {
        "ok": recommended_slot is not None,
        "request": request or "",
        "duration_minutes": plan["duration_minutes"],
        "preference": plan["preference"],
        "recommended_slot": recommended_slot,
        "candidate_slots": candidate_slots,
    }
    if not recommended_slot:
        payload["message"] = "没有找到满足需求的可用时间段"

    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return

    if not recommended_slot:
        click.echo(payload["message"])
        return

    click.echo("推荐 slot：")
    _echo_slot("  1.", recommended_slot)
    if len(candidate_slots) > 1:
        click.echo("\n其他候选：")
        for index, slot in enumerate(candidate_slots[1:], 2):
            _echo_slot(f"  {index}.", slot)

    click.echo("\n提示：本命令只推荐时间，不会写入 Apple Calendar。")


def _parse_request(request: str, schedule_prefs: dict) -> dict:
    today = date.today()
    start_date, end_date, label = _parse_date_range(request, today)
    preference = _parse_preference(request)
    hours_key = "personal_hours" if preference == "personal" else "work_hours"
    hours = schedule_prefs.get(hours_key) or schedule_prefs.get("work_hours") or ["09:00", "18:00"]
    start_minute = _parse_clock(hours[0])
    end_minute = _parse_clock(hours[1])
    return {
        "duration_minutes": _parse_duration_minutes(request),
        "preference": preference,
        "start_date": start_date,
        "end_date": end_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "label": label,
    }


def _parse_duration_minutes(request: str) -> int:
    hour_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|h|hour)", request, re.IGNORECASE)
    if hour_match:
        return int(float(hour_match.group(1)) * 60)
    minute_match = re.search(r"(\d+)\s*(?:分钟|min|minute)", request, re.IGNORECASE)
    if minute_match:
        return int(minute_match.group(1))
    return 60


def _parse_date_range(request: str, today: date) -> tuple[date, date, str]:
    if "今天" in request or "当天" in request:
        return today, today, "今天"
    if "明天" in request:
        tomorrow = today + timedelta(days=1)
        return tomorrow, tomorrow, "明天"
    if "后天" in request:
        target = today + timedelta(days=2)
        return target, target, "后天"
    if "未来两天" in request or "这两天" in request:
        return today, today + timedelta(days=1), "未来两天"
    monday = today - timedelta(days=today.weekday())
    return max(today, monday), monday + timedelta(days=6), "本周"


def _parse_preference(request: str) -> str:
    if any(word in request for word in ("个人", "私人", "生活", "家庭")):
        return "personal"
    return "work"


def _candidate_slots(events: list[dict], plan: dict) -> list[dict]:
    slots = []
    current_date = plan["start_date"]
    while current_date <= plan["end_date"]:
        slots.extend(_day_slots(current_date, events, plan))
        current_date += timedelta(days=1)
    return slots


def _day_slots(target_date: date, events: list[dict], plan: dict) -> list[dict]:
    busy = []
    window_start = plan["start_minute"]
    window_end = plan["end_minute"]
    for event in events:
        try:
            start_dt = datetime.strptime(event["start"], "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(event["end"], "%Y-%m-%d %H:%M")
        except (KeyError, ValueError):
            continue
        if start_dt.date() != target_date and end_dt.date() != target_date:
            continue
        start_minute = 0 if start_dt.date() < target_date else start_dt.hour * 60 + start_dt.minute
        end_minute = 24 * 60 if end_dt.date() > target_date else end_dt.hour * 60 + end_dt.minute
        start_minute = max(window_start, start_minute)
        end_minute = min(window_end, end_minute)
        if start_minute < end_minute:
            busy.append((start_minute, end_minute))

    busy.sort()
    slots = []
    current = window_start
    for busy_start, busy_end in busy:
        if current < busy_start:
            _append_slot(slots, target_date, current, busy_start, plan["duration_minutes"])
        current = max(current, busy_end)

    if current < window_end:
        _append_slot(slots, target_date, current, window_end, plan["duration_minutes"])
    return slots


def _append_slot(slots: list[dict], target_date: date, start_minute: int, end_minute: int, requested: int) -> None:
    gap = end_minute - start_minute
    if gap < requested:
        return
    slot_end = start_minute + requested
    slots.append({
        "date": target_date.isoformat(),
        "day_name": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][target_date.weekday()],
        "start": _format_minute(start_minute),
        "end": _format_minute(slot_end),
        "duration_minutes": requested,
    })


def _parse_clock(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _format_minute(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def _echo_slot(prefix: str, slot: dict) -> None:
    click.echo(
        f"{prefix} {slot['day_name']} {slot['date']} "
        f"{slot['start']}-{slot['end']} ({slot['duration_minutes']} 分钟)"
    )
