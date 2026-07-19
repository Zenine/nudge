"""Pure domain helpers for the interactive structured feedback interview."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable

from nudge.feedback import build_feedback
from nudge.sleep_reminders import later_sleep_reminders_after

FEEDBACK_INTERVIEW_PROTOCOL_VERSION = "nudge.feedback.interview.v1"
FEEDBACK_INTERVIEW_DEFAULT_SCOPE = "week-overdue"
FEEDBACK_INTERVIEW_DEFAULT_LIMIT = 20
FEEDBACK_INTERVIEW_MAX_LIMIT = 50
FEEDBACK_INTERVIEW_LLM_TIMEOUT_SECONDS = 10.0

_PENDING_STATUSES = {"created", "pending"}
_SCOPES = {"week-overdue", "today", "all-overdue"}
_QUESTION_TYPES = {"single_choice", "boolean", "multi_choice", "short_text", "long_text"}
_QUESTION_KEYS = {"id", "type", "prompt", "options", "required", "max_selections"}
_QUESTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1a\x1c-\x1f\x7f-\x9f]")

_HIGH_RISK_KEYWORDS = (
    "医疗",
    "医生",
    "复诊",
    "用药",
    "药物",
    "剂量",
    "注射",
    "家庭课程",
    "课前",
    "接送",
    "课程",
    "上课",
    "围棋",
    "绘画",
    "付款",
    "缴费",
    "交费",
    "账单",
    "物业费",
    "房租",
    "还款",
    "保险费",
    "转账",
    "证件",
    "护照",
    "签证",
    "出行",
    "航班",
    "高铁",
    "酒店",
    "机场",
    "机票",
    "车票",
    "行程",
    "出差",
    "旅行",
    "旅游",
    "medical",
    "doctor",
    "medication",
    "medicine",
    "dosage",
    "injection",
    "family course",
    "pickup",
    "payment",
    "pay bill",
    "transfer",
    "passport",
    "visa",
    "certificate",
    "flight",
    "train ticket",
    "hotel",
)

_HIGH_RISK_CONTEXT_FIELDS = ("reminder_list", "calendar", "calendar_name", "list_name")
_HIGH_RISK_CONTEXT_KEYWORDS = ("家庭", "family")


@dataclass(frozen=True)
class FeedbackCandidateBatch:
    """One bounded, stably ordered interview batch."""

    items: list[dict[str, Any]]
    total: int
    remaining: int
    scope: str
    limit: int


@dataclass(frozen=True)
class FeedbackQuestionBuildResult:
    """Validated GPT questions or a safe core-only degradation."""

    questions: list[dict[str, Any]]
    mode: str
    warning_code: str | None = None
    diagnostic: str | None = None


FEEDBACK_INTERVIEW_QUESTION_SYSTEM = """You generate optional follow-up questions for one task feedback interview.

