"""Dogfood weekly report aggregation and rendering."""
from datetime import date, datetime, timedelta
from pathlib import Path

from nudge.commands.doctor import FAIL, PASS, WARN, CheckResult
from nudge.feedback import feedback_source_summary, format_feedback_source_summary, normalize_feedback
from nudge.failures import build_failure_visibility_report
from nudge.sleep_reminders import SLEEP_AFTER_SKIP_STATUS, is_neutral_sleep_skip
from nudge.state import STATE_DIR


def build_weekly_dogfood_report(
    actions: list[dict],
    checks: list[CheckResult],
    today: date | None = None,
    note: str = "",
) -> dict:
    """Build a compact weekly dogfood report from local state and doctor checks."""
    today = today or date.today()
    week_start = today - timedelta(days=today.weekday())
    iso_year, iso_week, _ = today.isocalendar()

    sleep_after_skipped = sum(1 for action in actions if action.get("status") == SLEEP_AFTER_SKIP_STATUS)
    scored_actions = [action for action in actions if not is_neutral_sleep_skip(action)]
    total = len(scored_actions)
    done = sum(1 for action in scored_actions if action.get("status") == "done")
    partial = sum(1 for action in scored_actions if action.get("status") == "partial")
    skipped = sum(1 for action in scored_actions if action.get("status") == "skipped")
    deferred = sum(1 for action in scored_actions if action.get("status") == "deferred")
    blocked = sum(1 for action in scored_actions if action.get("status") == "blocked")
    pending = sum(1 for action in scored_actions if action.get("status") in ("created", "pending"))
    adapted = sum(1 for action in scored_actions if action.get("status") in ("adapted", "deleted"))
    completion_score = done + partial * 0.5
    completion_rate = round(completion_score / total * 100) if total else 0
    calendar_writes = sum(
        1
        for action in actions
        if action.get("type") == "calendar_event" and action.get("external_id")
    )
    adapt_accepts = adapted + sum(
        1
        for action in actions
        if "review weekly --adapt" in str(action.get("feedback") or "")
        and action.get("status") not in ("adapted", "deleted")
    )
    failure_visibility = build_failure_visibility_report(
        actions,
        now=datetime.combine(today, datetime.max.time()).replace(microsecond=0),
        overdue_hours=24,
    )

    return {
        "period": {
            "start": week_start.isoformat(),
            "end": today.isoformat(),
            "iso_week": f"{iso_year}-W{iso_week:02d}",
        },
        "actions": {
            "total": total,
            "done": done,
            "partial": partial,
            "skipped": skipped,
            "deferred": deferred,
            "blocked": blocked,
            "pending": pending,
            "adapted": adapted,
            "skipped_after_sleep": sleep_after_skipped,
            "completion_score": completion_score,
            "completion_rate": completion_rate,
            "calendar_writes": calendar_writes,
            "adapt_accepts": adapt_accepts,
        },
        "reasons": _extract_reasons(actions),
        "feedback_needed": _feedback_needed(actions),
        "feedback_sources": feedback_source_summary(actions),
        "failure_visibility": failure_visibility,
        "doctor": _summarize_checks(checks),
        "doctor_details": [
            {"status": check.status, "name": check.name, "message": check.message}
            for check in checks
        ],
        "note": note,
    }


