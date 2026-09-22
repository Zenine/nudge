"""Tests for nudge.commands.habits."""

from click.testing import CliRunner
from nudge.commands.habits import habits_command


def test_habits_empty(monkeypatch):
    monkeypatch.setattr("nudge.commands.habits.get_habit_streaks", lambda: {})
    runner = CliRunner()
    result = runner.invoke(habits_command, [])
    assert "暂无习惯记录" in result.output


def test_habits_show(monkeypatch):
    monkeypatch.setattr("nudge.commands.habits.get_habit_streaks", lambda: {
        "exercise": {"streak": 5, "last_logged": "2026-04-13"},
    })
    runner = CliRunner()
    result = runner.invoke(habits_command, [])
    assert "exercise" in result.output
    assert "5 天" in result.output


def test_habits_log_no_name():
    runner = CliRunner()
    result = runner.invoke(habits_command, ["log"])
    assert "请指定习惯名称" in result.output
