"""Trainer command — generate workout plans, log completions, view status."""

import json
from datetime import date, datetime, timedelta

import click

from nudge.apple.adapters import resolve_apple_backends
from nudge.apple.calendar import create_calendar_event, get_week_events, make_calendar_external_id
from nudge.brain import NudgeBrainError, generate_workout_plan, parse_workout_log
from nudge.commands.skills import _materialize_actions
from nudge.config import (
    DEFAULT_CALENDAR_NAME,
    get_calendar_map,
    get_configured_calendar_names,
    get_user_profile,
    load_config,
)
from nudge.errors import classify_apple_error
from nudge.json_contract import versioned_payload
from nudge.sleep_reminders import SLEEP_AFTER_SKIP_STATUS, is_neutral_sleep_skip
from nudge.skills.builtins import load_skill_source
from nudge.skills.dryrun import dry_run_skill
from nudge.skills.runtime import (
    create_skill_instance,
    list_skill_instances,
    record_materialized_week,
    skill_weeks_total,
)
from nudge.skills.schema import validate_skill
from nudge.state import (
    complete_action,
    configure_state,
    create_plan,
    get_actions,
    get_habit_streaks,
    get_plans,
    log_action,
    skip_action,
    update_habit,
    update_plan_status,
)


@click.group("trainer")
def trainer_command():
    """Personal trainer — plan, log, and track workouts."""
    pass


STRENGTH_SKILL_ID = "strength-basics-12w"


def _trainer_json_error(message: str) -> None:
    click.echo(
        json.dumps(
            versioned_payload({"ok": False, "error": message}),
            ensure_ascii=False,
        )
    )
    raise click.exceptions.Exit(1)


def _fitness_to_strength_context(profile: dict, *, start_date: str | None = None) -> dict:
    """Build the strength Skill context from [user.fitness] config."""
    if not isinstance(profile, dict):
        profile = {}
    fitness = profile.get("fitness") if "fitness" in profile else profile
    if not isinstance(fitness, dict):
        fitness = {}

    raw_frequency = fitness.get("current_frequency", fitness.get("strength_frequency"))
    if isinstance(raw_frequency, str) and raw_frequency in {"never", "one_or_two", "three_plus"}:
        frequency = str(raw_frequency)
    else:
        try:
            count = int(raw_frequency)
        except (TypeError, ValueError):
            count = 2
        if count <= 0:
            frequency = "never"
        elif count <= 2:
            frequency = "one_or_two"
        else:
            frequency = "three_plus"

    raw_minutes = fitness.get("preferred_session_length", fitness.get("session_minutes", 45))
    try:
        minutes = float(raw_minutes)
    except (TypeError, ValueError):
        minutes = 45.0

    skill_profile = {}
    chosen_start = start_date or fitness.get("start_date")
    if chosen_start:
        skill_profile["start_date"] = str(chosen_start)
    preferred_days = fitness.get("preferred_days")
    if isinstance(preferred_days, (list, tuple)):
        skill_profile["preferred_days"] = list(preferred_days)
    elif isinstance(preferred_days, str):
        skill_profile["preferred_days"] = [preferred_days]
    if fitness.get("preferred_time"):
        skill_profile["preferred_time"] = str(fitness["preferred_time"])

    return {
        "assessment": {
            "current_frequency": frequency,
            "preferred_session_length": minutes,
        },
        "profile": skill_profile,
    }


def _legacy_llm_plan(dry_run: bool, config_path: str | None) -> None:
    """Legacy LLM weekly workout planner kept as an explicit escape hatch."""
    config = load_config(config_path)
    profile = get_user_profile(config)
    cal_map = get_calendar_map(config)
    workout_calendar = cal_map.get("workout", DEFAULT_CALENDAR_NAME)

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


