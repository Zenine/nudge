"""Chat command — interactive multi-turn conversation."""

import sys

import click

from nudge.brain import NudgeBrainError, call_llm, suggest_family_routing
from nudge.apple.calendar import get_today_events
from nudge.apple.reminders import get_due_today
from nudge.commands.agent import apply_agent_request, configure_agent_state
from nudge.commands.do import _rewrite_family_group_actions
from nudge.config import (
    get_configured_calendar_names,
    get_family_aliases,
    get_family_members,
    get_family_routing,
    load_config,
)
from nudge.state import configure_state, get_actions, get_habit_streaks
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
@click.argument("message", required=False)
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--dry-run", "-n", is_flag=True, help="Preview detected actions without writing")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON for scripts")
@click.option("--confirmation-token", default=None, help="Token returned by a matching dry-run")
def chat_command(message, config_path, dry_run, json_output, confirmation_token):
    """Interactive chat with Nudge (type 'exit' to quit)."""
    try:
        config = load_config(config_path)
    except Exception as exc:
        if json_output:
            _emit_chat_json_error(str(exc), dry_run=dry_run)
            raise click.exceptions.Exit(1)
        raise
    if config_path:
        configure_state(config)
        configure_agent_state(config)

    if message is not None or json_output:
        text = message
        if text is None and not sys.stdin.isatty():
            text = sys.stdin.read().strip()
        if not text:
            if json_output:
                _emit_chat_json_error("Provide a message or pipe input", dry_run=dry_run)
                raise click.exceptions.Exit(1)
            raise click.ClickException("Provide a message or pipe input")
        payload, exit_code = _run_one_turn(
            text,
            history=[],
            config=config,
            dry_run=dry_run,
            json_output=json_output,
            confirmation_token=confirmation_token,
        )
        if json_output:
            click.echo(json.dumps(payload, ensure_ascii=False))
            if exit_code:
                raise click.exceptions.Exit(exit_code)
        return

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

        try:
            _run_one_turn(
                user_input,
                history=history,
                config=config,
                dry_run=dry_run,
                json_output=False,
                confirmation_token=confirmation_token,
            )
        except NudgeBrainError as e:
            click.echo(f"\nNudge> 出错了: {e}\n")
            continue

        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": ""})


def _run_one_turn(
    user_input: str,
    *,
    history: list[dict],
    config: dict,
    dry_run: bool,
    json_output: bool,
    confirmation_token: str | None,
) -> tuple[dict, int]:
    """Run one chat turn and optionally emit/return detected action results."""
    context = _build_context(config)
    system = CHAT_SYSTEM.format(**context)

    messages_for_prompt = ""
    for msg in history[-10:]:
        role = "用户" if msg["role"] == "user" else "Nudge"
        messages_for_prompt += f"{role}: {msg['content']}\n"
    messages_for_prompt += f"用户: {user_input}"

    response = call_llm(system, messages_for_prompt, task="default")
    actions = _extract_actions(response)
    clean_response = _strip_json_blocks(response)

    if not json_output:
        click.echo(f"\nNudge> {clean_response}\n")

    if not actions:
        return {
            "schema_version": "nudge.cli.v1",
            "ok": True,
            "dry_run": dry_run,
            "message": clean_response,
            "actions": [],
            "errors": [],
        }, 0

    _, alias_map = get_family_aliases(config)
    family_members = get_family_members(config)
    routing = get_family_routing(config)
    llm_router = suggest_family_routing if routing.get("llm_fallback") else None
    actions = _rewrite_family_group_actions(
        actions,
        family_members,
        alias_map,
        routing,
        llm_router=llm_router,
    )
    request = {
        "request_id": "chat",
        "source": "chat",
        "dry_run": dry_run,
        "require_confirmation": json_output and not dry_run,
        "actions": [_to_agent_action(action) for action in actions],
    }
    if confirmation_token:
        request["dry_run_token"] = confirmation_token

    if not json_output:
        click.echo(f"  检测到 {len(actions)} 个待创建项:")
        for i, a in enumerate(actions, 1):
            t = a.get("type", "?")
            s = a.get("summary") or a.get("name") or a.get("label") or a.get("title") or "?"
            click.echo(f"    {i}. [{t}] {s}")
        if not dry_run and not click.confirm("  创建？", default=True):
            click.echo("  已取消。")
            return {
                "schema_version": "nudge.cli.v1",
                "ok": False,
                "dry_run": False,
                "confirmation_required": True,
                "actions": [],
                "errors": [],
            }, 1

    payload, exit_code = apply_agent_request(
        request=request,
        config=config,
        dry_run_override=dry_run,
    )
    return payload, exit_code


def _build_context(config: dict) -> dict:
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")

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


def _to_agent_action(action: dict) -> dict:
    """Convert chat/do-shaped LLM actions to agent apply actions."""
    action_type = action.get("type")
    if action_type == "calendar_event":
        return {
            "type": "calendar_event.create",
            "summary": action.get("summary"),
            "start": action.get("start"),
            "end": action.get("end"),
            "location": action.get("location"),
            "notes": action.get("notes"),
            "target": action.get("target"),
            "calendar_name": action.get("calendar") or action.get("calendar_name"),
        }
    if action_type == "reminder":
        return {
            "type": "reminder.create",
            "name": action.get("name") or action.get("summary"),
            "due_date": action.get("due_date"),
            "body": action.get("body"),
            "priority": action.get("priority", 0),
            "remind_date": action.get("remind_date"),
            "target": action.get("target"),
            "list_name": action.get("list_name") or action.get("reminder_list"),
        }
    if action_type == "note":
        return {
            "type": "note.create",
            "title": action.get("title") or action.get("summary"),
            "body": action.get("body"),
            "target": action.get("target"),
            "folder_name": action.get("folder_name") or action.get("folder"),
        }
    if action_type == "alarm":
        return {
            "type": "alarm.create",
            "time": action.get("time"),
            "label": action.get("label") or action.get("summary"),
        }
    return dict(action)


def _emit_chat_json_error(message: str, *, dry_run: bool) -> None:
    payload = {
        "schema_version": "nudge.cli.v1",
        "ok": False,
        "dry_run": dry_run,
        "actions": [],
        "errors": [
            {
                "code": "CHAT_INPUT_ERROR",
                "title": "Chat input error",
                "detail": message,
            }
        ],
    }
    click.echo(json.dumps(payload, ensure_ascii=False))


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
