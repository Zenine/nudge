"""Habits command — view and manage habit streaks."""

import click

from nudge.state import get_habit_streaks, update_habit


@click.command("habits")
@click.argument("action", required=False, type=click.Choice(["log"]))
@click.argument("habit_name", required=False)
def habits_command(action, habit_name):
    """View habit streaks or log a habit.

    Examples:
        nudge.py habits              # show all streaks
        nudge.py habits log reading  # mark 'reading' as done today
    """
    if action == "log":
        if not habit_name:
            click.echo("请指定习惯名称: nudge.py habits log <name>")
            return
        update_habit(habit_name)
        streaks = get_habit_streaks()
        info = streaks.get(habit_name, {"streak": 1})
        click.echo(f"  ✓ {habit_name} 已打卡！streak: {info['streak']} 天")
        return

    streaks = get_habit_streaks()
    if not streaks:
        click.echo("暂无习惯记录。\n")
        click.echo("在 config.toml [user.habits] 中配置要追踪的习惯，")
        click.echo("然后用 `nudge.py habits log <habit>` 打卡。")
        return

    click.echo("🔥 习惯打卡\n")
    for name, info in streaks.items():
        streak = info["streak"]
        last = info["last_logged"]
        fire = "🔥" if streak >= 7 else "✓" if streak >= 1 else "○"
        click.echo(f"  {fire} {name}: {streak} 天 (最近: {last})")
