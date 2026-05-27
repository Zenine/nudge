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


class NudgeGroup(click.Group):
    """Custom group that treats unknown args as a message for 'do' command."""

    # Options that belong to 'do' command
    _do_opts = {"--dry-run", "-n", "--file", "-f", "--config", "-c", "--json"}

    def parse_args(self, ctx, args):
        """If first arg isn't a known subcommand, prepend 'do'."""
        if args:
            first = args[0]
            if first not in self.commands and (
                first in self._do_opts or not first.startswith("-")
            ):
                args = ["do"] + args
        return super().parse_args(ctx, args)


@click.group(cls=NudgeGroup, invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Nudge — AI Life Coach that actually gets things done."""
    # Configure Brain with LLM settings from config
    try:
        config = load_config()
        configure_brain(config.get("llm"))
    except FileNotFoundError:
        pass  # no config yet, brain will use defaults

    if ctx.invoked_subcommand is None:
        if not sys.stdin.isatty():
            ctx.invoke(do_command, message=sys.stdin.read())
        else:
            click.echo(ctx.get_help())


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