@trainer_command.command("plan")
@click.option("--dry-run", "-n", is_flag=True, help="Preview without creating events")
@click.option("--config", "-c", "config_path", default=None)
@click.option("--weeks", default=1, type=click.IntRange(1, 12), help="首次落地的周数")
@click.option("--start-date", "start_date_value", default=None, help="开始日期 YYYY-MM-DD，默认今天")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="跳过确认")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
@click.option("--legacy-llm", is_flag=True, help="使用旧版 LLM 周训练计划生成器")
def plan(dry_run, config_path, weeks, start_date_value, assume_yes, json_output, legacy_llm):
    """Create a workout plan. Defaults to the strength Skill runtime."""
    if legacy_llm:
        if json_output:
            _trainer_json_error("trainer plan --legacy-llm 不支持 --json")
        _legacy_llm_plan(dry_run, config_path)
        return

    config = load_config(config_path)
    configure_state(config)
    profile = get_user_profile(config)
    if not profile.get("fitness"):
        message = "请先在 config.toml 中填写 [user.fitness] 配置（健身水平、目标、器械等）"
        if json_output:
            _trainer_json_error(message)
        raise click.ClickException(message)

    fitness = profile.get("fitness") if isinstance(profile, dict) else {}
    if not isinstance(fitness, dict):
        fitness = {}
    start_date = start_date_value or fitness.get("start_date") or date.today().isoformat()
    try:
        start_date = str(start_date)
        date.fromisoformat(start_date)
    except (ValueError, TypeError) as exc:
        if json_output:
            _trainer_json_error("--start-date 必须是 YYYY-MM-DD 格式")
        raise click.ClickException("--start-date 必须是 YYYY-MM-DD 格式") from exc

    try:
        context = _fitness_to_strength_context(profile, start_date=start_date)
        skill = validate_skill(load_skill_source(STRENGTH_SKILL_ID))
        result = dry_run_skill(skill, context, weeks=weeks)
    except Exception as exc:
        if json_output:
            _trainer_json_error(str(exc))
        raise click.ClickException(str(exc)) from exc

    if dry_run:
        payload = {
            "ok": True,
            "legacy": False,
            "dry_run": True,
            "skill_id": STRENGTH_SKILL_ID,
            "actions": result.actions,
            "personalization_applied": result.personalization_applied,
        }
        if json_output:
            click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        else:
            click.echo("DRY-RUN trainer plan（Skill runtime）：")
            for action in result.actions:
                click.echo(f"  - W{action['week']} {action['start']} {action['summary']}")
        return

    if not assume_yes and not json_output:
        click.confirm(f"写入 {len(result.actions)} 个训练到 Apple Calendar？", default=True, abort=True)

    try:
        resolve_apple_backends(config)
    except Exception as exc:
        message = str(exc)
        if json_output:
            _trainer_json_error(message)
        raise click.ClickException(message) from exc

    plan_id = create_skill_instance(
        result.skill,
        context,
        start_date=start_date,
        weeks_total=skill_weeks_total(result.skill),
        materialized_through_week=0,
        personalization_applied=result.personalization_applied,
    )
    try:
        created, failed = _materialize_actions(
            result.actions,
            plan_id=plan_id,
            config=config,
            quiet=json_output,
        )
    except Exception as exc:
        update_plan_status(plan_id, "failed")
        message = str(exc)
        if json_output:
            click.echo(
                json.dumps(
                    versioned_payload(
                        {
                            "ok": False,
                            "error": message,
                            "legacy": False,
                            "skill_id": STRENGTH_SKILL_ID,
                            "plan_id": plan_id,
                        }
                    ),
                    ensure_ascii=False,
                )
            )
            raise click.exceptions.Exit(1)
        raise click.ClickException(message) from exc

    if not created and failed:
        update_plan_status(plan_id, "failed")

    if created and not failed:
        record_materialized_week(plan_id, weeks)

    payload = {
        "ok": not failed,
        "legacy": False,
        "skill_id": STRENGTH_SKILL_ID,
        "plan_id": plan_id,
        "created": created,
        "failed": failed,
        "personalization_applied": result.personalization_applied,
    }
    if created and failed:
        payload["retry_warning"] = (
            "部分训练已写入 Apple 并登记本地 action；不要整周重试，请只处理 failed 项或人工清理后重试。"
        )

    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        if failed:
            raise click.exceptions.Exit(1)
        return

    click.echo(
        f"PASS trainer plan 已通过 Skill runtime 创建: {plan_id}"
        f"（写入 {len(created)} 个，失败 {len(failed)} 个）"
    )
    if created and failed:
        click.echo("WARN 部分训练已写入；不要整周重试，请只处理 failed 项或人工清理后重试。", err=True)
    if failed:
        raise click.exceptions.Exit(1)


