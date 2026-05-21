"""Brain Service — all LLM calls go through here."""

import json
import math
from datetime import datetime

from nudge.llm import LLMError, create_provider, get_model_for_task
from nudge.sleep_reminders import is_neutral_sleep_skip

# Re-export for backward compat
NudgeBrainError = LLMError

PARSE_SYSTEM = """You are a family scheduling assistant. Parse the user's message and extract ALL actionable items as structured JSON.

Today's date and time: {current_datetime}

Family members: {family_members}

Return a JSON array. Each item must be one of these types:

1. Calendar Event:
{{
  "type": "calendar_event",
  "summary": "Event title",
  "start": "YYYY-MM-DD HH:MM",
  "end": "YYYY-MM-DD HH:MM",
  "person": "family member name or null",
  "location": "location or null",
  "notes": "additional details or null"
}}

2. Reminder:
{{
  "type": "reminder",
  "name": "Reminder title",
  "due_date": "YYYY-MM-DD HH:MM",
  "person": "family member name or null",
  "body": "details or null",
  "priority": 0,
  "remind_date": "YYYY-MM-DD HH:MM or null"
}}

3. Alarm:
{{
  "type": "alarm",
  "time": "HH:MM",
  "label": "What the alarm is for"
}}

Rules:
- If no end time for an event, default to 1 hour after start.
- Resolve relative dates ("tomorrow", "next Tuesday", "下周二") against today's date.
- If a message mentions a family member, set "person" to their name exactly as listed.
- If a message mentions the family group / all family / 家庭组 / 全家 / 家人, set "person" to that exact group alias from the listed family members.
- If no person is mentioned, set "person" to null.
- Reminder name must be a short task title. Do not include the due date or time in "name"; use "due_date" for scheduling and "body" for details.
- Only return valid JSON array. No explanation, no markdown fences."""

BRIEFING_SYSTEM = """You are Nudge, a personal life coach and assistant. Generate a concise morning briefing in Chinese.

Current date/time: {current_datetime}

Today's calendar events:
{events}

Today's due reminders:
{reminders}

Unread emails: {unread_count}

Recent emails:
{recent_emails}

Rules:
- Be concise and actionable. No filler.
- Group by time of day (morning, afternoon, evening).
- Highlight conflicts or tight schedules.
- End with exactly one concrete next step, not generic motivation.
- Keep a calm coach tone: no guilt, no scolding, no productivity theatrics.
- Use plain text, no markdown. Keep it under 300 characters."""

EVENING_SYSTEM = """You are Nudge, a personal life coach and assistant. Generate a concise evening review in Chinese.

Current date/time: {current_datetime}

Today's calendar events:
{events}

Completed actions today:
{completed}

Skipped/pending actions:
{skipped}

Habit streaks:
{habits}

Rules:
- Summarize what was accomplished today.
- Note what was skipped or left incomplete — no guilt, just facts.
- Show habit streak progress.
- Give one specific suggestion for tomorrow.
- Prefer one small next action over broad advice.
- Use plain text, no markdown. Keep it under 300 characters."""

ADAPTATION_SYSTEM = """You are Nudge, a personal life coach and assistant. Suggest practical plan adaptations in Chinese.

Period: {period}

Metrics:
{metrics}

Actions:
{actions}

Habit streaks:
{habits}

Return a JSON array. Each suggestion must use this shape:
{{
  "type": "move / reduce / split / delete / keep / increase",
  "title": "short Chinese title",
  "reason": "why this adjustment is useful",
  "suggestion": "specific next adjustment the user can approve",
  "confidence": 0.0,
  "action_id": "existing action id when changing an existing action",
  "match": "summary text when action_id is unavailable",
  "start": "YYYY-MM-DD HH:MM for move/reduce/increase",
  "end": "YYYY-MM-DD HH:MM for move/reduce/increase",
  "duration_minutes": 10
}}

Rules:
- Use only these types: move, reduce, split, delete, keep, increase.
- Prefer move/reduce/delete for future actions that were skipped or partially completed.
- Include action_id when referencing an existing action from the Actions list.
- Be specific and actionable, not motivational filler.
- Base every suggestion on the provided completion data.
- Keep a coach tone: honest, calm, and non-judgmental.
- If completion is consistently high, suggest a small level-up or keeping the current plan.
- If completion is low, reduce scope, move time slots, or simplify the habit.
- Do not invent external facts.
- Return valid JSON array only. No explanation, no markdown fences."""

