"""Bridge deterministic Skill dry-run actions into the confirmed agent-apply path.

Skill ``dry-run`` previews are otherwise a dead end (printed, never written).
These helpers convert those previews into ``calendar_event.create`` agent actions
and wrap them in a ``plan_driven`` request so the existing ``apply_agent_request``
engine performs the same dry-run -> text-plan confirmation -> real write flow used
by ``nudge agent apply``. The helpers are pure and deterministic: they never write
Apple apps or call an LLM.
"""

from __future__ import annotations

from typing import Any

# Skill dry-run emits calendar_event or reminder previews (see skills/dryrun.py).
# Reject anything else loudly rather than silently dropping it.
SKILL_SCHEDULABLE_TYPES = {"calendar_event", "reminder"}


def skill_actions_to_agent_actions(
    actions: list[dict],
    *,
    calendar: str | None = None,
    reminder_list: str | None = None,
) -> list[dict]:
    """Convert Skill dry-run actions into agent ``*.create`` actions.

    ``calendar_event`` previews become ``calendar_event.create``; ``reminder``
    previews (``plan_template`` ``action_type: reminder``) become
    ``reminder.create``. The dry-run ``start`` / ``end`` / ``due_date`` fields
    are already formatted as ``"%Y-%m-%d %H:%M"``, which is exactly what agent
    apply expects, so no time conversion is needed.
    """
    agent_actions: list[dict] = []
    for action in actions:
        action_type = action.get("type")
        if action_type not in SKILL_SCHEDULABLE_TYPES:
            raise ValueError(
                f"unsupported skill action type for scheduling: {action_type!r}"
            )
        notes = _skill_notes(action)
        item: dict[str, Any]
        if action_type == "reminder":
            item = {
                "type": "reminder.create",
                "name": action.get("name") or action["summary"],
                "due_date": action.get("due_date") or action["start"],
            }
            if notes:
                item["body"] = notes
            if reminder_list:
                item["target"] = {"list": reminder_list}
        else:
            item = {
                "type": "calendar_event.create",
                "summary": action["summary"],
                "start": action["start"],
                "end": action["end"],
            }
            if notes:
                item["notes"] = notes
            if calendar:
                item["target"] = {"calendar": calendar}
        agent_actions.append(item)
    return agent_actions


def _skill_notes(action: dict) -> str:
    """Human-readable provenance so scheduled events trace back to the Skill."""
    parts: list[str] = []
    if action.get("skill_title"):
        parts.append(str(action["skill_title"]))
    week = action.get("week")
    if week:
        parts.append(f"W{week}")
    if action.get("phase_title"):
        parts.append(str(action["phase_title"]))
    return " · ".join(parts)


def chunk_actions(actions: list[dict], size: int) -> list[list[dict]]:
    """Split actions into batches of at most ``size`` (agent apply caps at 10)."""
    if size < 1:
        raise ValueError("chunk size must be >= 1")
    return [actions[i : i + size] for i in range(0, len(actions), size)]


def build_skill_agent_request(
    agent_actions: list[dict],
    *,
    source: str,
    text_plan_ref: str,
    request_id: str,
    dry_run: bool,
    dry_run_token: str | None = None,
) -> dict:
    """Wrap agent actions in a plan-driven, confirmation-gated agent request.

    ``plan_driven`` + ``text_plan_confirmed`` + a non-empty ``text_plan_ref`` are
    required by ``apply_agent_request`` before any plan-driven write; the caller
    must point ``text_plan_ref`` at the reviewed human-readable plan.
    """
    return {
        "request_id": request_id,
        "source": source,
        "dry_run": dry_run,
        "require_confirmation": True,
        "dry_run_token": dry_run_token,
        "plan_driven": True,
        "text_plan_confirmed": True,
        "text_plan_ref": text_plan_ref,
        "actions": agent_actions,
    }
