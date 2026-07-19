"""Low-friction feedback pullback and batch status writeback."""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import click

from nudge.config import DEFAULT_LLM_CONFIG, load_config
from nudge.feedback import STATUS_ALLOWED, STATUS_NEXT_ACTIONS, STATUS_REASONS, build_feedback
from nudge.feedback_interview import (
    FEEDBACK_INTERVIEW_DEFAULT_LIMIT,
    FEEDBACK_INTERVIEW_DEFAULT_SCOPE,
    FEEDBACK_INTERVIEW_PROTOCOL_VERSION,
    FeedbackQuestionBuildResult,
    build_gpt_followup_questions,
    normalize_interview_response,
    plan_sleep_derived_effects,
    sanitize_terminal_text,
    select_feedback_candidates,
)
from nudge.json_contract import versioned_payload
from nudge.llm import get_model_for_task
from nudge.state import (
    FeedbackInterviewConflictError,
    apply_feedback_interview_batch,
    complete_action,
    get_action,
    get_actions,
    partial_action,
    skip_action,
    update_action_status,
)

_PENDING_STATUSES = {"created", "pending"}
_INTERVIEW_RESOLUTIONS = ("done", "partial", "skipped", "deferred", "blocked", "unconfirmed")


@dataclass(frozen=True)
class _FeedbackUpdate:
    action_id: str
    status: str
    note: str | None = None
    reason: str | None = None
    next_action: str | None = None
    source: str | None = None
    feedback: dict[str, Any] | None = None


@click.group("feedback")
def feedback_command():
    """List pending feedback and batch-write action status updates."""


@feedback_command.command("today")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def today_command(json_output: bool):
    """List today's actions that still need completion feedback."""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    actions = get_actions(since=today.isoformat(), until=tomorrow.isoformat())
    items = [_feedback_item(action) for action in actions if action.get("status") in _PENDING_STATUSES]
    payload = versioned_payload({
        "ok": True,
        "period": {"start": today.isoformat(), "end": tomorrow.isoformat()},
        "total": len(items),
        "items": items,
    })
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if not items:
        click.echo("今天没有待反馈 action。")
        return
    click.echo("今天待反馈 action:")
    for item in items:
        scheduled = f" · {item.get('scheduled_at')}" if item.get("scheduled_at") else ""
        click.echo(f"- {item['summary']}{scheduled}")
        click.echo(f"  done: {item['quick_commands']['done']}")
        click.echo(f"  partial: {item['quick_commands']['partial']}")
        click.echo(f"  skipped: {item['quick_commands']['skipped']}")


@feedback_command.command("interview")
@click.option(
    "--scope",
    type=click.Choice(["week-overdue", "today", "all-overdue"], case_sensitive=False),
    default=FEEDBACK_INTERVIEW_DEFAULT_SCOPE,
    show_default=True,
    help="Candidate scope for this interview batch",
)
@click.option(
    "--limit",
    type=click.IntRange(1, 50),
    default=FEEDBACK_INTERVIEW_DEFAULT_LIMIT,
    show_default=True,
    help="Maximum actions in this interview batch",
)
def interview_command(scope: str, limit: int):
    """Collect structured feedback in one TTY interview and atomic commit."""
    if not _is_interactive_terminal():
        raise click.ClickException(
            "FEEDBACK_INTERVIEW_TTY_REQUIRED: feedback interview requires an interactive terminal"
        )
    try:
        _run_feedback_interview(scope=scope, limit=limit)
    except click.Abort:
        click.echo("FEEDBACK_INTERVIEW_CANCELLED: 已取消，数据库未写入。", err=True)
        raise click.exceptions.Exit(130)