def render_weekly_dogfood_report(report: dict) -> str:
    """Render a short Chinese Markdown dogfood report."""
    period = report["period"]
    actions = report["actions"]
    doctor = report["doctor"]
    score = _format_score(actions["completion_score"])
    lines = [
        f"# Nudge Dogfood 周报 · {period['iso_week']}",
        "",
        f"周期：{period['start']} ~ {period['end']}",
        "",
        "## 关键指标",
        "",
        f"- 使用次数：{actions['total']} 个 action",
        f"- 完成率：{actions['completion_rate']}% ({score}/{actions['total']})",
        f"- 完成 / 部分 / 跳过 / 延期 / 阻塞 / 待反馈：{actions['done']} / {actions['partial']} / {actions['skipped']} / {actions['deferred']} / {actions['blocked']} / {actions['pending']}",
        f"- 已睡后作废：{actions.get('skipped_after_sleep', 0)}",
        f"- 反馈来源：{format_feedback_source_summary(report.get('feedback_sources') or {})}",
        (
            "- 失败可解释："
            f"overdue={_failure_summary(report, 'pending_overdue')} / "
            f"blocked={_failure_summary(report, 'blocked_open')} / "
            f"missing_reason={_failure_summary(report, 'missing_reason')} / "
            f"missing_next_action={_failure_summary(report, 'missing_next_action')}"
        ),
        f"- 真实 Calendar 写入：{actions['calendar_writes']}",
        f"- Adapt 采纳：{actions['adapt_accepts']}",
        f"- Doctor：PASS {doctor[PASS]} / WARN {doctor[WARN]} / FAIL {doctor[FAIL]}",
        "",
        "## 未完成原因",
        "",
    ]
    reasons = report.get("reasons") or []
    if reasons:
        lines.extend(f"- {reason}" for reason in reasons)
    else:
        lines.append("- 暂无记录")

    feedback_needed = report.get("feedback_needed") or []
    if feedback_needed:
        lines.extend(["", "## 待反馈 action", ""])
        for action in feedback_needed:
            scheduled = f" · {action.get('scheduled_at')}" if action.get("scheduled_at") else ""
            lines.append(f"- {action.get('summary')}{scheduled}：`nudge log done --id {action.get('id')}`")

    details = [
        detail for detail in report.get("doctor_details", [])
        if detail["status"] in (WARN, FAIL)
    ]
    if details:
        lines.extend(["", "## 权限 / 错误问题", ""])
        lines.extend(f"- {detail['status']} {detail['name']}：{detail['message']}" for detail in details)

    if report.get("note"):
        lines.extend(["", "## 主观记录", "", report["note"]])

    return "\n".join(lines) + "\n"


def save_weekly_dogfood_report(report: dict, base_dir: Path | None = None) -> Path:
    """Save dogfood report under the Nudge state dogfood/YYYY-WW.md path."""
    root = base_dir or STATE_DIR
    path = root / "dogfood" / f"{report['period']['iso_week']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_weekly_dogfood_report(report))
    return path


def _summarize_checks(checks: list[CheckResult]) -> dict[str, int]:
    summary = {PASS: 0, WARN: 0, FAIL: 0}
    for check in checks:
        if check.status in summary:
            summary[check.status] += 1
    return summary


def _extract_reasons(actions: list[dict]) -> list[str]:
    reasons = []
    for action in actions:
        if action.get("status") not in ("skipped", "partial", "deferred", "blocked"):
            continue
        note = _feedback_note(action)
        if note:
            reasons.append(note)
    return reasons[:10]


def _feedback_needed(actions: list[dict]) -> list[dict]:
    needed = []
    for action in actions:
        if action.get("status") not in ("created", "pending"):
            continue
        needed.append({
            "id": action.get("id"),
            "summary": action.get("summary"),
            "scheduled_at": action.get("scheduled_at"),
        })
    return needed[:10]


def _feedback_note(action: dict) -> str:
    feedback = normalize_feedback(action.get("feedback"))
    if not feedback:
        return ""
    reason = str(feedback.get("reason") or "").strip()
    next_action = str(feedback.get("next_action") or "").strip()
    note = str(feedback.get("note") or "").strip()
    parts = [part for part in (reason, next_action) if part]
    if not parts:
        return note
    detail = " / ".join(parts)
    if note:
        detail = f"{detail} · {note}"
    summary = str(action.get("summary") or "").strip()
    return f"{summary}：{detail}" if summary else detail


def _failure_summary(report: dict, key: str) -> int:
    failure_visibility = report.get("failure_visibility") or {}
    summary = failure_visibility.get("summary") or {}
    return int(summary.get(key) or 0)


def _format_score(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.1f}"
