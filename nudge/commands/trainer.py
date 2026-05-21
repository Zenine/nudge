"""Trainer command — generate workout plans, log completions, view status."""

from datetime import datetime, timedelta

import click

from nudge.apple.calendar import create_calendar_event, get_week_events, make_calendar_external_id
from nudge.brain import NudgeBrainError, generate_workout_plan, parse_workout_log
from nudge.config import get_calendar_map, get_configured_calendar_names, get_user_profile, load_config
from nudge.errors import classify_apple_error
from nudge.sleep_reminders import SLEEP_AFTER_SKIP_STATUS, is_neutral_sleep_skip
from nudge.state import (
    complete_action,
    create_plan,
    get_actions,
    get_habit_streaks,
    get_plans,
    log_action,
    skip_action,
    update_habit,
)


@click.group("trainer")
def trainer_command():
    """Personal trainer — plan, log, and track workouts."""
    pass


@trainer_command.command("plan")
@click.option("--dry-run", "-n", is_flag=True, help="Preview without creating events")
@click.option("--config", "-c", "config_path", default=None)
def plan(dry_run, config_path):
    """Generate a weekly workout plan and write to calendar."""
    config = load_config(config_path)
    profile = get_user_profile(config)
    cal_map = get_calendar_map(config)
    workout_calendar = cal_map.get("workout", "个人")

    if not profile.get("fitness"):
        raise click.ClickException(
            "请先在 config.toml 中填写 [user.fitness] 配置（健身水平、目标、器械等）"
        )

    click.echo("读取本周日程...\n")
    calendar_names = get_configured_calendar_names(config)
    try:
        busy = get_week_events(calendar_names=calendar_names)
    except Exception as exc:
        target = ", ".join(calendar_names) if calendar_names else "configured calendars"
        raise click.ClickException(
            classify_apple_error("Calendar", "Calendar", target, str(exc)).render()
        )

    click.echo("生成训练计划...\n")
    try:
        sessions = generate_workout_plan(profile, busy)
    except NudgeBrainError as e:
        raise click.ClickException(str(e))

    click.echo(f"本周 {len(sessions)} 次训练：\n")
    for i, s in enumerate(sessions, 1):
        exercises = s.get("exercises", [])
        ex_summary = ", ".join(e["name"] for e in exercises[:3])
        if len(exercises) > 3:
            ex_summary += f" +{len(exercises) - 3} more"
        click.echo(f"  {i}. {s['day']} {s['time']}  {s['summary']}")
        click.echo(f"     {s.get('type', '')} · {s.get('duration_minutes', 45)}min")
        if ex_summary:
            click.echo(f"     {ex_summary}")
        click.echo()

    if dry_run:
        click.echo("(dry-run, nothing created)")
        return

    # Confirm
    click.confirm("写入日历？", default=True, abort=True)

    # Create plan in DB
    plan_id = create_plan(
        goal="weekly_workout",
        config={"sessions": sessions, "calendar": workout_calendar},
    )

    # Create calendar events
    success = 0
    for s in sessions:
        try:
            start = datetime.strptime(f"{s['day']} {s['time']}", "%Y-%m-%d %H:%M")
            duration = s.get("duration_minutes", 45)
            end = start + timedelta(minutes=duration)

            ok, msg = create_calendar_event(
                summary=s["summary"],
                start=start,
                end=end,
                calendar_name=workout_calendar,
                notes=_format_exercises(s.get("exercises", [])),
            )
            if ok:
                success += 1
                log_action(
                    action_type="workout",
                    summary=s["summary"],
                    scheduled_at=f"{s['day']} {s['time']}",
                    external_id=make_calendar_external_id(workout_calendar, msg),
                    plan_id=plan_id,
                )
        except (ValueError, KeyError) as e:
            click.echo(f"  跳过无效 session: {e}", err=True)

    click.echo(f"\n已写入 {success}/{len(sessions)} 个训练到 [{workout_calendar}] 日历")