def _run_feedback_interview(*, scope: str, limit: int) -> None:
    now = _interview_now()
    all_actions = get_actions()
    batch = select_feedback_candidates(all_actions, scope=scope, now=now, limit=limit)
    if not batch.items:
        click.echo("FEEDBACK_INTERVIEW_EMPTY: 当前 scope 没有待反馈 action。")
        return

    click.echo(f"本批 {len(batch.items)} / 总候选 {batch.total} / 剩余 {batch.remaining}")
    normal_actions = [action for action in batch.items if action.get("risk") == "normal"]
    high_risk_actions = [action for action in batch.items if action.get("risk") == "high"]
    results = []

    if normal_actions:
        click.echo("\n普通分组")
        for action in normal_actions:
            results.append(_interview_one_action(action, allow_gpt=True, now=now))

    allow_high_risk_gpt = False
    if high_risk_actions:
        provider, model = _configured_fast_model()
        click.echo("\n高风险分组：不预选、不自动判断。")
        click.echo(f"provider={sanitize_terminal_text(provider)} model={sanitize_terminal_text(model)}")
        click.echo("发送字段：summary, type, scheduled_at, risk, core")
        allow_high_risk_gpt = click.confirm("允许本组使用 GPT 追问？", default=False)
        for action in high_risk_actions:
            results.append(
                _interview_one_action(
                    action,
                    allow_gpt=allow_high_risk_gpt,
                    now=now,
                )
            )

    updates = [_interview_result_update(result, scope=scope) for result in results]
    derived = plan_sleep_derived_effects(all_actions, updates)
    _render_interview_summary(results, derived)
    if any(result["action"].get("type") == "reminder" for result in results):
        click.echo("提示：本次只更新 Nudge SQLite；Apple Reminder 如仍存在，需要另行同步或人工处理。")
    if not click.confirm("确认一次性写入以上全部反馈？", default=False):
        click.echo("FEEDBACK_INTERVIEW_CANCELLED: 已取消，数据库未写入。", err=True)
        raise click.exceptions.Exit(130)

    action_by_id = {str(action.get("id") or ""): action for action in all_actions}
    snapshots = {str(result["action"]["id"]): result["action"] for result in results}
    atomic_updates = []
    for result, update in zip(results, updates):
        action = result["action"]
        resolution = result["core"]["resolution"]
        atomic_updates.append({
            "id": action["id"],
            "status": action.get("status") if resolution == "unconfirmed" else resolution,
            "completed_at": update.get("completed_at"),
            "feedback": update["feedback"],
        })
    for effect in derived:
        effect_id = str(effect["id"])
        if effect_id not in action_by_id:
            raise click.ClickException(f"FEEDBACK_INTERVIEW_SCHEMA_INVALID: missing derived action {effect_id}")
        snapshots[effect_id] = action_by_id[effect_id]
        atomic_updates.append({
            "id": effect_id,
            "status": effect["status"],
            "completed_at": effect.get("completed_at"),
            "feedback": effect["feedback"],
        })

    try:
        applied = apply_feedback_interview_batch(atomic_updates, snapshots=snapshots)
    except FeedbackInterviewConflictError as exc:
        ids = ", ".join(exc.action_ids)
        raise click.ClickException(
            f"FEEDBACK_INTERVIEW_CONFLICT: action 已在访谈期间变化，请重新运行：{ids}"
        ) from None
    except ValueError:
        raise click.ClickException(
            "FEEDBACK_INTERVIEW_SCHEMA_INVALID: 最终反馈结构无效，整批未写入。"
        ) from None
    except sqlite3.Error:
        raise click.ClickException(
            "FEEDBACK_INTERVIEW_WRITE_FAILED: SQLite 整批写入失败，已回滚。"
        ) from None
    click.echo(f"已写入 {len(applied)} 条本地状态（主反馈 {len(results)}，睡眠派生 {len(derived)}）。")


def _interview_one_action(action: dict, *, allow_gpt: bool, now: datetime) -> dict[str, Any]:
    summary = sanitize_terminal_text(action.get("summary"))
    scheduled = sanitize_terminal_text(action.get("scheduled_at"))
    click.echo(f"\n- {summary} · {scheduled}")
    resolution = click.prompt(
        "结果",
        type=click.Choice(list(_INTERVIEW_RESOLUTIONS), case_sensitive=False),
        show_choices=True,
    ).lower()
    core: dict[str, Any] = {"resolution": resolution}

    if resolution == "partial":
        core["note"] = _prompt_required_text("补充说明")
        core["next_action"] = _prompt_choice("下一步", STATUS_NEXT_ACTIONS)
    elif resolution in {"skipped", "deferred", "blocked"}:
        core["reason"] = _prompt_choice("原因", STATUS_REASONS)
        core["next_action"] = _prompt_choice("下一步", STATUS_NEXT_ACTIONS)
        note = _prompt_optional_text("补充说明（可留空）")
        if note:
            core["note"] = note
    elif resolution == "unconfirmed":
        note = _prompt_optional_text("无法确认的说明（可留空）")
        if note:
            core["note"] = note

    if allow_gpt:
        question_result = build_gpt_followup_questions(action, core)
    else:
        question_result = FeedbackQuestionBuildResult(questions=[], mode="core_only")
    if question_result.warning_code:
        click.echo(f"{question_result.warning_code}: 当前 action 已降级为固定核心题。")
    responses = [_prompt_gpt_response(question) for question in question_result.questions]
    return {
        "action": action,
        "core": core,
        "question_mode": question_result.mode,
        "responses": responses,
        "completed_at": now.strftime("%Y-%m-%d %H:%M") if resolution in {"done", "partial"} else action.get("completed_at"),
    }


