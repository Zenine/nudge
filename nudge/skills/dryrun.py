"""Deterministic Skill dry-run action preview generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from nudge.skills.engine import apply_adaptations, personalize_skill
from nudge.skills.schema import validate_skill


_DAY_INDEX = {
    "monday": 0,
    "mon": 0,
    "周一": 0,
    "星期一": 0,
    "tuesday": 1,
    "tue": 1,
    "周二": 1,
    "星期二": 1,
    "wednesday": 2,
    "wed": 2,
    "周三": 2,
    "星期三": 2,
    "thursday": 3,
    "thu": 3,
    "周四": 3,
    "星期四": 3,
    "friday": 4,
    "fri": 4,
    "周五": 4,
    "星期五": 4,
    "saturday": 5,
    "sat": 5,
    "周六": 5,
    "星期六": 5,
    "sunday": 6,
    "sun": 6,
    "周日": 6,
    "星期日": 6,
    "星期天": 6,
}


@dataclass(frozen=True)
class SkillDryRunResult:
    """Result from deterministic Skill dry-run preview."""

    skill: dict
    personalization_applied: list[str]
    adaptation_applied: list[str]
    actions: list[dict]


def dry_run_skill(skill: dict, context: dict | None = None, weeks: int = 1) -> SkillDryRunResult:
    """Apply deterministic Skill rules and preview candidate actions.

    This function is intentionally local and deterministic: it does not call LLMs,
    does not read Calendar, and does not write Apple Calendar / Reminders.
    """
    context = context or {}
    week_count = max(1, int(weeks))
    validated = validate_skill(skill)
    personalized = personalize_skill(validated, context)
    adapted = apply_adaptations(personalized.skill, context)
    actions = _generate_actions(adapted.skill, context, week_count)
    return SkillDryRunResult(
        skill=adapted.skill,
        personalization_applied=personalized.applied_rules,
        adaptation_applied=adapted.applied_rules,
        actions=actions,
    )


def _generate_actions(skill: dict, context: dict, weeks: int) -> list[dict]:
    metadata = skill.get("metadata", {})
    template = skill.get("plan_template", {})
    defaults = template.get("defaults", {})
    phases = template.get("phases") or []
    sessions = _session_sequence(phases)
    if not sessions:
        return []

    sessions_per_week = int(defaults.get("sessions_per_week") or len(sessions) or 1)
    preferred_days = _preferred_days(defaults, context, sessions_per_week)
    preferred_time = _preferred_time(defaults, context)
    start = _start_date(context)

    actions = []
    for week in range(1, weeks + 1):
        for slot in range(sessions_per_week):
            session_info = sessions[((week - 1) * sessions_per_week + slot) % len(sessions)]
            phase = session_info["phase"]
            session = session_info["session"]
            scheduled_date = _scheduled_date(start, week, preferred_days[slot % len(preferred_days)])
            duration = int(session.get("duration_minutes") or defaults.get("session_minutes") or 30)
            start_dt = datetime.strptime(
                f"{scheduled_date.isoformat()} {preferred_time}",
                "%Y-%m-%d %H:%M",
            )
            end_dt = start_dt + timedelta(minutes=duration)
            actions.append({
                "type": "calendar_event",
                "source": "skill_dry_run",
                "skill_id": metadata.get("id", "unknown"),
                "skill_title": metadata.get("title", "Untitled Skill"),
                "week": week,
                "phase_id": phase.get("id"),
                "phase_title": phase.get("title"),
                "session_id": session.get("id"),
                "summary": _summary(metadata, session),
                "scheduled_date": scheduled_date.isoformat(),
                "start": start_dt.strftime("%Y-%m-%d %H:%M"),
                "end": end_dt.strftime("%Y-%m-%d %H:%M"),
                "duration_minutes": duration,
            })
    return actions


def _session_sequence(phases: list[dict]) -> list[dict]:
    sessions = []
    for phase in phases:
        for session in phase.get("sessions") or []:
            sessions.append({"phase": phase, "session": session})
    return sessions


def _preferred_days(defaults: dict, context: dict, sessions_per_week: int) -> list[int]:
    profile = context.get("profile") or {}
    raw_days = profile.get("preferred_days") or defaults.get("preferred_days") or []
    day_indices = [_day_index(day) for day in raw_days]
    day_indices = [day for day in day_indices if day is not None]
    if day_indices:
        return day_indices
    return list(range(min(max(sessions_per_week, 1), 7)))


def _preferred_time(defaults: dict, context: dict) -> str:
    profile = context.get("profile") or {}
    return str(
        profile.get("preferred_time")
        or defaults.get("preferred_time")
        or defaults.get("start_time")
        or "09:00"
    )


def _start_date(context: dict) -> date:
    profile = context.get("profile") or {}
    value = profile.get("start_date")
    if value:
        return date.fromisoformat(str(value))
    return date.today()


def _scheduled_date(start: date, week: int, day_index: int) -> date:
    week_anchor = start + timedelta(days=(week - 1) * 7)
    offset = (day_index - week_anchor.weekday()) % 7
    return week_anchor + timedelta(days=offset)


def _day_index(day: Any) -> int | None:
    if isinstance(day, int) and 0 <= day <= 6:
        return day
    key = str(day).strip().lower()
    return _DAY_INDEX.get(key)


def _summary(metadata: dict, session: dict) -> str:
    skill_title = metadata.get("title", "Skill")
    session_title = session.get("title") or session.get("focus") or session.get("id") or "session"
    return f"{skill_title}：{session_title}"
