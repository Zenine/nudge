"""Deterministic runtime helpers for persisted Skill instances."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, timedelta
from typing import Any

from nudge.state import create_plan, get_actions, get_plan, get_plans, update_plan_config


SKILL_INSTANCE_KIND = "skill_instance"


def _metadata(skill: dict) -> dict:
    metadata = skill.get("metadata") if isinstance(skill, dict) else None
    return metadata if isinstance(metadata, dict) else {}


def _skill_goal(skill: dict) -> str:
    metadata = _metadata(skill)
    title = metadata.get("title") or metadata.get("id") or "unknown"
    return f"Skill: {title}"


def create_skill_instance(
    skill: dict,
    context: dict,
    *,
    start_date: str,
    weeks_total: int | None,
    materialized_through_week: int,
    personalization_applied: list[str],
) -> str:
    """Persist a Skill instance as a plan config and return the plan id."""
    metadata = _metadata(skill)
    config = {
        "kind": SKILL_INSTANCE_KIND,
        "skill_id": metadata.get("id"),
        "skill_version": metadata.get("version"),
        "context": deepcopy(context),
        "start_date": start_date,
        "weeks_total": weeks_total,
        "materialized_through_week": materialized_through_week,
        "personalization_applied": list(personalization_applied),
    }
    return create_plan(_skill_goal(skill), config=config)


def _instance_from_plan(plan: dict | None) -> dict | None:
    if not plan:
        return None

    try:
        config = json.loads(plan.get("config") or "")
    except (TypeError, json.JSONDecodeError):
        return None

    if not isinstance(config, dict):
        return None
    if config.get("kind") != SKILL_INSTANCE_KIND:
        return None

    instance = dict(config)
    instance.update(
        {
            "plan_id": plan.get("id"),
            "goal": plan.get("goal"),
            "status": plan.get("status"),
            "created_at": plan.get("created_at"),
        }
    )
    return instance


def list_skill_instances(status: str = "active") -> list[dict]:
    """List persisted Skill instances with the requested plan status."""
    instances: list[dict] = []
    for plan in get_plans(status=status):
        instance = _instance_from_plan(plan)
        if instance is not None:
            instances.append(instance)
    return instances


def get_skill_instance(plan_id: str) -> dict | None:
    """Return one Skill instance by plan id, or None for missing/non-Skill plans."""
    return _instance_from_plan(get_plan(plan_id))


def record_materialized_week(plan_id: str, week: int) -> None:
    """Advance an instance materialization cursor without allowing regression."""
    plan = get_plan(plan_id)
    if plan is None:
        raise ValueError(f"skill instance not found: {plan_id}")

    try:
        config = json.loads(plan.get("config") or "")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"skill instance not found: {plan_id}") from exc

    if not isinstance(config, dict) or config.get("kind") != SKILL_INSTANCE_KIND:
        raise ValueError(f"skill instance not found: {plan_id}")

    current = config.get("materialized_through_week")
    config["materialized_through_week"] = max(current if isinstance(current, int) else 0, week)
    update_plan_config(plan_id, config)


def skill_weeks_total(skill: dict) -> int | None:
    """Return the summed number of weeks across plan phases, treating 0 as unknown."""
    plan_template = skill.get("plan_template") if isinstance(skill, dict) else None
    phases = plan_template.get("phases") if isinstance(plan_template, dict) else None
    if not isinstance(phases, list):
        return None

    total = 0
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        weeks = phase.get("weeks", 0)
        if isinstance(weeks, bool):
            continue
        if isinstance(weeks, int):
            total += weeks

    return total or None


def numeric_metric_ids(skill: dict) -> list[str]:
    """Return metric ids whose tracking metric type is number."""
    tracking = skill.get("tracking") if isinstance(skill, dict) else None
    metrics = tracking.get("metrics") if isinstance(tracking, dict) else None
    if not isinstance(metrics, list):
        return []

    ids: list[str] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        metric_id: Any = metric.get("id")
        if metric.get("type") == "number" and isinstance(metric_id, str):
            ids.append(metric_id)
    return ids


def _parse_feedback(feedback_value: Any) -> dict:
    """Return feedback as a dict for stored dict/JSON values, or empty dict."""
    if isinstance(feedback_value, dict):
        return feedback_value
    if not feedback_value:
        return {}
    if isinstance(feedback_value, str):
        try:
            parsed = json.loads(feedback_value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _scheduled_date(action: dict) -> date | None:
    scheduled_at = action.get("scheduled_at")
    if not scheduled_at:
        return None
    try:
        return date.fromisoformat(str(scheduled_at)[:10])
    except ValueError:
        return None


def build_tracking_context(
    plan_id: str,
    metric_ids: list[str] | tuple = (),
    *,
    today: date | None = None,
) -> dict:
    """Build adaptation history variables from persisted action tracking data."""
    current_date = today or date.today()
    actions = get_actions(plan_id=plan_id)
    history: dict[str, int | float] = {}

    for days in (7, 14):
        window_start = current_date - timedelta(days=days - 1)
        window_actions = [
            action
            for action in actions
            if (scheduled_date := _scheduled_date(action)) is not None
            and window_start <= scheduled_date <= current_date
        ]

        total = len(window_actions)
        completed = sum(1 for action in window_actions if action.get("status") == "done")
        partial = sum(1 for action in window_actions if action.get("status") == "partial")
        skipped = sum(1 for action in window_actions if action.get("status") == "skipped")

        history[f"sessions_total_{days}d"] = total
        history[f"sessions_completed_{days}d"] = completed
        history[f"sessions_partial_{days}d"] = partial
        history[f"sessions_skipped_{days}d"] = skipped
        history[f"completion_rate_{days}d"] = round(completed / total, 4) if total else 0.0

        for metric_id in metric_ids:
            samples: list[float] = []
            for action in window_actions:
                if action.get("status") not in {"done", "partial"}:
                    continue
                feedback = _parse_feedback(action.get("feedback"))
                metrics = feedback.get("metrics") if isinstance(feedback, dict) else None
                if not isinstance(metrics, dict):
                    continue
                value = metrics.get(metric_id)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                samples.append(float(value))
            if samples:
                history[f"{metric_id}_avg_{days}d"] = round(sum(samples) / len(samples), 2)

    return {"history": history}
