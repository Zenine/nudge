"""Tests for the `nudge skills` CLI."""

import json
import os
from pathlib import Path
from textwrap import dedent

from click.testing import CliRunner

from nudge.cli import cli


def write_skill(path: Path, *, skill_id: str = "strength-basics-12w") -> None:
    path.write_text(
        dedent(
            f"""
            schema_version: "0.1"
            kind: skill
            metadata:
              id: {skill_id}
              title: 12 周力量基础
              version: 1.0.0
              creator: 张教练
              category: fitness
            audience:
              goals: ["建立训练习惯"]
            assessment:
              - id: current_frequency
                question: 你目前每周训练几次？
                type: single_choice
                options:
                  - id: never
                    label: 从不
            personalization:
              - id: beginner_frequency
                when:
                  "==":
                    - var: assessment.current_frequency
                    - never
                apply:
                  - op: set
                    path: plan_template.defaults.sessions_per_week
                    value: 3
            plan_template:
              defaults:
                sessions_per_week: 4
                session_minutes: 45
                preferred_days: [Monday, Wednesday, Friday]
                preferred_time: "07:30"
              phases:
                - id: foundation
                  title: 基础期
                  weeks: 4
                  sessions:
                    - id: upper_a
                      title: 上肢 A
                      duration_minutes: 45
                    - id: lower_a
                      title: 下肢 A
                      duration_minutes: 45
            tracking:
              metrics:
                - id: session_completed
                  type: boolean
            """
        ).strip()
    )


def run_skills_command(args, home_dir: Path, **kwargs):
    env = dict(os.environ)
    env["HOME"] = str(home_dir)
    return CliRunner().invoke(cli, args, prog_name="nudge", env=env, **kwargs)


def test_skills_validate_command_accepts_valid_skill(tmp_path):
    skill_path = tmp_path / "skill.yaml"
    write_skill(skill_path)

    result = CliRunner().invoke(cli, ["skills", "validate", str(skill_path)], prog_name="nudge")

    assert result.exit_code == 0
    assert "PASS" in result.output
    assert "strength-basics-12w" in result.output