def _interview_result_update(result: dict, *, scope: str) -> dict[str, Any]:
    action = result["action"]
    core = result["core"]
    feedback = build_feedback(
        source="nudge feedback interview",
        channel="cli.feedback.interview",
        source_type="subjective",
        note=core.get("note"),
        reason=core.get("reason"),
        next_action=core.get("next_action"),
        extra={
            "interview": {
                "protocol_version": FEEDBACK_INTERVIEW_PROTOCOL_VERSION,
                "scope": scope,
                "resolution": core["resolution"],
                "question_mode": result["question_mode"],
                "responses": result["responses"],
            }
        },
    )
    return {
        "id": action["id"],
        "resolution": core["resolution"],
        "completed_at": result.get("completed_at"),
        "sleep_event_at": action.get("scheduled_at") if core["resolution"] == "done" else None,
        "feedback": feedback,
    }


def _prompt_gpt_response(question: dict) -> dict[str, Any]:
    click.echo(f"GPT 追问：{sanitize_terminal_text(question['prompt'])}")
    question_type = question["type"]
    options = question.get("options") or []
    if question_type in {"single_choice", "multi_choice"}:
        for index, option in enumerate(options, start=1):
            click.echo(f"  {index}. {sanitize_terminal_text(option)}")
    while True:
        raw = _prompt_optional_text("回答（留空跳过）")
        if not raw:
            return normalize_interview_response(question, None, skipped=True)
        try:
            if question_type == "boolean":
                normalized = raw.strip().lower()
                if normalized in {"是", "yes", "y", "true", "1"}:
                    answer: object = True
                elif normalized in {"否", "no", "n", "false", "0"}:
                    answer = False
                else:
                    raise ValueError("请输入是或否")
            elif question_type == "single_choice":
                index = int(raw)
                if not 1 <= index <= len(options):
                    raise ValueError("选项编号超出范围")
                answer = options[index - 1]
            elif question_type == "multi_choice":
                indexes = [int(value.strip()) for value in raw.replace("，", ",").split(",")]
                if any(not 1 <= index <= len(options) for index in indexes):
                    raise ValueError("选项编号超出范围")
                answer = [options[index - 1] for index in indexes]
            else:
                answer = raw
            user_text = None
            if question_type in {"single_choice", "boolean", "multi_choice"}:
                user_text = _prompt_optional_text("补充文字（可留空）") or None
            return normalize_interview_response(question, answer, user_text=user_text)
        except (ValueError, IndexError):
            click.echo("输入无效，请按题目要求重试。")


def _render_interview_summary(results: list[dict], derived: list[dict]) -> None:
    click.echo("\n统一确认摘要")
    for risk, label in (("normal", "普通分组"), ("high", "高风险分组")):
        grouped = [result for result in results if result["action"].get("risk") == risk]
        if not grouped:
            continue
        click.echo(f"{label}（确认）")
        for result in grouped:
            action = result["action"]
            resolution = result["core"]["resolution"]
            summary = sanitize_terminal_text(action.get("summary"))
            scheduled = sanitize_terminal_text(action.get("scheduled_at"))
            click.echo(f"- {summary} · {scheduled} -> {resolution}")
            for key in ("reason", "next_action", "note"):
                value = result["core"].get(key)
                if value:
                    click.echo(f"  {key}: {sanitize_terminal_text(value)}")
            click.echo(f"  question_mode: {result['question_mode']}")
            for response in result["responses"]:
                prompt = sanitize_terminal_text(response.get("prompt"))
                answer = sanitize_terminal_text(_format_interview_answer(response))
                click.echo(f"  GPT：{prompt} -> {answer}")
                if response.get("user_text"):
                    click.echo(f"    补充文字：{sanitize_terminal_text(response['user_text'])}")
            if resolution == "unconfirmed":
                click.echo("  仍需人工确认")
    if derived:
        click.echo("睡眠派生变更")
        for effect in derived:
            click.echo(f"- {sanitize_terminal_text(effect.get('summary'))} -> {effect['status']}")
            reason = (effect.get("feedback") or {}).get("note")
            if reason:
                click.echo(f"  原因：{sanitize_terminal_text(reason)}")


