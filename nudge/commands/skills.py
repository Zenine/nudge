"""Skill Spec validation and deterministic application commands."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import click

from nudge.json_contract import versioned_payload
from nudge.skills.builtins import (
    delete_custom_skill,
    dump_skill_yaml,
    get_custom_skill,
    is_builtin_skill,
    list_all_skills,
    list_builtin_skills,
    load_custom_skill_text,
    load_skill_source,
    write_custom_skill,
    write_custom_skill_with_snapshot,
)
from nudge.skills.engine import apply_adaptations, personalize_skill
from nudge.skills.dryrun import dry_run_skill
from nudge.skills.schema import SkillValidationError, ValidationIssue, collect_validation_issues, validate_skill

_SEMVER_PATCH = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _issue_payload(exc: SkillValidationError) -> list[dict]:
    return [{"path": issue.path, "message": issue.message} for issue in exc.issues]


def _metadata_label(skill: dict) -> str:
    metadata = skill.get("metadata", {})
    title = metadata.get("title", "Untitled Skill")
    skill_id = metadata.get("id", "unknown")
    return f"{title} ({skill_id})"


def _load_context(path: str | None) -> dict:
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text())
    except Exception as exc:
        raise click.ClickException(f"Cannot load context JSON: {exc}")
    if not isinstance(data, dict):
        raise click.ClickException("Context JSON must contain an object")
    return data


def _bump_patch_version(version: str) -> str:
    match = _SEMVER_PATCH.fullmatch(version.strip())
    if not match:
        raise click.ClickException(
            f"Version does not match x.y.z for auto bump: {version!r}, "
            "请先手动更新 metadata.version 再重试"
        )
    major, minor, patch = match.groups()
    return f"{major}.{minor}.{int(patch) + 1}"


def _stamp_skill_metadata(skill: dict, *, bump_version: bool = False) -> dict:
    metadata = dict(skill.get("metadata", {}))
    if bump_version:
        metadata["version"] = _bump_patch_version(str(metadata.get("version", "0.0.0")))
    metadata["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    skill["metadata"] = metadata
    return skill


@click.group("skills")
def skills_command():
    """Validate and apply deterministic Skill Spec rules."""


@skills_command.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def list_command(json_output):
    """List bundled and custom Skills."""
    skills = list_all_skills()
    if json_output:
        click.echo(json.dumps(versioned_payload({"ok": True, "skills": skills}), ensure_ascii=False))
        return

    click.echo("Built-in Skills:")
    for skill in list_builtin_skills():
        click.echo(f"  - {skill['id']}  [{skill['category']}]  {skill['title']}")

    custom_skills = [item for item in skills if item.get("source") == "custom"]
    if custom_skills:
        click.echo("Custom Skills:")
        for skill in custom_skills:
            click.echo(f"  - {skill['id']}  [{skill['category']}]  {skill['title']}  ({skill['version']})")


@skills_command.command("show")
@click.argument("skill_source")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def show_command(skill_source, json_output):
    """Show a bundled Skill, custom Skill, or Skill file."""
    try:
        skill = validate_skill(load_skill_source(skill_source))
    except SkillValidationError as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "issues": _issue_payload(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))

    if json_output:
        click.echo(json.dumps(versioned_payload({"ok": True, "skill": skill}), ensure_ascii=False))
    else:
        click.echo(dump_skill_yaml(skill).rstrip())


@skills_command.command("validate")
@click.argument("skill_source")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
@click.pass_context
def validate_command(ctx, skill_source, json_output):
    """Validate a Skill YAML/JSON file or Skill id."""
    try:
        skill = load_skill_source(skill_source)
    except SkillValidationError as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "issues": _issue_payload(exc)}), ensure_ascii=False))
            ctx.exit(1)
        raise click.ClickException(str(exc))

    issues = collect_validation_issues(skill)
    if issues:
        exc = SkillValidationError(issues)
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "issues": _issue_payload(exc)}), ensure_ascii=False))
            ctx.exit(1)
        raise click.ClickException(str(exc))

    if json_output:
        click.echo(json.dumps(versioned_payload({"ok": True, "issues": [], "skill": skill.get("metadata", {})}), ensure_ascii=False))
    else:
        click.echo(f"PASS Skill valid: {_metadata_label(skill)}")


@skills_command.command("apply")
@click.argument("skill_source")
@click.option("--context", "context_file", type=click.Path(exists=True, dir_okay=False), required=True, help="Context JSON file")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def apply_command(skill_source, context_file, json_output):
    """Apply deterministic personalization and adaptation rules."""
    try:
        skill = validate_skill(load_skill_source(skill_source))
        context = _load_context(context_file)
        personalized = personalize_skill(skill, context)
        adapted = apply_adaptations(personalized.skill, context)
    except SkillValidationError as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "issues": _issue_payload(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))
    except Exception as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "error": str(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))

    payload = {
        "ok": True,
        "skill": adapted.skill,
        "personalization_applied": personalized.applied_rules,
        "adaptation_applied": adapted.applied_rules,
    }
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
    else:
        click.echo(f"PASS Skill applied: {_metadata_label(adapted.skill)}")
        click.echo(
            "Personalization: "
            + (", ".join(personalized.applied_rules) if personalized.applied_rules else "none")
        )
        click.echo("Adaptation: " + (", ".join(adapted.applied_rules) if adapted.applied_rules else "none"))


@skills_command.command("dry-run")
@click.argument("skill_source")
@click.option("--context", "context_file", type=click.Path(exists=True, dir_okay=False), required=True, help="Context JSON file")
@click.option("--weeks", default=1, type=click.IntRange(1, 12), help="Number of weeks to preview")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def dry_run_command(skill_source, context_file, weeks, json_output):
    """Preview candidate Skill actions without writing Apple apps."""
    try:
        skill = validate_skill(load_skill_source(skill_source))
        context = _load_context(context_file)
        result = dry_run_skill(skill, context, weeks=weeks)
    except SkillValidationError as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "issues": _issue_payload(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))
    except Exception as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "error": str(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))

    payload = {
        "ok": True,
        "dry_run": True,
        "skill": result.skill,
        "personalization_applied": result.personalization_applied,
        "adaptation_applied": result.adaptation_applied,
        "actions": result.actions,
    }
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        return

    click.echo(f"DRY-RUN Skill preview: {_metadata_label(result.skill)}")
    click.echo("不会写入 Apple Calendar / Reminders。")
    click.echo(
        "Personalization: "
        + (", ".join(result.personalization_applied) if result.personalization_applied else "none")
    )
    click.echo("Adaptation: " + (", ".join(result.adaptation_applied) if result.adaptation_applied else "none"))
    if not result.actions:
        click.echo("Actions: none")
        return
    click.echo("Actions:")
    for action in result.actions:
        click.echo(f"  - W{action['week']} {action['start']} → {action['end']}  {action['summary']}")


@skills_command.command("create")
@click.argument("skill_source", type=click.Path(exists=True, dir_okay=False))
@click.option("--bump-version", "bump_version", is_flag=True, help="Auto bump patch version before writing")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def create_command(skill_source, bump_version, json_output):
    """Create a custom Skill from file into `~/.nudge/skills/<skill-id>.yaml`."""
    try:
        skill = validate_skill(load_custom_skill_text(Path(skill_source).expanduser()))
        skill = _stamp_skill_metadata(skill, bump_version=bump_version)
        write_custom_skill(skill, allow_overwrite=False)
    except SkillValidationError as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "issues": _issue_payload(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))
    except OSError as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "error": str(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(f"Cannot create custom Skill: {exc}")

    payload = {
        "ok": True,
        "action": "create",
        "skill": skill,
    }
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        return

    click.echo(f"PASS Skill created: {_metadata_label(skill)}")


@skills_command.command("update")
@click.argument("skill_id")
@click.argument("skill_source", type=click.Path(exists=True, dir_okay=False))
@click.option("--bump-version", "bump_version", is_flag=True, help="Auto bump patch version before writing")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def update_command(skill_id, skill_source, bump_version, json_output):
    """Update an existing custom Skill in place and keep versioned history."""
    try:
        _ = get_custom_skill(skill_id)
    except SkillValidationError as exc:
        if is_builtin_skill(skill_id):
            exc = SkillValidationError([
                ValidationIssue("skill", f"built-in Skill cannot be updated: {skill_id}"),
            ])
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "issues": _issue_payload(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))

    try:
        skill = validate_skill(load_custom_skill_text(Path(skill_source).expanduser()))
        if skill.get("metadata", {}).get("id") != skill_id:
            raise click.ClickException(
                f"Source skill id mismatch: file has {skill.get('metadata', {}).get('id')}, expected {skill_id}"
            )
        skill = _stamp_skill_metadata(skill, bump_version=bump_version)
        write_custom_skill_with_snapshot(skill)
    except SkillValidationError as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "issues": _issue_payload(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))
    except click.ClickException:
        raise
    except Exception as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "error": str(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(f"Cannot update custom Skill: {exc}")

    payload = {
        "ok": True,
        "action": "update",
        "skill": skill,
    }
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        return

    click.echo(f"PASS Skill updated: {_metadata_label(skill)}")


@skills_command.command("delete")
@click.argument("skill_id")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def delete_command(skill_id, json_output):
    """Delete a custom Skill from local skill store."""
    try:
        delete_custom_skill(skill_id)
    except SkillValidationError as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "issues": _issue_payload(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))

    payload = {"ok": True, "action": "delete", "skill_id": skill_id}
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        return

    click.echo(f"PASS Skill deleted: {skill_id}")
