"""Nudge CLI — Click-based entry point with subcommands."""

import sys

import click

from nudge.brain import configure as configure_brain
from nudge.commands.agent import agent_command
from nudge.commands.briefing import briefing_command
from nudge.commands.chat import chat_command
from nudge.commands.do import do_command
from nudge.commands.doctor import doctor_command
from nudge.commands.docs import docs_command
from nudge.commands.daily import daily_command
from nudge.commands.db import db_command
from nudge.commands.dogfood import dogfood_command
from nudge.commands.failures import failures_command
from nudge.commands.habits import habits_command
from nudge.commands.health import health_command
from nudge.commands.log import check_in_command, log_command
from nudge.commands.daemon import daemon_command
from nudge.commands.mcp import mcp_command
from nudge.commands.reminders import reminders_command
from nudge.commands.review import review_command
from nudge.commands.schedule import schedule_command
from nudge.commands.skills import skills_command
from nudge.commands.trainer import trainer_command
from nudge.config import load_config
from nudge.runtime import load_runtime_config, resolve_config_path


class NudgeGroup(click.Group):
    """Custom group that treats unknown args as a message for 'do' command."""

    # Options that belong to 'do' command
    _do_opts = {"--dry-run", "-n", "--file", "-f", "--json"}
    _global_config_opts = {"--config", "-c"}

    def parse_args(self, ctx, args):
        """If first non-global arg isn't a known subcommand, prepend 'do'."""
        if args:
            insert_at = self._first_command_arg_index(args)
            first = args[insert_at] if insert_at < len(args) else None
            if first is not None and first not in self.commands and (
                first in self._do_opts or not first.startswith("-")
            ):
                args = args[:insert_at] + ["do"] + args[insert_at:]
        return super().parse_args(ctx, args)

    def _first_command_arg_index(self, args):
        index = 0
        while index < len(args):
            arg = args[index]
            if arg in self._global_config_opts:
                index += 2
                continue
            if arg.startswith("--config="):
                index += 1
                continue
            if arg.startswith("-c") and len(arg) > 2:
                index += 1
                continue
            break
        return index


@click.group(cls=NudgeGroup, invoke_without_command=True)
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.pass_context
def cli(ctx, config_path):
    """Nudge — AI Life Coach that actually gets things done."""
    # Configure Brain with LLM settings from config
    try:
        config = load_runtime_config(config_path, loader=load_config)
        if config_path:
            _default_subcommand_config(ctx, config_path)
        configure_brain(config.get("llm"))
    except FileNotFoundError as exc:
        if config_path:
            raise click.ClickException(str(exc)) from exc
        pass  # no config yet, brain will use defaults

    if ctx.invoked_subcommand is None:
        if not sys.stdin.isatty():
            ctx.invoke(do_command, message=sys.stdin.read())
        else:
            click.echo(ctx.get_help())


def _default_subcommand_config(ctx: click.Context, config_path: str) -> None:
    """Pass top-level --config to subcommands without mutating os.environ."""
    resolved = str(resolve_config_path(config_path))
    default_map = dict(ctx.default_map or {})
    for command_name in ctx.command.commands:
        command_defaults = dict(default_map.get(command_name) or {})
        command_defaults.setdefault("config_path", resolved)
        command = ctx.command.commands[command_name]
        if isinstance(command, click.Group):
            _default_group_subcommand_config(command_defaults, command, resolved)
        default_map[command_name] = command_defaults
    ctx.default_map = default_map


def _default_group_subcommand_config(default_map: dict, group: click.Group, config_path: str) -> None:
    """Pass top-level --config through nested command groups."""
    for command_name, command in group.commands.items():
        command_defaults = dict(default_map.get(command_name) or {})
        command_defaults.setdefault("config_path", config_path)
        if isinstance(command, click.Group):
            _default_group_subcommand_config(command_defaults, command, config_path)
        default_map[command_name] = command_defaults


cli.add_command(do_command)
cli.add_command(agent_command)
cli.add_command(mcp_command)
cli.add_command(reminders_command)
cli.add_command(doctor_command)
cli.add_command(dogfood_command)
cli.add_command(failures_command)
cli.add_command(briefing_command)
cli.add_command(trainer_command)
cli.add_command(review_command)
cli.add_command(chat_command)
cli.add_command(schedule_command)
cli.add_command(habits_command)
cli.add_command(health_command)
cli.add_command(daily_command)
cli.add_command(db_command)
cli.add_command(docs_command)
cli.add_command(log_command)
cli.add_command(check_in_command)
cli.add_command(skills_command)
cli.add_command(daemon_command)


def main():
    cli(prog_name="nudge")