def _format_interview_answer(response: dict[str, Any]) -> str:
    if response.get("skipped"):
        return "已跳过"
    answer = response.get("answer")
    if isinstance(answer, bool):
        return "是" if answer else "否"
    if isinstance(answer, list):
        return "、".join(str(value) for value in answer)
    return str(answer if answer is not None else "")


def _prompt_choice(label: str, values: set[str]) -> str:
    return click.prompt(label, type=click.Choice(sorted(values), case_sensitive=False)).lower()


def _prompt_required_text(label: str) -> str:
    return click.prompt(label, type=str).strip()


def _prompt_optional_text(label: str) -> str:
    return click.prompt(label, default="", show_default=False, type=str).strip()


def _configured_fast_model() -> tuple[str, str]:
    try:
        config = load_config()
    except (FileNotFoundError, OSError):
        config = {}
    llm_config = config.get("llm") if isinstance(config, dict) else None
    llm_config = llm_config if isinstance(llm_config, dict) else {}
    provider = str(llm_config.get("provider") or DEFAULT_LLM_CONFIG["provider"])
    return provider, get_model_for_task("fast", llm_config)


def _is_interactive_terminal() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _interview_now() -> datetime:
    return datetime.now()



@feedback_command.command("apply")
@click.option("--file", "file_path", type=click.Path(dir_okay=False), help="Read feedback update JSON from file")
@click.option("--dry-run", is_flag=True, help="Validate and preview without updating SQLite")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def apply_command(file_path: str | None, dry_run: bool, json_output: bool):
    """Apply multiple action status updates from JSON.

    Input format:
    {"updates": [{"id": "...", "status": "done", "note": "..."}]}
    """
    try:
        request = _read_request(file_path)
        updates = _normalize_request(request)
        previous = _validate_updates(updates)
    except ValueError as exc:
        _emit_error(str(exc), json_output=json_output, dry_run=dry_run)
        return

    results = []
    if not dry_run:
        for update in updates:
            feedback = _build_update_feedback(update)
            _apply_update(update, feedback)

    for update in updates:
        before = previous[update.action_id]
        after = get_action(update.action_id) if not dry_run else None
        results.append({
            "id": update.action_id,
            "summary": before.get("summary"),
            "type": before.get("type"),
            "scheduled_at": before.get("scheduled_at"),
            "previous_status": before.get("status"),
            "status": update.status,
            "updated_status": after.get("status") if after else None,
            "feedback": _build_update_feedback(update),
        })

    payload = versioned_payload({
        "ok": True,
        "dry_run": dry_run,
        "total": len(results),
        "succeeded": 0 if dry_run else len(results),
        "failed": 0,
        "updates": results,
        "errors": [],
    })
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    prefix = "DRY-RUN " if dry_run else ""
    click.echo(f"{prefix}feedback updates: {len(results)}")
    for result in results:
        click.echo(f"- {result['status']}: {result['summary']}")


def _feedback_item(action: dict) -> dict[str, Any]:
    action_id = str(action.get("id") or "")
    return {
        "id": action_id,
        "summary": action.get("summary"),
        "type": action.get("type"),
        "status": action.get("status"),
        "scheduled_at": action.get("scheduled_at"),
        "quick_commands": {
            "done": _quick_command(action_id, "done"),
            "partial": _quick_command(action_id, "partial"),
            "skipped": _quick_command(action_id, "skipped"),
            "deferred": _quick_command(action_id, "deferred"),
            "blocked": _quick_command(action_id, "blocked"),
        },
    }