@trainer_command.command("log")
@click.argument("message")
@click.option("--config", "-c", "config_path", default=None)
def log(message, config_path):
    """Log workout completion (e.g., 'trainer log "跑了5公里，感觉不错"')."""
    # Find the most recent pending workout action
    actions = get_actions(status="created")
    workout_actions = [a for a in actions if a["type"] == "workout"]

    if not workout_actions:
        strength_instances = [
            item
            for item in list_skill_instances()
            if item.get("skill_id") == STRENGTH_SKILL_ID
        ]
        if strength_instances:
            plan_id = strength_instances[0]["plan_id"]
            click.echo("当前训练计划由 Skills runtime 管理。")
            click.echo("请用通用打卡记录本次训练，例如：")
            click.echo("  nudge log done --metric effort=8")
            click.echo("查看进度: nudge skills status")
            click.echo(f"下周调整: nudge skills adapt {plan_id}")
            return
        click.echo("没有待完成的训练。先用 `nudge trainer plan` 创建计划。")
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
    if _show_strength_skill_status():
        return
    _legacy_workout_status()


def _show_strength_skill_status() -> bool:
    """Show active strength Skill progress. Returns True when one was shown."""
    instances = [
        item
        for item in list_skill_instances()
        if item.get("skill_id") == STRENGTH_SKILL_ID
    ]
    if not instances:
        return False

    skipped_empty = 0
    instance = None
    actions = []
    for candidate in instances:
        candidate_actions = get_actions(plan_id=candidate["plan_id"])
        if candidate_actions:
            instance = candidate
            actions = candidate_actions
            break
        skipped_empty += 1

    if instance is None:
        click.echo("WARN strength Skill 实例没有已登记动作，继续检查旧版训练计划。")
        return False

    if skipped_empty:
        click.echo(f"WARN strength Skill 实例没有已登记动作，已跳过 {skipped_empty} 个空实例。")

    plan_id = instance["plan_id"]
    extra_instances = len(instances) - 1
    if extra_instances > 0:
        click.echo(f"另有 {extra_instances} 个进行中的 strength Skill 实例")

    total = len(actions)
    done = sum(1 for a in actions if a.get("status") == "done")
    skipped = sum(1 for a in actions if a.get("status") == "skipped")
    partial = sum(1 for a in actions if a.get("status") == "partial")
    pending = sum(1 for a in actions if a.get("status") in {"created", "pending", "planned"})
    weeks_total = instance.get("weeks_total") or "?"

    click.echo(f"Skill 训练计划 · {STRENGTH_SKILL_ID}\n")
    click.echo(f"  实例: {plan_id}")
    click.echo(f"  进度: W{instance.get('materialized_through_week')}/{weeks_total}")
    click.echo(f"  总计: {total} 次训练")
    click.echo(f"  ✓ 完成: {done}")
    click.echo(f"  ✗ 跳过: {skipped}")
    if partial > 0:
        click.echo(f"  ◐ 部分完成: {partial}")
    click.echo(f"  ○ 待完成: {pending}")
    click.echo(f"\n  下一步: nudge log done --metric effort=8；nudge skills adapt {plan_id}")
    return True


def _legacy_workout_status() -> None:
    """Show status for legacy weekly_workout plans."""
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
