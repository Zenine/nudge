"""Dogfood command — weekly local usage report for Nudge itself."""

import json
from datetime import date, timedelta
from pathlib import Path

import click

from nudge.commands.doctor import run_checks
from nudge.dogfood import (
    build_weekly_dogfood_report,
    render_weekly_dogfood_report,
    save_weekly_dogfood_report,
)
from nudge.json_contract import versioned_payload
from nudge.state import STATE_DIR, get_actions


@click.group("dogfood")
def dogfood_command():
    """Review Nudge's own weekly usage from local state."""


@dogfood_command.command("weekly")
@click.option("--save", is_flag=True, help="Save report to the Nudge state dogfood/YYYY-WW.md path")
@click.option("--note", default="", help="Append a short subjective note to the report")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
@click.option("--export-json", type=click.Path(dir_okay=False), help="Write machine-readable JSON to this file")
def weekly_command(save: bool, note: str, json_output: bool, export_json: str | None):
    """Print a read-only weekly dogfood report."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    period_end = (today + timedelta(days=1)).isoformat()
    actions = get_actions(since=week_start.isoformat(), until=period_end)
    checks = run_checks()
    report = build_weekly_dogfood_report(actions=actions, checks=checks, today=today, note=note)

    payload = versioned_payload({"ok": True, "report": report})

    if export_json:
        output = Path(export_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    click.echo(render_weekly_dogfood_report(report), nl=False)
    if save:
        path = save_weekly_dogfood_report(report, base_dir=STATE_DIR)
        click.echo(f"\n已保存: {path}")
    if export_json:
        click.echo(f"\n已导出 JSON: {export_json}")
