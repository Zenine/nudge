"""Documentation maintenance commands."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import click

from nudge.docs_audit import audit_docs
from nudge.json_contract import versioned_payload


@click.group("docs")
def docs_command():
    """Audit and maintain project documentation."""
    pass


@docs_command.command("audit")
@click.option("--root", "root_path", default=".", show_default=True, help="Repository root to audit.")
@click.option(
    "--stale-days",
    default=30,
    show_default=True,
    type=click.IntRange(1, 3650),
    help="Age threshold for stale plans/specs.",
)
@click.option(
    "--max-entrypoint-lines",
    default=500,
    show_default=True,
    type=click.IntRange(50, 5000),
    help="Line threshold for README suggestions.",
)
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON.")
def audit_command(root_path: str, stale_days: int, max_entrypoint_lines: int, json_output: bool):
    """Report stale, broken, or low-value documentation without mutating files."""
    report = audit_docs(
        Path(root_path),
        today=date.today(),
        stale_days=stale_days,
        max_entrypoint_lines=max_entrypoint_lines,
    )
    payload = versioned_payload({"ok": report.get("ok", False), "report": report})

    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
    else:
        click.echo(render_docs_audit_report(report))

    if not report.get("ok", False):
        raise click.exceptions.Exit(1)


def render_docs_audit_report(report: dict) -> str:
    """Render a compact human-readable docs audit report."""
    summary = report.get("summary") or {}
    lines = [
        "Docs audit",
        (
            f"  errors={summary.get('errors', 0)} "
            f"warnings={summary.get('warnings', 0)} "
            f"suggestions={summary.get('suggestions', 0)}"
        ),
    ]
    for label, key in (("Errors", "errors"), ("Warnings", "warnings"), ("Suggestions", "suggestions")):
        items = report.get(key) or []
        if not items:
            continue
        lines.append(f"\n{label}:")
        for item in items:
            path = item.get("path")
            target = item.get("target")
            suffix = ""
            if path:
                suffix += f" · {path}"
            if target:
                suffix += f" -> {target}"
            lines.append(f"  - {item.get('code')}: {item.get('message')}{suffix}")
    return "\n".join(lines)
