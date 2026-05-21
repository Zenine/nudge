"""Review command — daily/weekly evaluation reports."""
from datetime import date, timedelta

import click

from nudge.adapt import apply_adaptation_plan, build_adaptation_plan
from nudge.brain import NudgeBrainError, suggest_adaptation
from nudge.errors import classify_apple_error
from nudge.feedback import feedback_source_summary, format_feedback_source_summary, normalize_feedback
from nudge.sleep_reminders import SLEEP_AFTER_SKIP_STATUS, is_neutral_sleep_skip
from nudge.state import get_actions, get_habit_streaks


@click.command("review")
@click.argument("period", default="weekly", type=click.Choice(["daily", "weekly"]))
@click.option("--adapt", is_flag=True, help="Generate AI adaptation suggestions")
@click.option("--dry-run", "adapt_dry_run", is_flag=True, help="Preview adaptation plan without writing Calendar")
@click.option("--apply", "adapt_apply", is_flag=True, help="Apply safe adaptation plan after confirmation")
def review_command(period, adapt, adapt_dry_run, adapt_apply):
    """Generate an evaluation report (daily or weekly)."""
    if (adapt_dry_run or adapt_apply) and not adapt:
        raise click.ClickException("--dry-run/--apply 需要和 --adapt 一起使用")
    if period == "daily":
        _daily_review()
    else:
        _weekly_review(adapt=adapt, adapt_dry_run=adapt_dry_run, adapt_apply=adapt_apply)


def _daily_review():
    """Same as evening briefing — today's summary."""
    from nudge.commands.briefing import _evening_briefing
    click.echo(_evening_briefing())


