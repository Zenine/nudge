"""Schedule command — find free time slots in your calendar."""

from datetime import datetime, date, time, timedelta

import click

from nudge.apple.calendar import get_week_events
from nudge.config import get_configured_calendar_names, get_user_profile, load_config
from nudge.errors import classify_apple_error


@click.command("schedule")
@click.argument("request", required=False)
@click.option("--config", "-c", "config_path", default=None)
def schedule_command(request, config_path):
    """Find free time slots this week.

    Example: nudge.py schedule "找2小时深度工作时间"
    """
    config = load_config(config_path)
    profile = get_user_profile(config)
    schedule_prefs = profile.get("schedule", {})

    work_start_str = schedule_prefs.get("work_hours", ["09:00", "18:00"])[0]
    work_end_str = schedule_prefs.get("work_hours", ["09:00", "18:00"])[1]
    work_start_h = int(work_start_str.split(":")[0])
    work_end_h = int(work_end_str.split(":")[0])

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

    free_slots = []
    for day_offset in range(7):
        d = monday + timedelta(days=day_offset)
        if d < today:
            continue

        day_events = [
            e for e in events if e.get("start", "").startswith(d.isoformat())
        ]

        # Parse busy times
        busy = []
        for e in day_events:
            try:
                s = datetime.strptime(e["start"], "%Y-%m-%d %H:%M")
                en = datetime.strptime(e["end"], "%Y-%m-%d %H:%M")
                busy.append((s.hour * 60 + s.minute, en.hour * 60 + en.minute))
            except (ValueError, KeyError):
                pass

        busy.sort()

        # Find free gaps within work hours
        current = work_start_h * 60
        end_of_day = work_end_h * 60

        for b_start, b_end in busy:
            if current < b_start:
                gap = b_start - current
                if gap >= 30:  # minimum 30 min slot
                    free_slots.append({
                        "date": d.isoformat(),
                        "start": f"{current // 60:02d}:{current % 60:02d}",
                        "end": f"{b_start // 60:02d}:{b_start % 60:02d}",
                        "duration": gap,
                        "day_name": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][d.weekday()],
                    })
            current = max(current, b_end)

        if current < end_of_day:
            gap = end_of_day - current
            if gap >= 30:
                free_slots.append({
                    "date": d.isoformat(),
                    "start": f"{current // 60:02d}:{current % 60:02d}",
                    "end": f"{end_of_day // 60:02d}:{end_of_day % 60:02d}",
                    "duration": gap,
                    "day_name": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][d.weekday()],
                })

    if not free_slots:
        click.echo(f"本周没有找到空闲时段（工作时间 {work_start_str}-{work_end_str}）")
        return

    click.echo(f"本周空闲时段（{work_start_str}-{work_end_str}）：\n")
    for i, slot in enumerate(free_slots, 1):
        hours = slot["duration"] // 60
        mins = slot["duration"] % 60
        dur_str = f"{hours}h{mins:02d}m" if hours else f"{mins}min"
        click.echo(f"  {i}. {slot['day_name']} {slot['date']} {slot['start']}-{slot['end']}  ({dur_str})")

    if request:
        click.echo(f"\n你的需求: {request}")
        # Filter by duration if user mentions hours
        click.echo("提示: 选择一个时段后，用 `nudge.py \"在XX时间做XX\"` 创建事件")