CHECK_IN_PARSE_SYSTEM = """You are Nudge, a fast check-in parser. Extract completion feedback from the user's message.

Return one JSON object:
{
  "status": "done / skipped / partial / deferred / blocked",
  "note": "short Chinese note, or empty string",
  "reason": "too_hard / no_time / conflict / low_energy / forgot / unclear / not_important / waiting_on_other, or null",
  "next_action": "keep / reduce / split / reschedule / cancel, or null",
  "metrics": {
    "effort": 1,
    "minutes": 30,
    "distance_km": 2
  },
  "match": "optional short text to match an existing action summary, or null"
}

Rules:
- Use only these status values: done, skipped, partial, deferred, blocked.
- done means the user completed the action.
- skipped means the user did not do it.
- partial means the user did some of it but not all.
- deferred means the user intentionally moved it later.
- blocked means the user cannot proceed because something external is blocking it.
- Use reason only from: too_hard, no_time, conflict, low_energy, forgot, unclear, not_important, waiting_on_other.
- Use next_action only from: keep, reduce, split, reschedule, cancel.
- Extract numeric metrics only when explicitly mentioned.
- Use `match` only when the message names the task or habit.
- Do not invent metrics or completion.
- Return valid JSON object only. No explanation, no markdown fences."""

FAMILY_ROUTING_SYSTEM = "\n".join([
    "You are Nudge's family routing assistant.",
    "",
    "Choose which configured family member keys should receive one family-group action.",
    "",
    "Return one JSON object only:",
    "{",
    '  "assignees": ["member_key"],',
    '  "confidence": 0.0,',
    '  "reason": "short reason"',
    "}",
    "",
    "Rules:",
    "- Use only member keys from the provided family members, or \"all\" for everyone.",
    "- assignees may be a string or an array, but prefer an array.",
    "- confidence must be a number between 0 and 1.",
    "- If unsure, return low confidence.",
    "- Return valid JSON object only. No explanation, no markdown fences.",
])


# Module-level provider instance (lazy init)
_provider = None
_llm_config = None


def _get_provider():
    global _provider, _llm_config
    if _provider is None:
        _provider = create_provider(_llm_config)
    return _provider


def configure(llm_config: dict | None = None):
    """Configure the Brain with LLM settings from config.toml [llm] section."""
    global _provider, _llm_config
    _llm_config = llm_config
    _provider = None  # reset, will be recreated on next call


def _call(system: str, user_message: str, task: str = "default",
          retries: int = 1) -> str:
    """Make an LLM call with retry logic."""
    provider = _get_provider()
    model = get_model_for_task(task, _llm_config)

    for attempt in range(retries + 1):
        try:
            return provider.call(system, user_message, model=model)
        except LLMError:
            if attempt < retries:
                import time
                time.sleep(2 ** attempt)
                continue
            raise


def _parse_json(raw: str) -> list | dict:
    """Parse JSON from LLM output, stripping markdown fences if present."""
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    return json.loads(raw)


def call_llm(system: str, user_message: str, task: str = "default") -> str:
    """Public interface for making LLM calls."""
    return _call(system, user_message, task=task)


def parse_json_response(raw: str) -> list | dict:
    """Public interface for parsing JSON from LLM output."""
    return _parse_json(raw)