def test_skills_validate_command_outputs_json_errors(tmp_path):
    skill_path = tmp_path / "bad.yaml"
    skill_path.write_text("schema_version: '0.1'\nkind: skill\n")

    result = CliRunner().invoke(
        cli,
        ["skills", "validate", str(skill_path), "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert any(issue["path"] == "metadata" for issue in payload["issues"])


def test_skills_list_command_outputs_versioned_json():
    result = CliRunner().invoke(cli, ["skills", "list", "--json"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert any(skill["id"] == "strength-basics-12w" for skill in payload["skills"])


def test_skills_apply_command_personalizes_with_context_json(tmp_path):
    skill_path = tmp_path / "skill.yaml"
    context_path = tmp_path / "context.json"
    write_skill(skill_path)
    context_path.write_text(json.dumps({"assessment": {"current_frequency": "never"}}))

    result = CliRunner().invoke(
        cli,
        ["skills", "apply", str(skill_path), "--context", str(context_path), "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["personalization_applied"] == ["beginner_frequency"]
    assert payload["skill"]["plan_template"]["defaults"]["sessions_per_week"] == 3


def test_skills_dry_run_command_outputs_json_preview(tmp_path):
    skill_path = tmp_path / "skill.yaml"
    context_path = tmp_path / "context.json"
    write_skill(skill_path)
    context_path.write_text(json.dumps({
        "assessment": {"current_frequency": "never"},
        "profile": {"start_date": "2026-04-27"},
    }))

    result = CliRunner().invoke(
        cli,
        [
            "skills",
            "dry-run",
            str(skill_path),
            "--context",
            str(context_path),
            "--weeks",
            "1",
            "--json",
        ],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["dry_run"] is True
    assert payload["personalization_applied"] == ["beginner_frequency"]
    assert payload["adaptation_applied"] == []
    assert payload["actions"][0]["summary"] == "12 周力量基础：上肢 A"
    assert payload["actions"][0]["start"] == "2026-04-27 07:30"


def test_skills_dry_run_command_outputs_text_preview(tmp_path):
    skill_path = tmp_path / "skill.yaml"
    context_path = tmp_path / "context.json"
    write_skill(skill_path)
    context_path.write_text(json.dumps({
        "assessment": {"current_frequency": "never"},
        "profile": {"start_date": "2026-04-27"},
    }))

    result = CliRunner().invoke(
        cli,
        ["skills", "dry-run", str(skill_path), "--context", str(context_path)],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    assert "DRY-RUN Skill preview" in result.output
    assert "不会写入 Apple Calendar / Reminders" in result.output
    assert "12 周力量基础：上肢 A" in result.output


def test_skills_create_update_and_delete_custom_skill(tmp_path):
    create_source = tmp_path / "custom.yaml"
    write_skill(create_source, skill_id="custom-lifestyle-plan")

    create_result = run_skills_command(["skills", "create", str(create_source), "--json"], tmp_path)
    assert create_result.exit_code == 0, create_result.output
    created_payload = json.loads(create_result.output)
    assert created_payload["ok"] is True
    assert created_payload["action"] == "create"
    assert created_payload["skill"]["metadata"]["id"] == "custom-lifestyle-plan"

    list_result = run_skills_command(["skills", "list", "--json"], tmp_path)
    assert list_result.exit_code == 0, list_result.output
    listed = json.loads(list_result.output)
    assert any(
        skill["id"] == "custom-lifestyle-plan" and skill["source"] == "custom"
        for skill in listed["skills"]
    )

    show_result = run_skills_command(["skills", "show", "custom-lifestyle-plan", "--json"], tmp_path)
    assert show_result.exit_code == 0, show_result.output
    assert json.loads(show_result.output)["skill"]["metadata"]["id"] == "custom-lifestyle-plan"

    update_source = tmp_path / "update.yaml"
    write_skill(update_source, skill_id="custom-lifestyle-plan")
    update_result = run_skills_command(
        ["skills", "update", "custom-lifestyle-plan", str(update_source), "--bump-version", "--json"],
        tmp_path,
    )
    assert update_result.exit_code == 0, update_result.output
    updated = json.loads(update_result.output)
    assert updated["ok"] is True
    assert updated["action"] == "update"
    assert updated["skill"]["metadata"]["version"] == "1.0.1"

    history_dir = tmp_path / ".nudge" / "skills" / ".history" / "custom-lifestyle-plan"
    assert history_dir.exists()
    assert any(item.suffix == ".yaml" for item in history_dir.iterdir())

    delete_result = run_skills_command(["skills", "delete", "custom-lifestyle-plan", "--json"], tmp_path)
    assert delete_result.exit_code == 0, delete_result.output
    deleted_payload = json.loads(delete_result.output)
    assert deleted_payload["ok"] is True
    assert deleted_payload["action"] == "delete"
    assert deleted_payload["skill_id"] == "custom-lifestyle-plan"

    after_delete = run_skills_command(["skills", "list", "--json"], tmp_path)
    assert after_delete.exit_code == 0, after_delete.output
    after_payload = json.loads(after_delete.output)
    assert all(skill["id"] != "custom-lifestyle-plan" for skill in after_payload["skills"])


def test_skills_help_lists_builtins_validate_apply_and_dry_run():
    result = CliRunner().invoke(cli, ["skills", "--help"], prog_name="nudge")

    assert result.exit_code == 0
    assert "list" in result.output
    assert "show" in result.output
    assert "validate" in result.output
    assert "apply" in result.output
    assert "dry-run" in result.output
    assert "schedule" in result.output
    assert "create" in result.output
    assert "update" in result.output
    assert "delete" in result.output


def _fake_apply(calls):
    """Fake apply_agent_request capturing requests; dry-run mints a token."""

    def fake(*, request, config, dry_run_override=False):
        calls.append({"request": request, "dry_run_override": dry_run_override})
        n = len(request["actions"])
        if dry_run_override:
            return (
                {
                    "ok": True,
                    "dry_run": True,
                    "total": n,
                    "succeeded": 0,
                    "dry_run_token": "tok-" + request["request_id"],
                    "errors": [],
                },
                0,
            )
        assert request.get("dry_run_token"), "real write must carry a dry-run token"
        return ({"ok": True, "dry_run": False, "total": n, "succeeded": n, "errors": []}, 0)

    return fake


def _schedule_fixture(tmp_path):
    skill_path = tmp_path / "skill.yaml"
    context_path = tmp_path / "context.json"
    plan_path = tmp_path / "plan.md"
    write_skill(skill_path)
    context_path.write_text(json.dumps({
        "assessment": {"current_frequency": "never"},
        "profile": {"start_date": "2026-04-27"},
    }))
    plan_path.write_text("# 力量入门滚动计划\n本周写入 Calendar。\n")
    return skill_path, context_path, plan_path


def test_skills_schedule_dry_run_only_without_yes(tmp_path, monkeypatch):
    skill_path, context_path, plan_path = _schedule_fixture(tmp_path)
    calls = []
    monkeypatch.setattr("nudge.commands.skills.load_config", lambda path=None: {})
    monkeypatch.setattr("nudge.commands.skills.apply_agent_request", _fake_apply(calls))

    result = CliRunner().invoke(
        cli,
        ["skills", "schedule", str(skill_path), "--context", str(context_path),
         "--text-plan", str(plan_path), "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    # No --yes in --json mode => preview only, never a real write.
    assert all(call["dry_run_override"] for call in calls)
    req = calls[0]["request"]
    assert req["plan_driven"] is True
    assert req["text_plan_confirmed"] is True
    assert req["text_plan_ref"] == str(plan_path)
    assert req["require_confirmation"] is True
    assert req["actions"][0]["type"] == "calendar_event.create"


def test_skills_schedule_writes_with_yes_and_passes_token(tmp_path, monkeypatch):
    skill_path, context_path, plan_path = _schedule_fixture(tmp_path)
    calls = []
    monkeypatch.setattr("nudge.commands.skills.load_config", lambda path=None: {})
    monkeypatch.setattr("nudge.commands.skills.apply_agent_request", _fake_apply(calls))

    result = CliRunner().invoke(
        cli,
        ["skills", "schedule", str(skill_path), "--context", str(context_path),
         "--text-plan", str(plan_path), "--weeks", "1", "--yes", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is False
    assert payload["succeeded"] == payload["total"] > 0
    # One dry-run + one real write for a single batch, same request_id, token relayed.
    dry_calls = [c for c in calls if c["dry_run_override"]]
    write_calls = [c for c in calls if not c["dry_run_override"]]
    assert len(dry_calls) == 1 and len(write_calls) == 1
    assert write_calls[0]["request"]["request_id"] == dry_calls[0]["request"]["request_id"]
    assert write_calls[0]["request"]["dry_run_token"] == "tok-" + dry_calls[0]["request"]["request_id"]


def test_skills_schedule_batches_over_ten_actions(tmp_path, monkeypatch):
    skill_path, context_path, plan_path = _schedule_fixture(tmp_path)
    calls = []
    monkeypatch.setattr("nudge.commands.skills.load_config", lambda path=None: {})
    monkeypatch.setattr("nudge.commands.skills.apply_agent_request", _fake_apply(calls))

    # 3 sessions/week * 4 weeks = 12 actions -> 2 batches of <=10.
    result = CliRunner().invoke(
        cli,
        ["skills", "schedule", str(skill_path), "--context", str(context_path),
         "--text-plan", str(plan_path), "--weeks", "4", "--yes", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total"] == 12
    dry_calls = [c for c in calls if c["dry_run_override"]]
    write_calls = [c for c in calls if not c["dry_run_override"]]
    assert len(dry_calls) == 2 and len(write_calls) == 2
    assert [len(c["request"]["actions"]) for c in write_calls] == [10, 2]
    # Each batch's real write relays its own batch token, not another batch's.
    for dry, write in zip(dry_calls, write_calls):
        assert write["request"]["dry_run_token"] == "tok-" + dry["request"]["request_id"]