def _weekly_review(adapt: bool = False, adapt_dry_run: bool = False, adapt_apply: bool = False):
    """Weekly stats: completion rate, patterns, streaks."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday
    week_start_str = week_start.isoformat()
    period_end = (today + timedelta(days=1)).isoformat()

    actions = get_actions(since=week_start_str, until=period_end)
    sleep_after_skipped = sum(1 for a in actions if a.get("status") == SLEEP_AFTER_SKIP_STATUS)
    scored_actions = [a for a in actions if not is_neutral_sleep_skip(a)]
    total = len(scored_actions)
    done = sum(1 for a in scored_actions if a["status"] == "done")
    skipped = sum(1 for a in scored_actions if a["status"] == "skipped")
    partial = sum(1 for a in scored_actions if a["status"] == "partial")
    deferred = sum(1 for a in scored_actions if a["status"] == "deferred")
    blocked = sum(1 for a in scored_actions if a["status"] == "blocked")
    created = sum(1 for a in scored_actions if a["status"] in ("created", "pending"))

    click.echo(f"📊 周报 · {week_start_str} ~ {today.isoformat()}\n")

    if total == 0:
        click.echo("  本周暂无执行记录。\n")
        click.echo("  用 `nudge.py trainer plan` 创建训练计划，")
        click.echo("  或 `nudge.py \"消息\"` 创建日历事件来开始追踪。")
        return

    done_score = sum(_action_credit(action) for action in scored_actions)
    rate = done_score / total * 100 if total > 0 else 0
    bar_done = int(rate / 5)
    bar_empty = 20 - bar_done

    click.echo(f"  完成率: {'█' * bar_done}{'░' * bar_empty}  {rate:.0f}% ({_format_score(done_score)}/{total})\n")
    click.echo(f"  ✓ 完成: {done}")
    click.echo(f"  ◐ 部分: {partial}")
    click.echo(f"  ✗ 跳过: {skipped}")
    click.echo(f"  ↷ 延期: {deferred}")
    click.echo(f"  ⛔ 阻塞: {blocked}")
    click.echo(f"  ○ 待完成: {created}")
    if sleep_after_skipped:
        click.echo(f"  ☾ 已睡后作废: {sleep_after_skipped}")

    reason_lines = _unfinished_reason_lines(scored_actions)
    if reason_lines:
        click.echo("\n  未完成原因:")
        for line in reason_lines:
            click.echo(f"    - {line}")

    feedback_needed = _feedback_needed_actions(scored_actions)
    if feedback_needed:
        click.echo("\n  待反馈:")
        for action in feedback_needed:
            scheduled = f" · {action.get('scheduled_at')}" if action.get("scheduled_at") else ""
            click.echo(f"    - {action.get('summary')}{scheduled} · nudge log done --id {action.get('id')}")

    feedback_sources = feedback_source_summary(scored_actions)
    if feedback_sources.get("total"):
        click.echo("\n  反馈来源:")
        click.echo(f"    - {format_feedback_source_summary(feedback_sources)}")

    # Per-day breakdown
    click.echo(f"\n  按天分布:")
    day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for i in range(7):
        d = week_start + timedelta(days=i)
        d_str = d.isoformat()
        day_actions = [a for a in scored_actions if a.get("scheduled_at", "").startswith(d_str)]
        day_done = sum(_action_credit(a) for a in day_actions)
        day_total = len(day_actions)
        if day_total > 0:
            click.echo(f"    {day_names[i]}: {_format_score(day_done)}/{day_total}")

    # Habit streaks
    streaks = get_habit_streaks()
    if streaks:
        click.echo(f"\n  🔥 Streaks:")
        for name, info in streaks.items():
            click.echo(f"    {name}: {info['streak']} 天")

    if adapt:
        _print_adaptation_suggestions(scored_actions, streaks, adapt_dry_run=adapt_dry_run, adapt_apply=adapt_apply)

    click.echo()


def _print_adaptation_suggestions(
    actions: list[dict],
    habit_streaks: dict[str, dict],
    adapt_dry_run: bool = False,
    adapt_apply: bool = False,
):
    """Generate and print AI adaptation suggestions."""
    try:
        suggestions = suggest_adaptation(actions, habit_streaks)
    except NudgeBrainError as e:
        raise click.ClickException(str(e))

    click.echo(f"\n  🧭 调整建议:")
    if not suggestions:
        click.echo("    暂无需要调整的建议，先保持当前节奏。")
        return

    for i, suggestion in enumerate(suggestions, 1):
        title = suggestion.get("title", "未命名建议")
        reason = suggestion.get("reason", "")
        action = suggestion.get("suggestion", "")
        confidence = suggestion.get("confidence")
        confidence_text = ""
        if isinstance(confidence, int | float):
            confidence_text = f" · 置信度 {confidence:.0%}"

        click.echo(f"    {i}. {title}{confidence_text}")
        if reason:
            click.echo(f"       原因：{reason}")
        if action:
            click.echo(f"       建议：{action}")

    if adapt_dry_run or adapt_apply:
        plan = build_adaptation_plan(suggestions, actions)
        _print_adaptation_plan(plan)
        if not adapt_apply:
            click.echo("\n  （dry-run：未写入 Calendar / SQLite）")
            return
        if not any(item.get("safe") for item in plan):
            click.echo("\n  没有可安全自动应用的调整；请先手动处理上面列出的 unsafe 项。")
            return
        click.confirm("\n  应用以上 safe 调整到 Calendar / SQLite？", default=False, abort=True)
        results = apply_adaptation_plan(plan)
        click.echo("\n  已应用:")
        for result in results:
            status = "✓" if result.get("ok") else "✗"
            click.echo(f"    {status} {result.get('operation')} {result.get('action_id') or ''}: {result.get('message')}")
            if not result.get("ok"):
                error = classify_apple_error(
                    "Calendar",
                    "Calendar action",
                    result.get("action_id") or "adaptation",
                    result.get("message") or "",
                )
                click.echo(error.render(indent="      "))


def _print_adaptation_plan(plan: list[dict]):
    """Print dry-run adaptation execution plan."""
    click.echo("\n  🧪 调整预览:")
    if not plan:
        click.echo("    暂无可预览的调整。")
        return
    for i, item in enumerate(plan, 1):
        safe = "safe" if item.get("safe") else "unsafe"
        title = item.get("title") or item.get("summary") or item.get("type")
        click.echo(f"    {i}. [{safe}] {item.get('operation')} · {title}")
        if item.get("summary"):
            click.echo(f"       action: {item.get('summary')}")
        if item.get("start") or item.get("end"):
            click.echo(f"       time: {item.get('start', '?')} → {item.get('end', '?')}")
        if item.get("problems"):
            click.echo(f"       problems: {'; '.join(item['problems'])}")


def _action_credit(action: dict) -> float:
    """Return weekly review credit for one action."""
    if action.get("status") == "done":
        return 1.0
    if action.get("status") == "partial":
        return 0.5
    return 0.0


def _feedback_needed_actions(actions: list[dict]) -> list[dict]:
    return [
        action for action in actions
        if action.get("status") in ("created", "pending")
    ][:10]


def _unfinished_reason_lines(actions: list[dict]) -> list[str]:
    lines = []
    for action in actions:
        if action.get("status") not in ("skipped", "partial", "deferred", "blocked"):
            continue
        feedback = normalize_feedback(action.get("feedback"))
        reason = str(feedback.get("reason") or "").strip()
        next_action = str(feedback.get("next_action") or "").strip()
        note = str(feedback.get("note") or "").strip()
        parts = []
        if reason:
            parts.append(reason)
        if next_action:
            parts.append(next_action)
        detail = " / ".join(parts)
        if note:
            detail = f"{detail} · {note}" if detail else note
        if detail:
            lines.append(f"{action.get('summary')}：{detail}")
    return lines[:10]


def _format_score(value: float) -> str:
    """Format whole/half review credits without trailing .0."""
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}"
