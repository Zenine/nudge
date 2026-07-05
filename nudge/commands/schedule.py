"""Schedule command — find and optionally book free time slots."""

from __future__ import annotations

import json
import re
from datetime import datetime, date, timedelta

import click

from nudge.apple.adapters import resolve_apple_backends
from nudge.apple.calendar import get_week_events
from nudge.config import get_configured_calendar_names, get_defaults, get_user_profile, load_config
from nudge.errors import classify_apple_error
from nudge.json_contract import versioned_payload
from nudge.state import log_action


DAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
DEFAULT_MIN_DURATION = 30


@click.command("schedule")
@click.argument("request", required=False)
@click.option("--config", "-c", "config_path", default=None)
@click.option("--duration", type=int, default=None, help="Minimum slot duration in minutes")
@click.option("--json", "json_output", is_flag=True, help="Output stable JSON")
@click.option("--dry-run", "dry_run", is_flag=True, help="Preview booking without writing Calendar")
@click.option("--book", is_flag=True, help="Create a Calendar event for the selected slot")
@click.option("--slot", "slot_number", type=int, default=None, help="1-based slot number to book")
@click.option("--title", default=None, help="Calendar event title when booking")
@click.option("--yes", is_flag=True, help="Skip interactive confirmation for --book")
def schedule_command(request, config_path, duration, json_output, dry_run, book, slot_number, title, yes):
    """Find free time slots this week and optionally book one.

    Example: nudge schedule "找2小时深度工作时间"
    """
    config = load_config(config_path)
    profile = get_user_profile(config)
    schedule_prefs = profile.get("schedule", {}) if isinstance(profile.get("schedule", {}), dict) else {}
    work_start_str, work_end_str = _work_hours(schedule_prefs)
    min_duration = duration or parse_duration_minutes(request)

    if book and slot_number is None:
        message = "--book requires --slot so Nudge does not pick a time implicitly"
        if json_output:
            click.echo(json.dumps(_error_payload(message, request, min_duration, dry_run=dry_run), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(message)

    if not json_output:
        click.echo("查找本周空闲时段...\n")
    calendar_names = get_configured_calendar_names(config)
    try:
        events = get_week_events(calendar_names=calendar_names)
    except Exception as exc:
        target = ", ".join(calendar_names) if calendar_names else "configured calendars"
        raise click.ClickException(
            classify_apple_error("Calendar", "Calendar", target, str(exc)).render()
        )

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    free_slots = find_free_slots(
        events,
        week_start=monday,
        today=today,
        work_start=work_start_str,
        work_end=work_end_str,
        min_duration=min_duration,
    )

    booking = None
    exit_code = 0
    if book:
        try:
            selected = _select_slot(free_slots, slot_number)
        except ValueError as exc:
            if json_output:
                click.echo(json.dumps(_error_payload(str(exc), request, min_duration, dry_run=dry_run, slots=free_slots), ensure_ascii=False))
                raise click.exceptions.Exit(1)
            raise click.ClickException(str(exc))
        booking, exit_code = _book_slot(
            selected,
            request=request,
            title=title,
            duration=min_duration,
            config=config,
            dry_run=dry_run,
            yes=yes,
            json_output=json_output,
        )

    if json_output:
        click.echo(json.dumps(_schedule_payload(
            request=request,
            min_duration=min_duration,
            work_start=work_start_str,
            work_end=work_end_str,
            slots=free_slots,
            dry_run=(dry_run or not book),
            booking=booking,
            ok=exit_code == 0,
        ), ensure_ascii=False))
        if exit_code:
            raise click.exceptions.Exit(exit_code)
        return

    _print_slots(free_slots, work_start_str, work_end_str)
    if request:
        click.echo(f"\n你的需求: {request}")
    if book and booking:
        if dry_run:
            click.echo(f"\n(dry-run) 将创建日历事件: {booking['summary']} {booking['start']}-{booking['end']}")
        else:
            click.echo(f"\n已创建日历事件: {booking['summary']} {booking['start']}-{booking['end']}")
    elif request:
        click.echo("提示: 使用 `--book --slot N --title ...` 可在确认后创建日历事件。")


def parse_duration_minutes(request: str | None) -> int:
    """Extract a duration from free text, defaulting to 30 minutes."""
    text = str(request or "")
    patterns = [
        (r"(\d+(?:\.\d+)?)\s*(?:小时|小時|hour|hours|hr|hrs|h)", 60),
        (r"(\d+(?:\.\d+)?)\s*(?:分钟|分鐘|分|minute|minutes|min|mins|m)", 1),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return max(1, int(float(match.group(1)) * multiplier))
    return DEFAULT_MIN_DURATION


def find_free_slots(
    events: list[dict],
    *,
    week_start: date,
    today: date,
    work_start: str,
    work_end: str,
    min_duration: int = DEFAULT_MIN_DURATION,
) -> list[dict]:
    """Return free slots within work hours for the week."""
    work_start_min = _time_to_minutes(work_start)
    work_end_min = _time_to_minutes(work_end)
    free_slots = []

    for day_offset in range(7):
        d = week_start + timedelta(days=day_offset)
        if d < today:
            continue

        busy = []
        for event in events:
            parsed = _event_busy_minutes(event, d)
            if parsed is not None:
                busy.append(parsed)
        busy.sort()

        current = work_start_min
        for b_start, b_end in busy:
            b_start = max(b_start, work_start_min)
            b_end = min(b_end, work_end_min)
            if b_end <= work_start_min or b_start >= work_end_min:
                continue
            if current < b_start:
                _append_slot(free_slots, d, current, b_start, min_duration)
            current = max(current, b_end)

        if current < work_end_min:
            _append_slot(free_slots, d, current, work_end_min, min_duration)

    return free_slots


def _append_slot(slots: list[dict], d: date, start_min: int, end_min: int, min_duration: int) -> None:
    gap = end_min - start_min
    if gap < min_duration:
        return
    slots.append({
        "date": d.isoformat(),
        "start": _minutes_to_time(start_min),
        "end": _minutes_to_time(end_min),
        "duration": gap,
        "day_name": DAY_NAMES[d.weekday()],
    })


def _book_slot(
    slot: dict,
    *,
    request: str | None,
    title: str | None,
    duration: int,
    config: dict,
    dry_run: bool,
    yes: bool,
    json_output: bool,
) -> tuple[dict, int]:
    summary = (title or request or "Scheduled focus block").strip()
    if not summary:
        summary = "Scheduled focus block"
    start = datetime.strptime(f"{slot['date']} {slot['start']}", "%Y-%m-%d %H:%M")
    end = start + timedelta(minutes=duration)
    defaults = get_defaults(config)
    calendar_name = defaults.get("default_calendar", "Personal")
    notes = f"Scheduled from nudge schedule request: {request}" if request else "Scheduled from nudge schedule"
    booking = {
        "summary": summary,
        "start": start.strftime("%Y-%m-%d %H:%M"),
        "end": end.strftime("%Y-%m-%d %H:%M"),
        "calendar": calendar_name,
        "slot": slot,
    }

    if dry_run:
        return booking, 0
    if not yes and not json_output:
        click.confirm(
            f"Create Calendar event `{summary}` at {booking['start']}-{booking['end']} in `{calendar_name}`?",
            abort=True,
        )

    backends = resolve_apple_backends(config)
    result = backends.calendar.create_event(
        summary=summary,
        start=start,
        end=end,
        calendar_name=calendar_name,
        location=None,
        notes=notes,
    )
    if not result.ok:
        error = classify_apple_error("Calendar", "Calendar", calendar_name, result.message)
        booking["error"] = error.title
        booking["error_code"] = error.code
        return booking, 1

    booking["external_id"] = result.external_id
    action_id = log_action(
        action_type="calendar_event",
        summary=summary,
        scheduled_at=booking["start"],
        external_id=result.external_id,
    )
    booking["action_id"] = action_id
    return booking, 0


def _select_slot(slots: list[dict], slot_number: int | None) -> dict:
    if slot_number is None:
        raise ValueError("--book requires --slot so Nudge does not pick a time implicitly")
    if slot_number < 1 or slot_number > len(slots):
        raise ValueError(f"slot {slot_number} is out of range; found {len(slots)} slot(s)")
    return slots[slot_number - 1]


def _schedule_payload(
    *,
    request: str | None,
    min_duration: int,
    work_start: str,
    work_end: str,
    slots: list[dict],
    dry_run: bool,
    booking: dict | None,
    ok: bool = True,
) -> dict:
    payload = {
        "ok": ok,
        "request": request,
        "dry_run": dry_run,
        "min_duration": min_duration,
        "work_hours": [work_start, work_end],
        "slots": slots,
    }
    if booking is not None:
        payload["booking"] = booking
    return versioned_payload(payload)


def _error_payload(message: str, request: str | None, min_duration: int, *, dry_run: bool, slots: list[dict] | None = None) -> dict:
    payload = _schedule_payload(
        request=request,
        min_duration=min_duration,
        work_start="",
        work_end="",
        slots=slots or [],
        dry_run=dry_run,
        booking=None,
        ok=False,
    )
    payload["errors"] = [{"code": "SCHEDULE_REQUEST_INVALID", "message": message, "detail": message}]
    return payload


def _print_slots(free_slots: list[dict], work_start: str, work_end: str) -> None:
    if not free_slots:
        click.echo(f"本周没有找到空闲时段（工作时间 {work_start}-{work_end}）")
        return

    click.echo(f"本周空闲时段（{work_start}-{work_end}）：\n")
    for i, slot in enumerate(free_slots, 1):
        click.echo(f"  {i}. {slot['day_name']} {slot['date']} {slot['start']}-{slot['end']}  ({_duration_label(slot['duration'])})")


def _duration_label(duration: int) -> str:
    hours = duration // 60
    mins = duration % 60
    return f"{hours}h{mins:02d}m" if hours else f"{mins}min"


def _work_hours(schedule_prefs: dict) -> tuple[str, str]:
    value = schedule_prefs.get("work_hours", ["09:00", "18:00"])
    if not isinstance(value, list | tuple) or len(value) < 2:
        return "09:00", "18:00"
    return str(value[0]), str(value[1])


def _event_busy_minutes(event: dict, d: date) -> tuple[int, int] | None:
    try:
        start = _parse_event_datetime(str(event["start"]))
        end = _parse_event_datetime(str(event["end"]))
    except (KeyError, ValueError):
        return None
    if start.date() != d:
        return None
    return start.hour * 60 + start.minute, end.hour * 60 + end.minute


def _parse_event_datetime(value: str) -> datetime:
    normalized = value.replace("T", " ")[:16]
    return datetime.strptime(normalized, "%Y-%m-%d %H:%M")


def _time_to_minutes(value: str) -> int:
    hour, minute = str(value).split(":", 1)
    return int(hour) * 60 + int(minute[:2])


def _minutes_to_time(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"
