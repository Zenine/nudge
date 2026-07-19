"""Public-safe behavior tests for structured feedback interview."""

import json
from datetime import datetime
from types import SimpleNamespace

from click.testing import CliRunner

from nudge.cli import cli
from nudge.feedback_interview import classify_feedback_risk, select_feedback_candidates
from nudge.state import get_action, log_action


def _setup_state(monkeypatch, tmp_path):
    import nudge.state as state

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "_schema_initialized_for", None, raising=False)


def test_feedback_interview_help_exposes_scope_and_limit():
    result = CliRunner().invoke(cli, ["feedback", "interview", "--help"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    assert "--scope" in result.output
    assert "--limit" in result.output


def test_feedback_candidate_selection_is_public_runtime_safe():
    batch = select_feedback_candidates(
        [{
            "id": "public-test",
            "type": "reminder",
            "summary": "整理书桌",
            "scheduled_at": "2026-07-13 08:00",
            "completed_at": None,
            "status": "created",
            "feedback": None,
        }],
        scope="week-overdue",
        now=datetime(2026, 7, 19, 12, 0),
    )

    assert [item["id"] for item in batch.items] == ["public-test"]


def test_feedback_risk_gate_uses_family_list_and_common_sensitive_tasks():
    assert classify_feedback_risk({
        "type": "reminder",
        "summary": "周六围棋课",
        "reminder_list": "家庭",
    }) == "high"
    assert classify_feedback_risk({"type": "reminder", "summary": "交物业费"}) == "high"
    assert classify_feedback_risk({"type": "reminder", "summary": "去机场"}) == "high"


def test_feedback_interview_public_runtime_writes_after_complete_confirmation(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    action_id = log_action("reminder", "整理书桌", "2026-07-13 08:00")
    monkeypatch.setattr("nudge.commands.feedback._is_interactive_terminal", lambda: True)
    monkeypatch.setattr(
        "nudge.commands.feedback._interview_now",
        lambda: datetime(2026, 7, 19, 12, 0),
    )
    monkeypatch.setattr(
        "nudge.commands.feedback.build_gpt_followup_questions",
        lambda *_args, **_kwargs: SimpleNamespace(
            questions=[],
            mode="core_only",
            warning_code=None,
            diagnostic=None,
        ),
    )

    result = CliRunner().invoke(
        cli,
        ["feedback", "interview"],
        prog_name="nudge",
        input="done\ny\n",
    )

    assert result.exit_code == 0, result.output
    assert "普通分组（确认）" in result.output
    assert "整理书桌 · 2026-07-13 08:00 -> done" in result.output
    assert result.output.index("Apple Reminder 如仍存在") < result.output.index("确认一次性写入")
    action = get_action(action_id)
    assert action["status"] == "done"
    assert json.loads(action["feedback"])["channel"] == "cli.feedback.interview"


def test_feedback_interview_public_runtime_disables_sdk_retries(monkeypatch):
    import nudge.brain as brain

    captured = {}

    class FakeProvider:
        def call(self, system, user_message, **kwargs):
            captured.update(kwargs)
            return "ok"

    monkeypatch.setattr(brain, "_get_provider", lambda: FakeProvider())
    monkeypatch.setattr(brain, "get_model_for_task", lambda task, config: "fast-model")

    assert brain.call_llm("system", "message", task="fast", timeout=10.0, retries=0) == "ok"
    assert captured == {"model": "fast-model", "timeout": 10.0, "max_retries": 0}