def _quick_command(action_id: str, status: str) -> str:
    return (
        "nudge feedback apply --json <<'JSON'\n"
        + json.dumps({"updates": [{"id": action_id, "status": status}]}, ensure_ascii=False)
        + "\nJSON"
    )


def _read_request(file_path: str | None) -> object:
    if file_path:
        text = Path(file_path).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        raise ValueError("missing feedback JSON; pass --file or pipe stdin")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


def _normalize_request(request: object) -> list[_FeedbackUpdate]:
    if not isinstance(request, dict):
        raise ValueError("request must be a JSON object")
    raw_updates = request.get("updates")
    if not isinstance(raw_updates, list) or not raw_updates:
        raise ValueError("request.updates must be a non-empty list")
    if len(raw_updates) > 50:
        raise ValueError("request.updates must contain at most 50 items")
    updates = [_normalize_update(item, index) for index, item in enumerate(raw_updates, start=1)]
    ids = [update.action_id for update in updates]
    if len(ids) != len(set(ids)):
        raise ValueError("request.updates contains duplicate action ids")
    return updates


def _normalize_update(item: object, index: int) -> _FeedbackUpdate:
    if not isinstance(item, dict):
        raise ValueError(f"updates[{index}] must be an object")
    action_id = _string(item.get("id") or item.get("action_id"))
    if not action_id:
        raise ValueError(f"updates[{index}].id is required")
    status = _string(item.get("status")).lower()
    if status not in STATUS_ALLOWED:
        raise ValueError(f"updates[{index}].status unsupported: {status}")
    reason = _optional_choice(item.get("reason"), STATUS_REASONS, f"updates[{index}].reason")
    next_action = _optional_choice(item.get("next_action"), STATUS_NEXT_ACTIONS, f"updates[{index}].next_action")
    raw_feedback = item.get("feedback", {})
    if not isinstance(raw_feedback, dict):
        raise ValueError(f"updates[{index}].feedback must be an object if provided")
    return _FeedbackUpdate(
        action_id=action_id,
        status=status,
        note=_optional_string(item.get("note")),
        reason=reason,
        next_action=next_action,
        source=_optional_string(item.get("source")),
        feedback=raw_feedback,
    )


def _validate_updates(updates: list[_FeedbackUpdate]) -> dict[str, dict]:
    previous = {}
    for update in updates:
        action = get_action(update.action_id)
        if action is None:
            raise ValueError(f"FEEDBACK_ACTION_NOT_FOUND: {update.action_id}")
        previous[update.action_id] = action
    return previous


def _build_update_feedback(update: _FeedbackUpdate) -> dict[str, Any]:
    return build_feedback(
        source=update.source or "nudge feedback apply",
        channel="cli.feedback.apply",
        source_type="subjective",
        note=update.note,
        reason=update.reason,
        next_action=update.next_action,
        extra=update.feedback,
    )


def _apply_update(update: _FeedbackUpdate, feedback: dict[str, Any]) -> None:
    if update.status == "done":
        complete_action(update.action_id, feedback=feedback)
    elif update.status == "skipped":
        skip_action(update.action_id, feedback=feedback)
    elif update.status == "partial":
        partial_action(update.action_id, feedback=feedback)
    else:
        update_action_status(update.action_id, update.status, feedback=feedback)


def _emit_error(message: str, *, json_output: bool, dry_run: bool) -> None:
    code = "FEEDBACK_REQUEST_INVALID"
    detail = message
    if message.startswith("FEEDBACK_ACTION_NOT_FOUND:"):
        code = "FEEDBACK_ACTION_NOT_FOUND"
        detail = message.split(":", 1)[1].strip()
    payload = versioned_payload({
        "ok": False,
        "dry_run": dry_run,
        "errors": [{"code": code, "message": detail}],
    })
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        raise click.exceptions.Exit(1)
    raise click.ClickException(f"{code}: {detail}")


def _optional_choice(value: object, allowed: set[str], field_name: str) -> str | None:
    text = _optional_string(value)
    if not text:
        return None
    normalized = text.lower()
    if normalized not in allowed:
        raise ValueError(f"{field_name} unsupported: {normalized}")
    return normalized


def _optional_string(value: object) -> str | None:
    text = _string(value)
    return text or None


def _string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