def parse_check_in_feedback(text: str) -> dict:
    """Parse natural-language check-in feedback into status, note, metrics, and match."""
    raw = _call(CHECK_IN_PARSE_SYSTEM, text, task="fast")
    try:
        parsed = _parse_json(raw)
    except json.JSONDecodeError:
        raise LLMError(f"Check-in JSON 解析失败: {raw[:200]}")

    if not isinstance(parsed, dict):
        raise LLMError(f"Check-in JSON 必须是对象: {raw[:200]}")
    return parsed


def suggest_family_routing(action: dict, members: list[dict], routing: dict | None) -> dict:
    """Suggest family routing assignees for one action using the LLM."""
    prompt = json.dumps(
        {
            "action": _family_routing_action_payload(action),
            "members": _family_routing_members_payload(members),
            "routing": _family_routing_config_payload(routing),
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    raw = _call(FAMILY_ROUTING_SYSTEM, prompt, task="fast")
    try:
        parsed = _parse_json(raw)
    except json.JSONDecodeError:
        raise LLMError(f"家庭路由 JSON 解析失败: {raw[:200]}")

    if not isinstance(parsed, dict):
        raise LLMError(f"家庭路由 JSON 必须是对象: {raw[:200]}")

    assignees = parsed.get("assignees", [])
    if isinstance(assignees, str):
        normalized_assignees = [assignees]
    elif isinstance(assignees, list):
        normalized_assignees = [str(item) for item in assignees]
    else:
        normalized_assignees = []

    confidence = _safe_family_routing_confidence(parsed.get("confidence"))
    reason = parsed.get("reason")
    return {
        "assignees": normalized_assignees,
        "confidence": confidence,
        "reason": reason if isinstance(reason, str) else "",
    }


def _family_routing_action_payload(action: dict) -> dict:
    """Return minimal action context needed by the family-routing LLM."""
    payload = {}
    for key in ("type", "summary", "name", "label", "title", "start", "end", "due_date", "time", "location"):
        if action.get(key) is not None:
            payload[key] = action.get(key)
    for key in ("body", "notes"):
        if action.get(key) is not None:
            payload[key] = str(action.get(key))[:200]
    return payload


def _family_routing_members_payload(members: list[dict]) -> list[dict]:
    """Return minimal family member context needed by the family-routing LLM."""
    result = []
    for member in members:
        if not isinstance(member, dict):
            continue
        payload = {}
        for key in ("key", "display_name", "name", "role"):
            if member.get(key) is not None:
                payload[key] = member.get(key)
        result.append(payload)
    return result


def _family_routing_config_payload(routing: dict | None) -> dict:
    """Return minimal routing config context needed by the family-routing LLM."""
    if not isinstance(routing, dict):
        return {}

    payload = {}
    for key in ("default", "llm_confidence_threshold"):
        if routing.get(key) is not None:
            payload[key] = routing.get(key)

    rules = routing.get("rules")
    if isinstance(rules, list):
        payload["rules"] = [
            {
                allowed_key: rule.get(allowed_key)
                for allowed_key in ("id", "keywords", "assignees")
                if rule.get(allowed_key) is not None
            }
            for rule in rules
            if isinstance(rule, dict)
        ]
    return payload


def _safe_family_routing_confidence(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(confidence):
        return 0.0
    return confidence


def parse_actions(
    text: str,
    family_members: list[str],
    current_datetime: str | None = None,
) -> list[dict]:
    """Parse natural language into structured actions.

    Returns list of dicts with type: calendar_event | reminder | alarm.
    """
    if current_datetime is None:
        current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")

    system = PARSE_SYSTEM.format(
        current_datetime=current_datetime,
        family_members=", ".join(family_members) if family_members else "none",
    )

    raw = _call(system, text, task="fast")

    try:
        actions = _parse_json(raw)
    except json.JSONDecodeError:
        try:
            raw = _call(
                system + "\n\nIMPORTANT: Return ONLY a valid JSON array.",
                text, task="fast",
            )
            actions = _parse_json(raw)
        except json.JSONDecodeError:
            raise LLMError(f"LLM returned invalid JSON after retry: {raw[:200]}")

    if not isinstance(actions, list):
        actions = [actions]

    return actions


def generate_briefing(
    events: list[dict],
    reminders: list[dict],
    unread_count: int,
    recent_emails: list[dict],
) -> str:
    """Generate a morning briefing summary."""
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")

    events_str = "\n".join(
        f"  {e['start']} - {e['end']}  {e['summary']} ({e.get('calendar', '')})"
        for e in events
    ) or "  (no events today)"

    reminders_str = "\n".join(
        f"  {r.get('due_time', '')}  {r['name']} [{r.get('list', '')}]"
        for r in reminders
    ) or "  (no reminders due)"

    emails_str = "\n".join(
        f"  {e['sender']}: {e['subject']}"
        for e in recent_emails
    ) or "  (no recent emails)"

    system = BRIEFING_SYSTEM.format(
        current_datetime=current_datetime,
        events=events_str,
        reminders=reminders_str,
        unread_count=unread_count,
        recent_emails=emails_str,
    )

    return _call(system, "请生成今日早报", task="default")


def generate_evening_review(
    events: list[dict],
    completed_actions: list[dict],
    skipped_actions: list[dict],
    habit_streaks: dict[str, dict],
) -> str:
    """Generate an evening review summary."""
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")

    events_str = "\n".join(
        f"  {e['start']} - {e['end']}  {e['summary']}"
        for e in events
    ) or "  (no events today)"

    completed_str = "\n".join(
        f"  ✓ {a['summary']}"
        for a in completed_actions
    ) or "  (none)"

    skipped_str = "\n".join(
        f"  ✗ {a['summary']} ({a['status']})"
        for a in skipped_actions
    ) or "  (all done!)"

    habits_str = "\n".join(
        f"  {name}: streak {info['streak']} 天"
        for name, info in habit_streaks.items()
    ) or "  (no habits tracked)"

    system = EVENING_SYSTEM.format(
        current_datetime=current_datetime,
        events=events_str,
        completed=completed_str,
        skipped=skipped_str,
        habits=habits_str,
    )

    return _call(system, "请生成今日晚报", task="default")


def suggest_adaptation(
    actions: list[dict],
    habit_streaks: dict[str, dict],
    period: str = "weekly",
) -> list[dict]:
    """Suggest plan adaptations from recent execution data.

    Returns a list of dicts with type, title, reason, suggestion, confidence.
    """
    actions = [action for action in actions if not is_neutral_sleep_skip(action)]
    if not actions:
        return []

    total = len(actions)
    done = sum(1 for a in actions if a.get("status") == "done")
    skipped = sum(1 for a in actions if a.get("status") == "skipped")
    partial = sum(1 for a in actions if a.get("status") == "partial")
    pending = sum(1 for a in actions if a.get("status") in ("created", "pending"))
    rate = round((done + partial * 0.5) / total * 100) if total else 0

    metrics = "\n".join([
        f"  总数: {total}",
        f"  完成: {done}",
        f"  部分完成: {partial}",
        f"  跳过: {skipped}",
        f"  待完成: {pending}",
        f"  完成率: {rate}%",
    ])

    actions_str = "\n".join(
        _format_action_for_adaptation(action)
        for action in actions[:30]
    )
    if len(actions) > 30:
        actions_str += f"\n  ... 另有 {len(actions) - 30} 项未显示"

    habits_str = "\n".join(
        f"  {name}: streak {info.get('streak', 0)} 天, 最近 {info.get('last_logged', 'unknown')}"
        for name, info in habit_streaks.items()
    ) or "  (no habits tracked)"

    system = ADAPTATION_SYSTEM.format(
        period=period,
        metrics=metrics,
        actions=actions_str,
        habits=habits_str,
    )

    user_message = "请根据本周执行数据给出调整建议" if period == "weekly" else "请根据执行数据给出调整建议"
    raw = _call(system, user_message, task="strong")

    try:
        suggestions = _parse_json(raw)
    except json.JSONDecodeError:
        raise LLMError(f"调整建议 JSON 解析失败: {raw[:200]}")

    if isinstance(suggestions, dict):
        suggestions = [suggestions]
    if not isinstance(suggestions, list):
        raise LLMError(f"调整建议 JSON 必须是数组: {raw[:200]}")

    return suggestions


def _format_action_for_adaptation(action: dict) -> str:
    """Format one action as compact prompt context for adaptation."""
    parts = [
        f"id={action.get('id', '')}",
        f"[{action.get('status', 'unknown')}]",
        action.get("summary") or action.get("name") or "(untitled)",
    ]
    if action.get("type"):
        parts.append(f"type={action['type']}")
    if action.get("scheduled_at"):
        parts.append(f"scheduled={action['scheduled_at']}")
    if action.get("external_id"):
        parts.append("external_id=yes")
    if action.get("feedback"):
        parts.append(f"feedback={action['feedback']}")
    return "  " + " | ".join(parts)


# ── Trainer ─────────────────────────────────────────────────────

TRAINER_PLAN_SYSTEM = """You are a personal fitness trainer. Generate a weekly workout plan based on the user's profile and available time slots.

Today's date: {current_date}

User profile:
{profile}

Current calendar (busy slots this week):
{busy_slots}

Return a JSON array of workout sessions. Each session:
{{
  "day": "YYYY-MM-DD",
  "time": "HH:MM",
  "duration_minutes": 45,
  "type": "upper_body / lower_body / cardio / full_body / rest",
  "summary": "Session title in Chinese",
  "exercises": [
    {{"name": "exercise name", "sets": 3, "reps": 12, "notes": "optional"}}
  ]
}}

Rules:
- Only schedule on the user's preferred days and preferred time.
- Avoid time slots that conflict with existing calendar events.
- Balance muscle groups across the week.
- If the user has injuries, avoid exercises that stress those areas.
- Return valid JSON array only. No explanation."""

TRAINER_LOG_SYSTEM = """You are a fitness tracking assistant. Parse the user's workout completion message into structured data.

Current plan session:
{session}

Return a JSON object:
{{
  "completed": true/false,
  "effort": 1-10,
  "notes": "summary of what the user said",
  "metrics": {{}}
}}

If the user mentions distance, time, weight, or reps, include them in metrics.
Return valid JSON only. No explanation."""


def generate_workout_plan(
    profile: dict,
    busy_slots: list[dict],
) -> list[dict]:
    """Generate a weekly workout plan.

    Returns list of session dicts ready to be written to calendar.
    """
    profile_str = "\n".join(f"  {k}: {v}" for k, v in _flatten_profile(profile).items())
    busy_str = "\n".join(
        f"  {e['start']} - {e['end']}  {e.get('summary', '')}"
        for e in busy_slots
    ) or "  (no existing events)"

    current_date = datetime.now().strftime("%Y-%m-%d (%A)")
    system = TRAINER_PLAN_SYSTEM.format(
        current_date=current_date, profile=profile_str, busy_slots=busy_str
    )
    raw = _call(system, "请生成本周训练计划", task="strong")

    try:
        sessions = _parse_json(raw)
    except json.JSONDecodeError:
        raise LLMError(f"训练计划 JSON 解析失败: {raw[:200]}")

    if not isinstance(sessions, list):
        sessions = [sessions]
    return sessions


def parse_workout_log(text: str, session: dict) -> dict:
    """Parse a workout completion message.

    Returns {completed, effort, notes, metrics}.
    """
    session_str = json.dumps(session, ensure_ascii=False, indent=2)
    system = TRAINER_LOG_SYSTEM.format(session=session_str)
    raw = _call(system, text, task="fast")

    try:
        return _parse_json(raw)
    except json.JSONDecodeError:
        raise LLMError(f"训练记录 JSON 解析失败: {raw[:200]}")


def _flatten_profile(profile: dict) -> dict:
    """Flatten nested profile dict for prompt injection."""
    result = {}
    for k, v in profile.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                result[f"{k}.{k2}"] = v2
        else:
            result[k] = v
    return result
