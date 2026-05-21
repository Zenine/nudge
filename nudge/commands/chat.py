"""Chat command — interactive multi-turn conversation."""

import sys

import click

from nudge.brain import NudgeBrainError, call_llm, suggest_family_routing
from nudge.apple.calendar import get_today_events
from nudge.apple.reminders import get_due_today
from nudge.config import get_configured_calendar_names, load_config
from nudge.state import get_actions, get_habit_streaks
from datetime import datetime, timedelta
import json

CHAT_SYSTEM = """You are Nudge, an AI life coach and personal assistant. You speak Chinese by default.

Current date/time: {current_datetime}

Today's calendar:
{events}

Today's reminders:
{reminders}

Recent actions:
{actions}

Habit streaks:
{habits}

You can:
1. Answer questions about the user's schedule
2. Create calendar events or reminders — return JSON in your response wrapped in ```json ... ```
3. Give coaching advice, encouragement, and suggestions
4. Help with workout planning, study scheduling, etc.

If the user asks you to create something, include a JSON block in your response:
```json
[{{"type": "calendar_event", "summary": "...", "start": "YYYY-MM-DD HH:MM", "end": "YYYY-MM-DD HH:MM"}}]
```

Otherwise, just respond conversationally in Chinese. Be concise and warm."""


@click.command("chat")
def chat_command():
    """Interactive chat with Nudge (type 'exit' to quit)."""
    click.echo("Nudge Chat · 输入消息开始对话，exit 退出\n")

    history = []

    while True:
        try:
            user_input = click.prompt("你", prompt_suffix="> ", type=str)
        except (click.Abort, EOFError):
            break

        if user_input.strip().lower() in ("exit", "quit", "q", "退出"):
            click.echo("\n再见！")
            break

        context = _build_context()
        system = CHAT_SYSTEM.format(**context)

        # Build messages with history (keep last 10 turns)
        messages_for_prompt = ""
        for msg in history[-10:]:
            role = "用户" if msg["role"] == "user" else "Nudge"
            messages_for_prompt += f"{role}: {msg['content']}\n"
        messages_for_prompt += f"用户: {user_input}"

        try:
            response = call_llm(system, messages_for_prompt, task="default")
        except NudgeBrainError as e:
            click.echo(f"\nNudge> 出错了: {e}\n")
            continue

        # Check if response contains JSON actions
        actions = _extract_actions(response)
        clean_response = _strip_json_blocks(response)

        click.echo(f"\nNudge> {clean_response}\n")

        if actions:
            from nudge.apple.adapters import resolve_apple_backends
            from nudge.commands.do import _rewrite_family_group_actions, execute_action
            from nudge.config import get_defaults, get_family_aliases, get_family_members, get_family_routing, load_config
            from nudge.state import log_action

            config = load_config()
            defaults = get_defaults(config)
            _, alias_map = get_family_aliases(config)
            family_members = get_family_members(config)
            routing = get_family_routing(config)
            apple_backends = resolve_apple_backends(config)
            llm_router = suggest_family_routing if routing.get("llm_fallback") else None
            actions = _rewrite_family_group_actions(
                actions,
                family_members,
                alias_map,
                routing,
                llm_router=llm_router,
            )

            click.echo(f"  检测到 {len(actions)} 个待创建项:")
            for i, a in enumerate(actions, 1):
                t = a.get("type", "?")
                s = a.get("summary") or a.get("name", "?")
                click.echo(f"    {i}. [{t}] {s}")

            if click.confirm("  创建？", default=True):
                for a in actions:
                    if execute_action(a, alias_map, defaults, apple_backends=apple_backends):
                        log_action(
                            action_type=a["type"],
                            summary=a.get("summary") or a.get("name", ""),
                            scheduled_at=a.get("start") or a.get("due_date"),
                            external_id=a.get("_external_id"),
                        )

        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": clean_response})


def _build_context() -> dict:
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")

    config = load_config()
    try:
        events = get_today_events(calendar_names=get_configured_calendar_names(config))
        events_str = "\n".join(
            f"  {e['start']} - {e['end']}  {e['summary']}"
            for e in events
        ) or "  (no events)"
    except Exception as exc:
        events_str = f"  (calendar unavailable: {exc})"

    try:
        reminders = get_due_today()
        reminders_str = "\n".join(
            f"  {r['name']}"
            for r in reminders
        ) or "  (no reminders)"
    except Exception as exc:
        reminders_str = f"  (reminders unavailable: {exc})"

    today = datetime.now().date()
    actions = get_actions(since=today.isoformat(), until=(today + timedelta(days=1)).isoformat())
    actions_str = "\n".join(
        f"  [{a['status']}] {a['summary']}"
        for a in actions[:5]
    ) or "  (none)"

    habits = get_habit_streaks()
    habits_str = "\n".join(
        f"  {name}: {info['streak']} 天"
        for name, info in habits.items()
    ) or "  (none)"

    return {
        "current_datetime": current_datetime,
        "events": events_str,
        "reminders": reminders_str,
        "actions": actions_str,
        "habits": habits_str,
    }


def _extract_actions(response: str) -> list[dict]:
    """Extract JSON action blocks from response text."""
    import re
    pattern = r'```json\s*([\s\S]*?)```'
    matches = re.findall(pattern, response)
    actions = []
    for match in matches:
        try:
            parsed = json.loads(match)
            if isinstance(parsed, list):
                actions.extend(parsed)
            else:
                actions.append(parsed)
        except json.JSONDecodeError:
            pass
    return actions


def _strip_json_blocks(response: str) -> str:
    """Remove JSON code blocks from response for clean display."""
    import re
    return re.sub(r'```json\s*[\s\S]*?```', '', response).strip()