The local application already decided the task status. You must not change it, infer completion,
request secrets, or propose database or Apple-app operations. Return exactly one JSON object with
a questions array containing at most 3 optional questions. Supported types are single_choice,
boolean, multi_choice, short_text, and long_text. Every question must set required to false.
Choice questions need 2 to 6 short unique options. Return JSON only."""


def select_feedback_candidates(
    actions: Iterable[dict[str, Any]],
    *,
    scope: str = FEEDBACK_INTERVIEW_DEFAULT_SCOPE,
    now: datetime | None = None,
    limit: int = FEEDBACK_INTERVIEW_DEFAULT_LIMIT,
) -> FeedbackCandidateBatch:
    """Select pending scheduled actions for one interview batch."""
    if scope not in _SCOPES:
        raise ValueError(f"unsupported feedback interview scope: {scope}")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= FEEDBACK_INTERVIEW_MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {FEEDBACK_INTERVIEW_MAX_LIMIT}")

    current = now or datetime.now()
    week_start = (current - timedelta(days=current.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    overdue_cutoff = current - timedelta(hours=24)

    selected: dict[str, dict[str, Any]] = {}
    for raw_action in actions:
        if not isinstance(raw_action, dict) or raw_action.get("status") not in _PENDING_STATUSES:
            continue
        action_id = str(raw_action.get("id") or "").strip()
        scheduled_at = _parse_scheduled_at(raw_action.get("scheduled_at"))
        if not action_id or scheduled_at is None:
            continue
        if scope == "week-overdue" and not (week_start <= scheduled_at < overdue_cutoff):
            continue
        if scope == "today" and not (today_start <= scheduled_at < tomorrow_start):
            continue
        if scope == "all-overdue" and not scheduled_at < overdue_cutoff:
            continue
        if action_id in selected:
            continue
        action = dict(raw_action)
        action["risk"] = classify_feedback_risk(action)
        selected[action_id] = action

    ordered = sorted(
        selected.values(),
        key=lambda action: (str(action.get("scheduled_at") or ""), str(action.get("id") or "")),
    )
    total = len(ordered)
    items = ordered[:limit]
    return FeedbackCandidateBatch(
        items=items,
        total=total,
        remaining=max(0, total - len(items)),
        scope=scope,
        limit=limit,
    )


def classify_feedback_risk(action: dict[str, Any]) -> str:
    """Classify one action using deterministic local-only rules."""
    if not isinstance(action, dict):
        return "high"
    summary = action.get("summary")
    action_type = action.get("type")
    if not isinstance(summary, str) or not summary.strip() or not isinstance(action_type, str) or not action_type.strip():
        return "high"

    explicit_values: list[str] = []
    for container in (action, action.get("metadata")):
        if not isinstance(container, dict):
            continue
        if "risk" in container:
            explicit_values.append(str(container.get("risk") or "").strip().lower())
        if container.get("high_risk") is True:
            explicit_values.append("high")
        elif container.get("high_risk") is False:
            explicit_values.append("normal")
    normalized_explicit = {value for value in explicit_values if value in {"high", "normal"}}
    invalid_explicit = any(value not in {"", "high", "normal"} for value in explicit_values)
    if invalid_explicit or len(normalized_explicit) > 1:
        return "high"
    if "high" in normalized_explicit:
        return "high"

    context_text = " ".join(
        str(action.get(field) or "").strip().casefold()
        for field in _HIGH_RISK_CONTEXT_FIELDS
    )
    if any(keyword.casefold() in context_text for keyword in _HIGH_RISK_CONTEXT_KEYWORDS):
        return "high"

    text = summary.casefold()
    if any(keyword.casefold() in text for keyword in _HIGH_RISK_KEYWORDS):
        return "high"
    return "normal"


def build_gpt_followup_questions(
    action: dict[str, Any],
    core_answers: dict[str, Any],
    *,
    llm_call=None,
) -> FeedbackQuestionBuildResult:
    """Request one bounded GPT follow-up set and degrade on any failure."""
    if llm_call is None:
        from nudge.brain import call_llm

        llm_call = call_llm
    payload = {
        "action": {
            "summary": str(action.get("summary") or ""),
            "type": str(action.get("type") or ""),
            "scheduled_at": action.get("scheduled_at"),
            "risk": action.get("risk") or classify_feedback_risk(action),
        },
        "core": {
            key: core_answers.get(key)
            for key in ("resolution", "reason", "next_action", "note")
            if core_answers.get(key) not in (None, "")
        },
    }
    try:
        raw = llm_call(
            FEEDBACK_INTERVIEW_QUESTION_SYSTEM,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            task="fast",
            timeout=FEEDBACK_INTERVIEW_LLM_TIMEOUT_SECONDS,
            retries=0,
        )
    except Exception as exc:
        return FeedbackQuestionBuildResult(
            questions=[],
            mode="core_only",
            warning_code="FEEDBACK_INTERVIEW_LLM_DEGRADED",
            diagnostic=exc.__class__.__name__,
        )
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return FeedbackQuestionBuildResult(
            questions=[],
            mode="core_only",
            warning_code="FEEDBACK_INTERVIEW_LLM_DEGRADED",
            diagnostic="invalid_json",
        )
    try:
        questions = validate_gpt_questions(parsed)
    except ValueError:
        return FeedbackQuestionBuildResult(
            questions=[],
            mode="core_only",
            warning_code="FEEDBACK_INTERVIEW_LLM_DEGRADED",
            diagnostic="invalid_schema",
        )
    return FeedbackQuestionBuildResult(questions=questions, mode="core_plus_gpt")


def plan_sleep_derived_effects(
    actions: Iterable[dict[str, Any]],
    interview_updates: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Plan existing sleep auto-skip semantics without writing state."""
    action_list = [dict(action) for action in actions if isinstance(action, dict)]
    action_by_id = {str(action.get("id") or ""): action for action in action_list}
    updates = [dict(update) for update in interview_updates if isinstance(update, dict)]
    explicit_ids = {str(update.get("id") or "") for update in updates}
    effects: dict[str, dict[str, Any]] = {}

    for update in updates:
        if update.get("resolution") != "done":
            continue
        action_id = str(update.get("id") or "")
        original = action_by_id.get(action_id)
        if original is None:
            continue
        completed = dict(original)
        completed["status"] = "done"
        completed["completed_at"] = (
            update.get("sleep_event_at")
            or update.get("completed_at")
            or datetime.now().strftime("%Y-%m-%d %H:%M")
        )
        for later in later_sleep_reminders_after(completed, action_list):
            later_id = str(later.get("id") or "")
            if not later_id or later_id in explicit_ids or later_id in effects:
                continue
            feedback = build_feedback(
                source="nudge sleep auto-skip",
                channel="sleep.auto_skip",
                source_type="system",
                note="已完成睡觉目标，后续睡眠提醒自动跳过，不计失败。",
                extra={
                    "completed_sleep_action_id": action_id,
                    "completed_sleep_action_summary": completed.get("summary"),
                },
            )
            effects[later_id] = {
                "id": later_id,
                "summary": later.get("summary"),
                "scheduled_at": later.get("scheduled_at"),
                "status": "skipped_after_sleep",
                "completed_at": later.get("completed_at"),
                "feedback": feedback,
            }
    return sorted(
        effects.values(),
        key=lambda effect: (str(effect.get("scheduled_at") or ""), str(effect.get("id") or "")),
    )


