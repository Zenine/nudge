"""Public-safe behavior tests for structured feedback interview."""

import json
import os
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from nudge.cli import cli
from nudge.feedback_interview import classify_feedback_risk, select_feedback_candidates
from nudge.state import get_action, log_action


def run_cli(args, home_dir, input_text=None):
    env = dict(os.environ)
    env["HOME"] = str(home_dir)
    return CliRunner().invoke(cli, args, prog_name="nudge", env=env, input=input_text)


def _setup_interview(monkeypatch):
    monkeypatch.setattr("nudge.commands.feedback._is_interactive_terminal", lambda: True)
    monkeypatch.setattr("nudge.commands.feedback._interview_now", lambda: datetime(2026, 7, 19, 12, 0))
    monkeypatch.setattr(
        "nudge.commands.feedback.build_gpt_followup_questions",
        lambda *_args, **_kwargs: SimpleNamespace(
            questions=[],
            mode="core_only",
            warning_code=None,
            diagnostic=None,
        ),
    )


class _FixedDate:
    @classmethod
    def today(cls):
        from datetime import date

        return date(2026, 7, 4)



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


def test_feedback_today_json_lists_pending_actions(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    monkeypatch.setattr("nudge.commands.feedback.date", _FixedDate)
    today_id = log_action(action_type="reminder", summary="20:00 营养闭环", scheduled_at="2026-07-04 20:00")
    log_action(action_type="reminder", summary="明天任务", scheduled_at="2026-07-05 20:00")

    result = run_cli(["feedback", "today", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["period"] == {"start": "2026-07-04", "end": "2026-07-05"}
    assert [item["id"] for item in payload["items"]] == [today_id]
    assert payload["items"][0]["summary"] == "20:00 营养闭环"
    assert payload["items"][0]["quick_commands"]["done"].startswith("nudge feedback apply")


def test_feedback_apply_json_updates_multiple_actions(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    a1 = log_action(action_type="reminder", summary="饮水闭环", scheduled_at="2026-07-04 20:00")
    a2 = log_action(action_type="calendar_event", summary="午间训练", scheduled_at="2026-07-04 12:30")
    request = {
        "updates": [
            {"id": a1, "status": "done", "note": "已完成"},
            {"id": a2, "status": "partial", "reason": "low_energy", "next_action": "keep", "note": "只做拉伸"},
        ]
    }

    result = run_cli(["feedback", "apply", "--json"], tmp_path, input_text=json.dumps(request, ensure_ascii=False))

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["total"] == 2
    assert payload["succeeded"] == 2
    assert payload["failed"] == 0
    assert get_action(a1)["status"] == "done"
    assert get_action(a2)["status"] == "partial"
    feedback = json.loads(get_action(a2)["feedback"])
    assert feedback["schema_version"] == "nudge.feedback.v1"
    assert feedback["channel"] == "cli.feedback.apply"
    assert feedback["source_type"] == "subjective"
    assert feedback["reason"] == "low_energy"
    assert feedback["next_action"] == "keep"


def test_feedback_apply_dry_run_does_not_update(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    action_id = log_action(action_type="reminder", summary="饮水闭环", scheduled_at="2026-07-04 20:00")
    request = {"updates": [{"id": action_id, "status": "done", "note": "已完成"}]}

    result = run_cli(["feedback", "apply", "--dry-run", "--json"], tmp_path, input_text=json.dumps(request, ensure_ascii=False))

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert get_action(action_id)["status"] == "created"


def test_feedback_apply_rejects_unknown_action_without_partial_writes(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    action_id = log_action(action_type="reminder", summary="饮水闭环", scheduled_at="2026-07-04 20:00")
    request = {
        "updates": [
            {"id": action_id, "status": "done"},
            {"id": "missing", "status": "done"},
        ]
    }

    result = run_cli(["feedback", "apply", "--json"], tmp_path, input_text=json.dumps(request, ensure_ascii=False))

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "FEEDBACK_ACTION_NOT_FOUND"
    assert get_action(action_id)["status"] == "created"


def test_feedback_weekly_score_json_writes_subjective_evaluation(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    monkeypatch.setattr("nudge.commands.feedback.date", _FixedDate)

    result = run_cli([
        "feedback",
        "weekly-score",
        "--difficulty", "6",
        "--recovery", "7",
        "--sleep", "5",
        "--mood", "8",
        "--note", "训练能完成，但晚上偏累",
        "--json",
    ], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["period"] == {
        "type": "weekly_subjective",
        "start": "2026-06-29",
        "end": "2026-07-06",
    }
    assert payload["metrics"] == {"difficulty": 6, "recovery": 7, "sleep": 5, "mood": 8}

    from nudge.state import get_latest_evaluation

    saved = get_latest_evaluation(period="weekly_subjective", period_start="2026-06-29", period_end="2026-07-06")
    assert saved is not None
    assert saved["metrics"] == payload["metrics"]
    assert saved["insights"] == "训练能完成，但晚上偏累"


def test_feedback_weekly_score_rejects_out_of_range(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    monkeypatch.setattr("nudge.commands.feedback.date", _FixedDate)

    result = run_cli([
        "feedback", "weekly-score",
        "--difficulty", "11",
        "--recovery", "7",
        "--sleep", "5",
        "--mood", "8",
        "--json",
    ], tmp_path)

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "SUBJECTIVE_SCORE_INVALID"


def test_feedback_interview_applies_batch_after_one_final_confirmation(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    _setup_interview(monkeypatch)
    done_id = log_action("reminder", "整理书桌", "2026-07-13 08:00")
    unconfirmed_id = log_action("reminder", "整理文件", "2026-07-13 09:00")

    result = run_cli(
        ["feedback", "interview"],
        tmp_path,
        input_text="done\nunconfirmed\n仍不确定\ny\n",
    )

    assert result.exit_code == 0, result.output
    assert "本批 2 / 总候选 2 / 剩余 0" in result.output
    assert get_action(done_id)["status"] == "done"
    assert get_action(unconfirmed_id)["status"] == "created"
    feedback = json.loads(get_action(unconfirmed_id)["feedback"])
    assert feedback["channel"] == "cli.feedback.interview"
    assert feedback["interview"]["resolution"] == "unconfirmed"
    assert feedback["interview"]["question_mode"] == "core_only"
    assert feedback["interview"]["responses"] == []


def test_feedback_interview_cancel_at_final_confirmation_writes_nothing(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    _setup_interview(monkeypatch)
    action_id = log_action("reminder", "整理书桌", "2026-07-13 08:00")

    result = run_cli(["feedback", "interview"], tmp_path, input_text="done\nn\n")

    assert result.exit_code == 130
    assert "FEEDBACK_INTERVIEW_CANCELLED" in result.output
    assert get_action(action_id)["status"] == "created"
    assert get_action(action_id)["feedback"] is None


def test_feedback_interview_high_risk_group_can_disable_gpt_without_default_selection(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    _setup_interview(monkeypatch)
    action_id = log_action("reminder", "复诊确认用药剂量", "2026-07-13 08:00")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("high-risk core_only group must not call GPT")

    monkeypatch.setattr("nudge.commands.feedback.build_gpt_followup_questions", fail_if_called)
    result = run_cli(
        ["feedback", "interview"],
        tmp_path,
        input_text="n\nunconfirmed\n\ny\n",
    )

    assert result.exit_code == 0, result.output
    assert "高风险分组" in result.output
    assert "provider=" in result.output
    assert "发送字段：summary, type, scheduled_at, risk, core" in result.output
    assert "高风险分组（确认）" in result.output
    assert "复诊确认用药剂量 · 2026-07-13 08:00 -> unconfirmed" in result.output
    assert "仍需人工确认" in result.output
    assert get_action(action_id)["status"] == "created"


def test_feedback_interview_shows_and_atomically_applies_sleep_derived_effect(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    _setup_interview(monkeypatch)
    bedtime_id = log_action("reminder", "关机睡觉", "2026-07-13 22:30")
    later_id = log_action("reminder", "不要熬夜", "2026-07-13 23:00")

    result = run_cli(
        ["feedback", "interview", "--limit", "1"],
        tmp_path,
        input_text="done\ny\n",
    )

    assert result.exit_code == 0, result.output
    assert "睡眠派生变更" in result.output
    assert "不要熬夜 -> skipped_after_sleep" in result.output
    assert "原因：已完成睡觉目标，后续睡眠提醒自动跳过，不计失败。" in result.output
    assert get_action(bedtime_id)["status"] == "done"
    assert get_action(later_id)["status"] == "skipped_after_sleep"


def test_feedback_interview_empty_scope_is_successful_info(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    _setup_interview(monkeypatch)

    result = run_cli(["feedback", "interview"], tmp_path)

    assert result.exit_code == 0
    assert "FEEDBACK_INTERVIEW_EMPTY" in result.output


def test_feedback_interview_persists_gpt_choice_and_user_text(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    _setup_interview(monkeypatch)
    action_id = log_action("reminder", "整理书桌", "2026-07-13 08:00")
    monkeypatch.setattr(
        "nudge.commands.feedback.build_gpt_followup_questions",
        lambda *_args, **_kwargs: SimpleNamespace(
            questions=[{
                "id": "main_blocker",
                "type": "single_choice",
                "source": "gpt",
                "prompt": "主要阻力是什么？",
                "required": False,
                "options": ["时间不足", "精力不足"],
            }],
            mode="core_plus_gpt",
            warning_code=None,
            diagnostic=None,
        ),
    )

    result = run_cli(
        ["feedback", "interview"],
        tmp_path,
        input_text="partial\n只做了一半\nsplit\n1\n下班太晚\ny\n",
    )

    assert result.exit_code == 0, result.output
    action = get_action(action_id)
    assert action["status"] == "partial"
    feedback = json.loads(action["feedback"])
    assert feedback["note"] == "只做了一半"
    assert feedback["next_action"] == "split"
    assert feedback["interview"]["question_mode"] == "core_plus_gpt"
    assert feedback["interview"]["responses"][0]["answer"] == "时间不足"
    assert feedback["interview"]["responses"][0]["user_text"] == "下班太晚"
    assert "普通分组（确认）" in result.output
    assert "整理书桌 · 2026-07-13 08:00 -> partial" in result.output
    assert "GPT：主要阻力是什么？ -> 时间不足" in result.output
    assert "补充文字：下班太晚" in result.output
    reminder_warning = "Apple Reminder 如仍存在，需要另行同步或人工处理"
    assert reminder_warning in result.output
    assert result.output.index(reminder_warning) < result.output.index("确认一次性写入以上全部反馈？")


def test_feedback_interview_rejects_zero_choice_index(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    _setup_interview(monkeypatch)
    action_id = log_action("reminder", "整理书桌", "2026-07-13 08:00")
    monkeypatch.setattr(
        "nudge.commands.feedback.build_gpt_followup_questions",
        lambda *_args, **_kwargs: SimpleNamespace(
            questions=[{
                "id": "main_blocker",
                "type": "single_choice",
                "source": "gpt",
                "prompt": "主要阻力是什么？",
                "required": False,
                "options": ["时间不足", "精力不足"],
            }],
            mode="core_plus_gpt",
            warning_code=None,
            diagnostic=None,
        ),
    )

    result = run_cli(
        ["feedback", "interview"],
        tmp_path,
        input_text="done\n0\n1\n\ny\n",
    )

    assert result.exit_code == 0, result.output
    assert "输入无效，请按题目要求重试" in result.output
    feedback = json.loads(get_action(action_id)["feedback"])
    assert feedback["interview"]["responses"][0]["answer"] == "时间不足"


def test_feedback_interview_maps_final_payload_value_error_to_schema_invalid(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    _setup_interview(monkeypatch)
    action_id = log_action("reminder", "整理书桌", "2026-07-13 08:00")

    def reject_payload(*_args, **_kwargs):
        raise ValueError("invalid final payload")

    monkeypatch.setattr("nudge.commands.feedback.apply_feedback_interview_batch", reject_payload)
    result = run_cli(["feedback", "interview"], tmp_path, input_text="done\ny\n")

    assert result.exit_code == 1
    assert "FEEDBACK_INTERVIEW_SCHEMA_INVALID" in result.output
    assert "invalid final payload" not in result.output
    assert get_action(action_id)["status"] == "created"


def test_feedback_interview_requires_tty(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    monkeypatch.setattr("nudge.commands.feedback._is_interactive_terminal", lambda: False)

    result = run_cli(["feedback", "interview"], tmp_path)

    assert result.exit_code == 1
    assert "FEEDBACK_INTERVIEW_TTY_REQUIRED" in result.output
