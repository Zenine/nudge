"""Local long-term profile memory command."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta
from typing import Any

import click

from nudge.feedback import normalize_feedback
from nudge.json_contract import versioned_payload
from nudge.state import get_actions, get_latest_evaluation, save_evaluation

PROFILE_PERIOD = "profile_memory"


@click.group("profile")
def profile_command():
    """Build and inspect local execution profile memory."""


@profile_command.command("build")
@click.option("--days", type=int, default=90, show_default=True, help="Look back this many days")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def build_command(days: int, json_output: bool):
    """Derive and save a minimal profile from local execution feedback."""
    if days <= 0:
        _emit_error("days must be positive", json_output=json_output)
        return
    today = date.today()
    start = today - timedelta(days=days - 1)
    end = today + timedelta(days=1)
    actions = get_actions(since=start.isoformat(), until=end.isoformat())
    profile = build_profile_memory(actions, days=days)
    evaluation_id = save_evaluation(
        period=PROFILE_PERIOD,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        metrics=profile,
        insights="\n".join(profile.get("constraints") or []),
    )
    payload = versioned_payload({
        "ok": True,
        "id": evaluation_id,
        "period": {"type": PROFILE_PERIOD, "start": start.isoformat(), "end": end.isoformat()},
        "profile": profile,
        "errors": [],
    })
    _emit_profile(payload, json_output=json_output, empty_message="暂无可沉淀的 profile 信号。")


@profile_command.command("show")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def show_command(json_output: bool):
    """Show the latest saved local profile memory."""
    evaluation = get_latest_evaluation(period=PROFILE_PERIOD)
    if not evaluation:
        payload = versioned_payload({"ok": True, "profile": {}, "errors": []})
    else:
        payload = versioned_payload({
            "ok": True,
            "id": evaluation.get("id"),
            "period": {
                "type": PROFILE_PERIOD,
                "start": evaluation.get("period_start"),
                "end": evaluation.get("period_end"),
            },
            "profile": evaluation.get("metrics") or {},
            "errors": [],
        })
    _emit_profile(payload, json_output=json_output, empty_message="还没有保存的 profile；先运行 `nudge profile build`。")


def build_profile_memory(actions: list[dict], *, days: int) -> dict[str, Any]:
    """Derive deterministic profile memory from local action outcomes."""
    preferred_hours: Counter[str] = Counter()
    avoid_hours: Counter[str] = Counter()
    blocker_patterns: Counter[str] = Counter()
    action_type_counts: Counter[str] = Counter()
    disliked_items: list[str] = []

    for action in actions:
        status = str(action.get("status") or "")
        action_type = str(action.get("type") or "unknown")
        if action_type:
            action_type_counts[action_type] += 1
        hour = _scheduled_hour(action.get("scheduled_at"))
        if hour and status in {"done", "partial"}:
            preferred_hours[hour] += 1
        if hour and status in {"skipped", "deferred", "blocked"}:
            avoid_hours[hour] += 1

        feedback = normalize_feedback(action.get("feedback"))
        reason = str(feedback.get("reason") or "").strip()
        if reason:
            blocker_patterns[reason] += 1
        if reason in {"too_hard", "not_important"}:
            summary = str(action.get("summary") or "").strip()
            if summary and summary not in disliked_items:
                disliked_items.append(summary)

    profile = {
        "schema_version": "nudge.profile.v1",
        "source": "local_actions",
        "lookback_days": days,
        "action_count": len(actions),
        "preferred_hours": dict(sorted(preferred_hours.items())),
        "avoid_hours": dict(sorted(avoid_hours.items())),
        "blocker_patterns": dict(sorted(blocker_patterns.items())),
        "action_type_counts": dict(sorted(action_type_counts.items())),
        "disliked_items": disliked_items[:10],
    }
    profile["constraints"] = _constraints(profile)
    return profile


def latest_profile_context() -> str:
    """Return a compact prompt context for the latest profile memory."""
    evaluation = get_latest_evaluation(period=PROFILE_PERIOD)
    if not evaluation:
        return ""
    profile = evaluation.get("metrics") or {}
    constraints = profile.get("constraints") or []
    if not constraints:
        return ""
    lines = ["长期画像:"]
    lines.extend(f"- {item}" for item in constraints[:8])
    return "\n".join(lines)


def _constraints(profile: dict[str, Any]) -> list[str]:
    constraints: list[str] = []
    preferred = _top_keys(profile.get("preferred_hours") or {}, limit=3)
    avoid = _top_keys(profile.get("avoid_hours") or {}, limit=3)
    blockers = _top_keys(profile.get("blocker_patterns") or {}, limit=3)
    if preferred:
        constraints.append(f"优先安排在 {', '.join(preferred)} 点附近，历史完成/部分完成更多。")
    if avoid:
        constraints.append(f"谨慎安排在 {', '.join(avoid)} 点附近，历史跳过/延期/阻塞更多。")
    if blockers:
        constraints.append(f"常见阻塞原因：{', '.join(blockers)}。计划应预留降级或改期方案。")
    disliked = profile.get("disliked_items") or []
    if disliked:
        constraints.append(f"避免直接重复低价值/过难事项：{', '.join(disliked[:3])}。")
    if not constraints and profile.get("action_count"):
        constraints.append("历史样本不足以形成稳定偏好；保持小步试探，不激进加量。")
    return constraints


def _top_keys(counter: dict[str, int], *, limit: int) -> list[str]:
    return [key for key, _count in sorted(counter.items(), key=lambda item: (-int(item[1]), item[0]))[:limit]]


def _scheduled_hour(value: object) -> str | None:
    text = str(value or "")
    if len(text) >= 13 and text[10:13].strip().startswith(":") is False:
        hour = text[11:13]
        if hour.isdigit():
            return hour
    return None


def _emit_profile(payload: dict, *, json_output: bool, empty_message: str) -> None:
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    profile = payload.get("profile") or {}
    if not profile or not profile.get("constraints"):
        click.echo(empty_message)
        return
    click.echo("Profile memory:")
    for line in profile.get("constraints") or []:
        click.echo(f"- {line}")


def _emit_error(message: str, *, json_output: bool) -> None:
    payload = versioned_payload({
        "ok": False,
        "errors": [{"code": "PROFILE_REQUEST_INVALID", "message": message}],
    })
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        raise click.exceptions.Exit(1)
    raise click.ClickException(f"PROFILE_REQUEST_INVALID: {message}")