def validate_gpt_questions(payload: object) -> list[dict[str, Any]]:
    """Validate and normalize the bounded GPT follow-up question contract."""
    if not isinstance(payload, dict) or set(payload) != {"questions"}:
        raise ValueError("GPT question response must contain only questions")
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list) or len(raw_questions) > 3:
        raise ValueError("questions must be a list containing at most 3 items")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_question in enumerate(raw_questions, start=1):
        if not isinstance(raw_question, dict) or not set(raw_question).issubset(_QUESTION_KEYS):
            raise ValueError(f"questions[{index}] contains unsupported fields")
        question_id = raw_question.get("id")
        question_type = raw_question.get("type")
        prompt = raw_question.get("prompt")
        if not isinstance(question_id, str) or not _QUESTION_ID_RE.fullmatch(question_id):
            raise ValueError(f"questions[{index}].id is invalid")
        if question_id in seen_ids:
            raise ValueError(f"questions[{index}].id must be unique")
        seen_ids.add(question_id)
        if question_type not in _QUESTION_TYPES:
            raise ValueError(f"questions[{index}].type is unsupported")
        if not isinstance(prompt, str):
            raise ValueError(f"questions[{index}].prompt is required")
        safe_prompt = sanitize_terminal_text(prompt).strip()
        if not safe_prompt or len(safe_prompt) > 200:
            raise ValueError(f"questions[{index}].prompt is invalid")
        if raw_question.get("required") is not False:
            raise ValueError(f"questions[{index}].required must be false")

        question: dict[str, Any] = {
            "id": question_id,
            "type": question_type,
            "source": "gpt",
            "prompt": safe_prompt,
            "required": False,
        }
        raw_options = raw_question.get("options")
        if question_type in {"single_choice", "multi_choice"}:
            if not isinstance(raw_options, list) or not 2 <= len(raw_options) <= 6:
                raise ValueError(f"questions[{index}].options must contain 2 to 6 items")
            options = []
            for raw_option in raw_options:
                if not isinstance(raw_option, str):
                    raise ValueError(f"questions[{index}].options must be strings")
                option = sanitize_terminal_text(raw_option).strip()
                if not option or len(option) > 80:
                    raise ValueError(f"questions[{index}].options contains an invalid item")
                options.append(option)
            if len(options) != len(set(options)):
                raise ValueError(f"questions[{index}].options must be unique")
            question["options"] = options
            if question_type == "multi_choice":
                max_selections = raw_question.get("max_selections")
                if (
                    not isinstance(max_selections, int)
                    or isinstance(max_selections, bool)
                    or not 1 <= max_selections <= len(options)
                ):
                    raise ValueError(f"questions[{index}].max_selections is invalid")
                question["max_selections"] = max_selections
            elif "max_selections" in raw_question:
                raise ValueError(f"questions[{index}].max_selections is only valid for multi_choice")
        elif "options" in raw_question or "max_selections" in raw_question:
            raise ValueError(f"questions[{index}] options are not valid for {question_type}")
        normalized.append(question)
    return normalized


