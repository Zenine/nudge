"""Skill Spec validation and deterministic application commands."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import click

from nudge.apple.adapters import resolve_apple_backends
from nudge.commands.do import execute_action
from nudge.config import get_defaults, get_family_aliases, load_config
from nudge.json_contract import versioned_payload
from nudge.state import configure_state, get_actions, log_action, update_plan_status
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
from nudge.skills.runtime import (
    build_tracking_context,
    create_skill_instance,
    get_skill_instance,
    list_skill_instances,
    numeric_metric_ids,
    record_materialized_week,
    skill_weeks_total,
)
from nudge.skills.schema import SkillValidationError, ValidationIssue, collect_validation_issues, validate_skill

_SEMVER_PATCH = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_RETRY_WARNING = "部分动作已写入 Apple 并登记本地 action；不要整周重试，请只处理 failed 项或人工清理后重试。"


def _issue_payload(exc: SkillValidationError) -> list[dict]:
    return [{"path": issue.path, "message": issue.message} for issue in exc.issues]


def _metadata_label(skill: dict) -> str:
    metadata = skill.get("metadata", {})
    title = metadata.get("title", "Untitled Skill")
    skill_id = metadata.get("id", "unknown")
    return f"{title} ({skill_id})"


def _exit_json_error(message: str, *, issues: list[dict] | None = None) -> None:
    payload = {"ok": False, "error": message}
    if issues is not None:
        payload["issues"] = issues
    click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
    raise click.exceptions.Exit(1)


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


def _assessment_options(question: dict) -> list[tuple[str, str]]:
    options = []
    for index, option in enumerate(question.get("options") or [], 1):
        if isinstance(option, dict):
            option_id = str(option.get("id") or option.get("value") or index)
            label = str(option.get("label") or option_id)
        else:
            option_id = str(option)
            label = str(option)
        options.append((option_id, label))
    return options


def _choose_assessment_option(question: dict) -> str:
    options = _assessment_options(question)
    if not options:
        return click.prompt(question.get("question") or question.get("id") or "Answer", type=str)

    prompt = question.get("question") or question.get("id") or "Answer"
    click.echo(prompt)
    for index, (option_id, label) in enumerate(options, 1):
        click.echo(f"  {index}. {label} [{option_id}]")

    lookup = {}
    for index, (option_id, label) in enumerate(options, 1):
        lookup[str(index)] = option_id
        lookup[option_id] = option_id
        lookup[label] = option_id

    while True:
        value = click.prompt("请选择", type=str).strip()
        if value in lookup:
            return lookup[value]
        click.echo("无效选项，请输入编号或选项 id。")


def _choose_assessment_options(question: dict) -> list[str]:
    options = _assessment_options(question)
    if not options:
        raw = click.prompt(question.get("question") or question.get("id") or "Answer", type=str)
        return [item.strip() for item in raw.split(",") if item.strip()]

    prompt = question.get("question") or question.get("id") or "Answer"
    click.echo(prompt)
    for index, (option_id, label) in enumerate(options, 1):
        click.echo(f"  {index}. {label} [{option_id}]")

    lookup = {}
    for index, (option_id, label) in enumerate(options, 1):
        lookup[str(index)] = option_id
        lookup[option_id] = option_id
        lookup[label] = option_id

    while True:
        raw = click.prompt("请选择（多个用逗号分隔）", type=str)
        selected = [item.strip() for item in raw.split(",") if item.strip()]
        if selected and all(item in lookup for item in selected):
            result = []
            for item in selected:
                option_id = lookup[item]
                if option_id not in result:
                    result.append(option_id)
            return result
        click.echo("无效选项，请输入编号或选项 id，多个用逗号分隔。")


def _run_assessment(skill: dict) -> dict:
    """Interactively collect Skill assessment answers."""
    answers = {}
    for question in skill.get("assessment") or []:
        if not isinstance(question, dict):
            continue
        question_id = question.get("id")
        if not question_id:
            continue
        question_type = str(question.get("type") or "text").strip().lower()
        prompt = question.get("question") or question_id

        if question_type == "single_choice":
            answers[question_id] = _choose_assessment_option(question)
        elif question_type == "multi_choice":
            answers[question_id] = _choose_assessment_options(question)
        elif question_type == "number":
            answers[question_id] = click.prompt(prompt, type=float)
        elif question_type == "boolean":
            answers[question_id] = click.confirm(prompt)
        else:
            answers[question_id] = click.prompt(prompt, type=str)
    return answers


def _error_text(error: object) -> str:
    if hasattr(error, "render"):
        try:
            return error.render()
        except Exception:
            pass
    return str(error)


def _action_summary(action: dict) -> str:
    return str(
        action.get("summary")
        or action.get("name")
        or action.get("title")
        or action.get("label")
        or "Untitled action"
    )


def _action_scheduled_at(action: dict) -> str | None:
    value = action.get("start") or action.get("due_date") or action.get("time")
    return str(value) if value else None


def _add_retry_warning(payload: dict, created: list[dict], failed: list[dict]) -> None:
    if created and failed:
        payload["retry_warning"] = _RETRY_WARNING


def _echo_retry_warning(created: list[dict], failed: list[dict]) -> None:
    if created and failed:
        click.echo(f"WARN {_RETRY_WARNING}", err=True)


def _materialize_actions(actions, *, plan_id, config, quiet: bool = False) -> tuple[list[dict], list[dict]]:
    backends = resolve_apple_backends(config)
    defaults = get_defaults(config)
    _, alias_map = get_family_aliases(config)
    created = []
    failed = []

    for candidate in actions:
        action = deepcopy(candidate)
        try:
            ok = execute_action(
                action,
                alias_map,
                defaults,
                quiet=quiet,
                apple_backends=backends,
            )
        except Exception as exc:
            failed.append(
                {
                    "summary": action.get("summary") or action.get("name") or action.get("title"),
                    "week": action.get("week"),
                    "error": _error_text(exc),
                }
            )
            continue
        if ok:
            action_id = log_action(
                action["type"],
                _action_summary(action),
                scheduled_at=_action_scheduled_at(action),
                external_id=action.get("_external_id"),
                plan_id=plan_id,
            )
            action["action_id"] = action_id
            created.append(action)
        else:
            failed.append(
                {
                    "summary": action.get("summary") or action.get("name") or action.get("title"),
                    "week": action.get("week"),
                    "error": _error_text(action.get("_error") or "unknown error"),
                }
            )

    return created, failed


def _echo_action_preview(actions) -> None:
    click.echo("Actions:")
    for action in actions:
        action_type = action.get("type")
        if action_type == "calendar_event":
            click.echo(
                f"  - W{action.get('week')} {action.get('start')} → "
                f"{action.get('end')}  {action.get('summary')}"
            )
        elif action_type == "reminder":
            click.echo(f"  - W{action.get('week')} {action.get('due_date')}  {action.get('name')}")
        else:
            click.echo(f"  - W{action.get('week')} {action.get('summary') or action}")


def _default_session_minutes(skill: dict) -> int | None:
    defaults = ((skill.get("plan_template") or {}).get("defaults") or {})
    value = defaults.get("session_minutes")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _clamp_action_durations(actions: list[dict], max_minutes: int | None) -> list[dict]:
    if not max_minutes:
        return [deepcopy(action) for action in actions]

    clamped = []
    for action in actions:
        updated = deepcopy(action)
        duration = updated.get("duration_minutes")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or int(duration) <= max_minutes:
            clamped.append(updated)
            continue

        updated["duration_minutes"] = max_minutes
        start = updated.get("start")
        if start:
            try:
                start_dt = datetime.strptime(str(start), "%Y-%m-%d %H:%M")
                updated["end"] = (start_dt + timedelta(minutes=max_minutes)).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
        clamped.append(updated)
    return clamped


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


@skills_command.command("status")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def status_command(config_path, json_output):
    """Show active Skill instances and progress."""
    config = load_config(config_path)
    configure_state(config)

    instances = []
    for instance in list_skill_instances():
        plan_id = instance.get("plan_id")
        actions = get_actions(plan_id=plan_id)
        history = build_tracking_context(plan_id, ())["history"]
        instances.append(
            {
                "plan_id": plan_id,
                "skill_id": instance.get("skill_id"),
                "goal": instance.get("goal"),
                "start_date": instance.get("start_date"),
                "weeks_total": instance.get("weeks_total"),
                "materialized_through_week": instance.get("materialized_through_week"),
                "actions_total": len(actions),
                "actions_done": sum(1 for action in actions if action.get("status") == "done"),
                "completion_rate_7d": history.get("completion_rate_7d"),
            }
        )

    if json_output:
        click.echo(json.dumps(versioned_payload({"ok": True, "instances": instances}), ensure_ascii=False))
        return

    if not instances:
        click.echo("没有进行中的 Skill 实例")
        return

    for instance in instances:
        click.echo(
            f"{instance['plan_id']}  {instance['skill_id']}  "
            f"{instance['actions_done']}/{instance['actions_total']} done  "
            f"W{instance['materialized_through_week']}/{instance['weeks_total']}  "
            f"7d={instance['completion_rate_7d']}  {instance['goal']}"
        )


@skills_command.command("start")
@click.argument("skill_source")
@click.option("--context", "context_file", type=click.Path(exists=True, dir_okay=False), help="Context JSON file")
@click.option("--weeks", default=1, type=click.IntRange(1, 12), help="Number of weeks to materialize")
@click.option("--start-date", "start_date_value", default=None, help="Start date YYYY-MM-DD")
@click.option("--dry-run", "-n", is_flag=True, help="Preview without creating a Skill instance or Apple items")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip confirmation")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def start_command(skill_source, context_file, weeks, start_date_value, dry_run, assume_yes, config_path, json_output):
    """Start a Skill by creating an instance and writing its first actions."""
    if json_output and not context_file:
        _exit_json_error("--json 模式必须提供 --context（无交互评估）")

    try:
        config = load_config(config_path)
        configure_state(config)
        skill = validate_skill(load_skill_source(skill_source))
        if context_file:
            context = _load_context(context_file)
        else:
            context = {"assessment": _run_assessment(skill)}

        profile = context.get("profile")
        if profile is None:
            profile = {}
            context["profile"] = profile
        if not isinstance(profile, dict):
            raise click.ClickException("Context profile must contain an object")

        resolved_start_date = start_date_value or profile.get("start_date") or date.today().isoformat()
        try:
            date.fromisoformat(str(resolved_start_date))
        except ValueError as exc:
            raise click.ClickException(f"Invalid --start-date/profile.start_date: {resolved_start_date}") from exc
        profile["start_date"] = str(resolved_start_date)

        result = dry_run_skill(skill, context, weeks=weeks)
        if not result.actions:
            raise click.ClickException("Skill did not generate actions")
    except SkillValidationError as exc:
        if json_output:
            _exit_json_error(f"无法加载 Skill: {exc}", issues=_issue_payload(exc))
        raise click.ClickException(str(exc))
    except click.ClickException as exc:
        if json_output:
            _exit_json_error(exc.message)
        raise
    except Exception as exc:
        if json_output:
            _exit_json_error(str(exc))
        raise click.ClickException(str(exc))

    if dry_run:
        payload = {
            "ok": True,
            "dry_run": True,
            "actions": result.actions,
            "personalization_applied": result.personalization_applied,
        }
        if json_output:
            click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
            return
        click.echo(f"DRY-RUN Skill start preview: {_metadata_label(result.skill)}")
        click.echo("不会创建 Skill instance，也不会写入 Apple Calendar / Reminders。")
        click.echo(
            "Personalization: "
            + (", ".join(result.personalization_applied) if result.personalization_applied else "none")
        )
        _echo_action_preview(result.actions)
        return

    if not assume_yes and not json_output:
        click.echo(f"即将启动 Skill: {_metadata_label(result.skill)}")
        click.echo(
            "Personalization: "
            + (", ".join(result.personalization_applied) if result.personalization_applied else "none")
        )
        _echo_action_preview(result.actions)
        click.confirm("确认创建实例并写入 Apple？", abort=True)

    plan_id = create_skill_instance(
        result.skill,
        context,
        start_date=profile["start_date"],
        weeks_total=skill_weeks_total(result.skill),
        materialized_through_week=0,
        personalization_applied=result.personalization_applied,
    )
    try:
        created, failed = _materialize_actions(result.actions, plan_id=plan_id, config=config, quiet=json_output)
    except Exception as exc:
        update_plan_status(plan_id, "failed")
        if json_output:
            _exit_json_error(str(exc))
        raise click.ClickException(str(exc)) from exc
    if not created and failed:
        update_plan_status(plan_id, "failed")
    if created and not failed:
        record_materialized_week(plan_id, weeks)
    payload = {
        "ok": not failed,
        "dry_run": False,
        "plan_id": plan_id,
        "created": created,
        "failed": failed,
        "personalization_applied": result.personalization_applied,
    }
    _add_retry_warning(payload, created, failed)

    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
    else:
        click.echo(f"PASS Skill instance created: {plan_id}")
        click.echo(f"Created actions: {len(created)}")
        if failed:
            click.echo(f"Failed actions: {len(failed)}", err=True)
            _echo_retry_warning(created, failed)
            for item in failed:
                click.echo(f"  - W{item.get('week')} {item.get('summary')}: {item.get('error')}", err=True)

    if failed:
        raise click.exceptions.Exit(1)


@skills_command.command("adapt")
@click.argument("plan_id")
@click.option("--weeks", default=1, type=click.IntRange(1, 4), help="Number of new weeks to preview/materialize")
@click.option("--apply", "apply_changes", is_flag=True, help="Write next-week actions and advance the cursor")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def adapt_command(plan_id, weeks, apply_changes, config_path, json_output):
    """Adapt a persisted Skill instance from real tracking history."""
    try:
        config = load_config(config_path)
        configure_state(config)

        instance = get_skill_instance(plan_id)
        if instance is None:
            raise click.ClickException(f"找不到 Skill 实例: {plan_id}")

        skill = validate_skill(load_skill_source(instance["skill_id"]))
    except SkillValidationError as exc:
        if json_output:
            _exit_json_error(f"无法加载 Skill: {exc}", issues=_issue_payload(exc))
        raise click.ClickException(f"无法加载 Skill: {exc}")
    except click.ClickException as exc:
        if json_output:
            _exit_json_error(exc.message)
        raise
    except Exception as exc:
        if json_output:
            _exit_json_error(f"无法加载 Skill: {exc}")
        raise click.ClickException(f"无法加载 Skill: {exc}")

    skill_version = (skill.get("metadata") or {}).get("version")
    if skill_version != instance.get("skill_version"):
        click.echo(
            f"WARN Skill version mismatch: instance={instance.get('skill_version')} current={skill_version}",
            err=True,
        )

    context = deepcopy(instance.get("context") or {})
    history = build_tracking_context(plan_id, numeric_metric_ids(skill))["history"]
    context["history"] = history

    materialized_through_week = int(instance.get("materialized_through_week") or 0)
    from_week = materialized_through_week + 1
    to_week = from_week + weeks - 1
    weeks_total = instance.get("weeks_total")
    effective_to_week = to_week
    if weeks_total is not None:
        weeks_total = int(weeks_total)
        if to_week > weeks_total:
            click.echo(f"WARN requested week {to_week} exceeds Skill total weeks {weeks_total}", err=True)
            effective_to_week = min(to_week, weeks_total)

    personalized = personalize_skill(skill, context)
    before_adaptation_minutes = _default_session_minutes(personalized.skill)
    result = dry_run_skill(skill, context, weeks=effective_to_week)
    after_adaptation_minutes = _default_session_minutes(result.skill)
    max_minutes = None
    if (
        after_adaptation_minutes is not None
        and before_adaptation_minutes is not None
        and after_adaptation_minutes < before_adaptation_minutes
    ):
        max_minutes = after_adaptation_minutes
    next_actions = _clamp_action_durations(
        [
            action
            for action in result.actions
            if from_week <= int(action["week"]) <= effective_to_week
        ],
        max_minutes,
    )

    if not apply_changes:
        payload = {
            "ok": True,
            "applied": False,
            "plan_id": plan_id,
            "from_week": from_week,
            "to_week": effective_to_week,
            "adaptation_applied": result.adaptation_applied,
            "history": history,
            "actions": next_actions,
        }
        if json_output:
            click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
            return
        click.echo(f"DRY-RUN Skill adapt preview: {plan_id}")
        click.echo(f"Weeks: {from_week}..{effective_to_week}")
        click.echo("Adaptation: " + (", ".join(result.adaptation_applied) if result.adaptation_applied else "none"))
        click.echo(f"History: {json.dumps(history, ensure_ascii=False, sort_keys=True)}")
        _echo_action_preview(next_actions)
        return

    if next_actions:
        try:
            created, failed = _materialize_actions(next_actions, plan_id=plan_id, config=config, quiet=json_output)
        except Exception as exc:
            payload = {
                "ok": False,
                "applied": True,
                "plan_id": plan_id,
                "from_week": from_week,
                "to_week": effective_to_week,
                "adaptation_applied": result.adaptation_applied,
                "history": history,
                "created": [],
                "failed": [
                    {
                        "summary": "materialization",
                        "week": from_week,
                        "error": _error_text(exc),
                    }
                ],
                "error": _error_text(exc),
            }
            if json_output:
                click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
                raise click.exceptions.Exit(1)
            raise click.ClickException(_error_text(exc)) from exc
    else:
        created, failed = [], []
    if created and not failed:
        record_materialized_week(plan_id, effective_to_week)

    payload = {
        "ok": not failed,
        "applied": True,
        "plan_id": plan_id,
        "from_week": from_week,
        "to_week": effective_to_week,
        "adaptation_applied": result.adaptation_applied,
        "history": history,
        "created": created,
        "failed": failed,
    }
    _add_retry_warning(payload, created, failed)
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
    else:
        click.echo(f"PASS Skill adapt applied: {plan_id}")
        click.echo(f"Created actions: {len(created)}")
        if failed:
            click.echo(f"Failed actions: {len(failed)}", err=True)
            _echo_retry_warning(created, failed)
            for item in failed:
                click.echo(f"  - W{item.get('week')} {item.get('summary')}: {item.get('error')}", err=True)

    if failed:
        raise click.exceptions.Exit(1)


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
