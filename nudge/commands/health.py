"""Health command — import Apple Health summaries into local state."""

from __future__ import annotations

import json
from datetime import date, timedelta

import click

from nudge.config import load_config
from nudge.health import apply_health_import, parse_apple_health_export
from nudge.json_contract import versioned_payload
from nudge.state import configure_state, get_health_daily_summaries, get_health_workouts


@click.group("health")
def health_command():
    """Import and inspect local Apple Health summaries."""


@health_command.command("import")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--from", "date_from", default=None, help="Import dates from YYYY-MM-DD, inclusive")
@click.option("--to", "date_to", default=None, help="Import dates before YYYY-MM-DD, exclusive")
@click.option("--apply", "apply_changes", is_flag=True, help="Write parsed summaries to SQLite")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def import_command(
    path: str,
    date_from: str | None,
    date_to: str | None,
    apply_changes: bool,
    config_path: str | None,
    json_output: bool,
):
    """Parse an Apple Health export (ZIP or HealthExport JSON file).

    Dry-run is the default: Nudge parses the export and reports aggregate counts
    without writing SQLite. Use --apply after reviewing the result.
    """
    try:
        if config_path:
            configure_state(load_config(config_path))
        _validate_date_filter(date_from, date_to)
        result = parse_apple_health_export(path, date_from=date_from, date_to=date_to)
        updated = (
            apply_health_import(result)
            if apply_changes
            else {"daily_upserted": 0, "workouts_upserted": 0}
        )
        payload = versioned_payload({
            "ok": True,
            "dry_run": not apply_changes,
            "source": result.source_path,
            "date_start": result.date_start,
            "date_end": result.date_end,
            "summary": {
                "daily": len(result.daily_summaries),
                "workouts": len(result.workouts),
                "ignored_route_files": result.ignored_route_files,
                "export_xml": result.export_xml_name,
            },
            "updated": updated,
            "errors": [],
        })
        _emit_import(
            payload,
            json_output,
            _suggest_full_export_import(result, path, date_from, date_to),
        )
    except (OSError, ValueError) as exc:
        payload = versioned_payload({
            "ok": False,
            "dry_run": not apply_changes,
            "source": path,
            "summary": {"daily": 0, "workouts": 0, "ignored_route_files": 0},
            "updated": {"daily_upserted": 0, "workouts_upserted": 0},
            "errors": [{"code": "HEALTH_IMPORT_FAILED", "message": str(exc)}],
        })
        _emit_import(payload, json_output)
        raise click.exceptions.Exit(1)


def _suggest_full_export_import(
    result,
    path: str,
    date_from: str | None,
    date_to: str | None,
) -> str | None:
    if not path.lower().endswith(".json"):
        return None
    if not result.daily_summaries and not result.workouts:
        return "App JSON 在这个时间窗没有可汇总样本：建议改从 Apple Health 导出 ZIP（Health→账户→导出数据）再导入。"

    span_days = None
    if date_from and date_to:
        try:
            span_days = (date.fromisoformat(date_to) - date.fromisoformat(date_from)).days
        except ValueError:
            span_days = None

    if span_days and span_days > 7 and len(result.daily_summaries) <= 1:
        return (
            "App JSON 样本偏少，若需要完整周报趋势，建议改从 Apple Health 导出 ZIP "
            "补一次全量数据。"
        )
    return None


@health_command.command("daily")
@click.option("--from", "date_from", default=None, help="Show dates from YYYY-MM-DD, inclusive")
@click.option("--to", "date_to", default=None, help="Show dates before YYYY-MM-DD, exclusive")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def daily_command(date_from: str | None, date_to: str | None, json_output: bool):
    """Show imported health summaries and workout metadata."""
    start, end = _default_period(date_from, date_to)
    daily = get_health_daily_summaries(start, end)
    workouts = get_health_workouts(start, end)
    payload = versioned_payload({
        "ok": True,
        "from": start,
        "to": end,
        "daily": daily,
        "workouts": workouts,
        "errors": [],
    })
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    click.echo(f"Health daily: {start} → {end}")
    if not daily:
        click.echo("  no imported health summaries")
    for row in daily:
        click.echo(
            "  {date} steps={steps} sleep={sleep}min active={active}kcal rhr={rhr}".format(
                date=row.get("date"),
                steps=_display_number(row.get("steps")),
                sleep=_display_number(row.get("sleep_asleep_minutes")),
                active=_display_number(row.get("active_energy_kcal")),
                rhr=_display_number(row.get("resting_heart_rate")),
            )
        )
    if workouts:
        click.echo(f"  workouts: {len(workouts)}")


def _emit_import(payload: dict, json_output: bool, suggestion: str | None = None) -> None:
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    status = "DRY-RUN" if payload.get("dry_run") else "APPLY"
    click.echo(f"{status} Health import: {payload.get('source')}")
    if not payload.get("ok"):
        click.echo(f"  error: {payload['errors'][0]['message']}", err=True)
        return
    summary = payload["summary"]
    click.echo(
        f"  dates: {payload.get('date_start')} → {payload.get('date_end')} · "
        f"daily={summary.get('daily')} · workouts={summary.get('workouts')} · "
        f"ignored GPX routes={summary.get('ignored_route_files')}"
    )
    if payload.get("dry_run"):
        click.echo("  add --apply to write daily summaries and workout metadata to SQLite")
    else:
        updated = payload.get("updated") or {}
        click.echo(f"  upserted daily={updated.get('daily_upserted')} workouts={updated.get('workouts_upserted')}")
    if suggestion:
        click.echo(f"  提示：{suggestion}")


def _validate_date_filter(date_from: str | None, date_to: str | None) -> None:
    if date_from:
        date.fromisoformat(date_from)
    if date_to:
        date.fromisoformat(date_to)
    if date_from and date_to and date_to <= date_from:
        raise ValueError("--to must be later than --from")


def _default_period(date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    _validate_date_filter(date_from, date_to)
    if date_from or date_to:
        return date_from, date_to
    today = date.today()
    start = today - timedelta(days=7)
    return start.isoformat(), (today + timedelta(days=1)).isoformat()


def _display_number(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