def normalize_interview_response(
    question: dict[str, Any],
    answer: object,
    *,
    skipped: bool = False,
    user_text: str | None = None,
) -> dict[str, Any]:
    """Normalize one optional GPT follow-up answer for feedback storage."""
    response = {
        "id": question["id"],
        "type": question["type"],
        "source": "gpt",
        "prompt": question["prompt"],
        "answer": None,
        "skipped": bool(skipped),
    }
    if skipped:
        if answer not in (None, "", []):
            raise ValueError("skipped response cannot include an answer")
    else:
        response["answer"] = _normalize_answer(question, answer)
    if user_text is not None:
        if not isinstance(user_text, str) or len(user_text) > 2000:
            raise ValueError("user_text must contain at most 2000 characters")
        if user_text:
            response["user_text"] = user_text
    return response


def sanitize_terminal_text(value: object) -> str:
    """Remove terminal escape sequences and unsafe control characters."""
    text = str(value if value is not None else "")
    text = _ANSI_ESCAPE_RE.sub("", text)
    return _CONTROL_RE.sub("", text)


def _normalize_answer(question: dict[str, Any], answer: object) -> object:
    question_type = question["type"]
    if question_type == "boolean":
        if not isinstance(answer, bool):
            raise ValueError("boolean answer must be true or false")
        return answer
    if question_type == "single_choice":
        if not isinstance(answer, str) or answer not in question["options"]:
            raise ValueError("single_choice answer must be one configured option")
        return answer
    if question_type == "multi_choice":
        if not isinstance(answer, list) or not answer:
            raise ValueError("multi_choice answer must be a non-empty list")
        if len(answer) != len(set(answer)):
            raise ValueError("multi_choice answer must not contain duplicates")
        if len(answer) > question["max_selections"]:
            raise ValueError("multi_choice answer exceeds max_selections")
        if any(not isinstance(value, str) or value not in question["options"] for value in answer):
            raise ValueError("multi_choice answer contains an unsupported option")
        return list(answer)
    if question_type in {"short_text", "long_text"}:
        limit = 500 if question_type == "short_text" else 4000
        if not isinstance(answer, str) or not answer.strip() or len(answer) > limit:
            raise ValueError(f"{question_type} answer must contain 1 to {limit} characters")
        return answer
    raise ValueError(f"unsupported question type: {question_type}")


def _parse_scheduled_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt, length in (
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%dT%H:%M", 16),
        ("%Y-%m-%d", 10),
    ):
        try:
            return datetime.strptime(text[:length], fmt)
        except ValueError:
            continue
    return None