@trainer_command.command("log")
@click.argument("message")
@click.option("--config", "-c", "config_path", default=None)
def log(message, config_path):
    """Log workout completion (e.g., 'trainer log "跑了5公里，感觉不错"')."""
    # Find the most recent pending workout action
    actions = get_actions(status="created")
    workout_actions = [a for a in actions if a["type"] == "workout"]

    if not workout_actions:
        click.echo("没有待完成的训练。先用 `nudge.py trainer plan` 创建计划。")
        return

    latest = workout_actions[0]  # most recent (ordered by created_at DESC)
    click.echo(f"记录训练: {latest['summary']}\n")

    try:
        result = parse_workout_log(message, latest)
    except NudgeBrainError as e:
        raise click.ClickException(str(e))

    if result.get("completed", False):
        complete_action(latest["id"], feedback=result)
        update_habit("exercise", notes=result.get("notes"))
        click.echo(f"  ✓ 已完成！effort: {result.get('effort', '?')}/10")
        if result.get("metrics"):
            for k, v in result["metrics"].items():
                click.echo(f"    {k}: {v}")
    else:
        skip_action(latest["id"])
        click.echo(f"  ✗ 已跳过: {result.get('notes', '')}")

    streaks = get_habit_streaks()
    exercise_streak = streaks.get("exercise", {}).get("streak", 0)
    if exercise_streak > 0:
        click.echo(f"\n  🔥 运动连续打卡第 {exercise_streak} 天！")


@trainer_command.command("status")
def status():
    """Show current workout plan progress."""
    plans = get_plans(status="active")
    workout_plans = [p for p in plans if p["goal"] == "weekly_workout"]

    if not workout_plans:
        click.echo("没有活跃的训练计划。用 `nudge.py trainer plan` 创建一个。")
        return

    current_plan = workout_plans[0]
    plan_id = current_plan["id"]
    actions = get_actions(plan_id=plan_id)

    sleep_after_skipped = sum(1 for a in actions if a["status"] == SLEEP_AFTER_SKIP_STATUS)
    scored_actions = [a for a in actions if not is_neutral_sleep_skip(a)]
    total = len(scored_actions)
    done = sum(1 for a in scored_actions if a["status"] == "done")
    skipped = sum(1 for a in scored_actions if a["status"] == "skipped")
    pending = total - done - skipped

    click.echo(f"训练计划 · 创建于 {current_plan['created_at'][:10]}\n")
    click.echo(f"  总计: {total} 次训练")
    click.echo(f"  ✓ 完成: {done}")
    click.echo(f"  ✗ 跳过: {skipped}")
    click.echo(f"  ○ 待完成: {pending}")
    if sleep_after_skipped:
        click.echo(f"  ☾ 已睡后作废: {sleep_after_skipped}")

    if total > 0:
        rate = done / total * 100
        bar_done = int(rate / 5)
        bar_empty = 20 - bar_done
        click.echo(f"\n  {'█' * bar_done}{'░' * bar_empty}  {rate:.0f}%")

    click.echo()
    for a in actions:
        if is_neutral_sleep_skip(a):
            symbol = "☾"
        else:
            symbol = "✓" if a["status"] == "done" else "✗" if a["status"] == "skipped" else "○"
        click.echo(f"  {symbol} {a['scheduled_at'] or ''}  {a['summary']}")

    # Habit streak
    streaks = get_habit_streaks()
    exercise_streak = streaks.get("exercise", {}).get("streak", 0)
    click.echo(f"\n  🔥 运动 streak: {exercise_streak} 天")


def _format_exercises(exercises: list[dict]) -> str:
    """Format exercises list for calendar event notes."""
    lines = []
    for ex in exercises:
        line = ex["name"]
        if ex.get("sets") and ex.get("reps"):
            line += f" {ex['sets']}x{ex['reps']}"
        if ex.get("notes"):
            line += f" ({ex['notes']})"
        lines.append(line)
    return "\n".join(lines)
