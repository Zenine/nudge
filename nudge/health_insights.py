"""Health insight rendering for briefings and reviews."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


def health_context_section(
    *,
    as_of: date | None = None,
    days: int = 7,
    daily_summaries: list[dict] | None = None,
    workouts: list[dict] | None = None,
    fetch_daily=None,
    fetch_workouts=None,
) -> str:
    """Render a concise health context section from imported Apple Health aggregates.

    The section is read-only and intentionally uses daily aggregates/workout
    metadata only; Nudge never needs raw Health samples or routes for briefing.
    """
    if days <= 0:
        raise ValueError("days must be positive")
    today = as_of or date.today()
    start = today - timedelta(days=days - 1)
    end = today + timedelta(days=1)
    since = start.isoformat()
    until = end.isoformat()

    if daily_summaries is None:
        if fetch_daily is None:
            from nudge.state import get_health_daily_summaries as fetch_daily  # local import for testability
        daily_summaries = fetch_daily(since, until)
    if workouts is None:
        if fetch_workouts is None:
            from nudge.state import get_health_workouts as fetch_workouts  # local import for testability
        workouts = fetch_workouts(since, until)

    rows = [row for row in daily_summaries if isinstance(row, dict)]
    workout_rows = [row for row in workouts if isinstance(row, dict)]
    if not rows and not workout_rows:
        return ""

    lines = [f"健康数据（近 {days} 天）:"]
    metric_parts = []

    sleep_avg = _average_present(row.get("sleep_asleep_minutes") for row in rows)
    steps_avg = _average_present(row.get("steps") for row in rows)
    active_avg = _average_present(row.get("active_energy_kcal") for row in rows)
    exercise_avg = _average_present(row.get("exercise_minutes") for row in rows)
    if sleep_avg is not None:
        metric_parts.append(f"睡眠均值 {_fmt(sleep_avg)}min")
    if steps_avg is not None:
        metric_parts.append(f"步数均值 {_fmt(steps_avg)}")
    if active_avg is not None:
        metric_parts.append(f"活跃能量均值 {_fmt(active_avg)}kcal")
    if exercise_avg is not None:
        metric_parts.append(f"锻炼均值 {_fmt(exercise_avg)}min")

    workout_count = len(workout_rows)
    workout_minutes = sum(_number(row.get("duration_minutes")) or 0 for row in workout_rows)
    if workout_count:
        metric_parts.append(f"运动 {workout_count} 次/{_fmt(workout_minutes)}min")

    if metric_parts:
        lines.append(f"- {'；'.join(metric_parts)}")

    latest = _latest_daily(rows)
    if latest:
        latest_parts = []
        if latest.get("sleep_asleep_minutes") is not None:
            latest_parts.append(f"睡眠 {_fmt(latest.get('sleep_asleep_minutes'))}min")
        if latest.get("steps") is not None:
            latest_parts.append(f"步数 {_fmt(latest.get('steps'))}")
        if latest.get("active_energy_kcal") is not None:
            latest_parts.append(f"活跃 {_fmt(latest.get('active_energy_kcal'))}kcal")
        if latest_parts:
            lines.append(f"- 最近一天 {latest.get('date')}：{'；'.join(latest_parts)}")
        freshness = _freshness_note(str(latest.get("date") or ""), today)
        if freshness:
            lines.append(f"- {freshness}")

    return "\n".join(lines) if len(lines) > 1 else ""


def _average_present(values: Iterable[object]) -> float | None:
    numbers = [_number(value) for value in values]
    present = [value for value in numbers if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: object) -> str:
    number = _number(value)
    if number is None:
        return "-"
    rounded = round(number)
    if abs(number - rounded) < 0.05:
        return str(int(rounded))
    return f"{number:.1f}"


def _latest_daily(rows: list[dict]) -> dict | None:
    dated = [row for row in rows if row.get("date")]
    if not dated:
        return None
    return sorted(dated, key=lambda row: str(row.get("date")))[-1]


def _freshness_note(latest_date: str, today: date) -> str:
    try:
        latest = date.fromisoformat(latest_date)
    except ValueError:
        return ""
    if latest < today - timedelta(days=2):
        return f"健康数据停留在 {latest.isoformat()}，可运行 `nudge daily sync --health <export.json> --apply` 补齐。"
    return ""
