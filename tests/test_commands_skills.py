import json
import textwrap
from pathlib import Path

from click.testing import CliRunner

from nudge.cli import cli


def _payload(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _custom_skill_yaml(skill_id: str = "custom-focus-rhythm") -> str:
    return textwrap.dedent(
        f"""
        schema_version: "0.1"
        kind: skill
        metadata:
          id: {skill_id}
          title: 自定义专注节奏
          version: 1.0.0
          creator: Test Suite
          category: productivity
        audience:
          goals:
            - 保护专注时间
          level: beginner
        assessment:
          - id: energy
            question: 你上午精力好吗？
            type: boolean
          - id: workload
            question: 本周负荷如何？
            type: single_choice
            options:
              - id: normal
                label: 正常
              - id: high
                label: 很高
        personalization:
          - id: morning_energy
            when:
              "==":
                - var: assessment.energy
                - true
            apply:
              - op: set
                path: plan_template.defaults.preferred_time
                value: "09:30"
        plan_template:
          defaults:
            sessions_per_week: 2
            session_minutes: 45
            preferred_days: [Monday, Wednesday]
            preferred_time: "14:00"
          phases:
            - id: week
              title: 每周执行
              weeks: 1
              sessions:
                - id: focus_1
                  title: 专注块 1
                  duration_minutes: 45
                - id: focus_2
                  title: 专注块 2
                  duration_minutes: 45
        tracking:
          metrics:
            - id: distraction_count
              type: number
        adaptation:
          - id: distraction_overload
            trigger:
              ">":
                - var: history.distraction_avg_7d
                - 5
            apply:
              - op: set
                path: plan_template.defaults.session_minutes
                value: 30
        """
    ).strip()


def test_skills_builtin_list_show_validate_apply_and_dry_run_use_json_contract(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    list_payload = _payload(
        CliRunner().invoke(cli, ["skills", "list", "--json"], prog_name="nudge")
    )
    builtin_ids = {skill["id"] for skill in list_payload["skills"] if skill["source"] == "builtin"}
    assert "deep-work-weekly-rhythm" in builtin_ids

    show_payload = _payload(
        CliRunner().invoke(
            cli,
            ["skills", "show", "deep-work-weekly-rhythm", "--json"],
            prog_name="nudge",
        )
    )
    assert show_payload["ok"] is True
    assert show_payload["skill"]["metadata"]["id"] == "deep-work-weekly-rhythm"

    validate_payload = _payload(
        CliRunner().invoke(
            cli,
            ["skills", "validate", "deep-work-weekly-rhythm", "--json"],
            prog_name="nudge",
        )
    )
    assert validate_payload["ok"] is True
    assert validate_payload["issues"] == []

    matching_context = _write_json(
        tmp_path / "matching-context.json",
        {
            "assessment": {"morning_energy": True, "meetings_load": "high"},
            "history": {"distraction_avg_7d": 6},
            "profile": {
                "preferred_days": ["Monday", "Wednesday", "Friday"],
                "preferred_time": "08:30",
                "start_date": "2026-06-01",
            },
        },
    )
    apply_payload = _payload(
        CliRunner().invoke(
            cli,
            [
                "skills",
                "apply",
                "deep-work-weekly-rhythm",
                "--context",
                str(matching_context),
                "--json",
            ],
            prog_name="nudge",
        )
    )
    assert apply_payload["personalization_applied"] == ["heavy_meeting_week", "morning_focus"]
    assert apply_payload["adaptation_applied"] == ["too_many_distractions"]
    assert apply_payload["skill"]["plan_template"]["defaults"]["sessions_per_week"] == 3
    assert apply_payload["skill"]["plan_template"]["defaults"]["session_minutes"] == 50
    assert apply_payload["skill"]["plan_template"]["defaults"]["preferred_time"] == "09:00"

    miss_context = _write_json(
        tmp_path / "miss-context.json",
        {
            "assessment": {"morning_energy": False, "meetings_load": "normal"},
            "history": {"distraction_avg_7d": 1},
            "profile": {"start_date": "2026-06-01"},
        },
    )
    miss_payload = _payload(
        CliRunner().invoke(
            cli,
            [
                "skills",
                "apply",
                "deep-work-weekly-rhythm",
                "--context",
                str(miss_context),
                "--json",
            ],
            prog_name="nudge",
        )
    )
    assert miss_payload["personalization_applied"] == []
    assert miss_payload["adaptation_applied"] == []
    assert miss_payload["skill"]["plan_template"]["defaults"]["sessions_per_week"] == 4
    assert miss_payload["skill"]["plan_template"]["defaults"]["session_minutes"] == 75

    dry_run_payload = _payload(
        CliRunner().invoke(
            cli,
            [
                "skills",
                "dry-run",
                "deep-work-weekly-rhythm",
                "--context",
                str(matching_context),
                "--weeks",
                "1",
                "--json",
            ],
            prog_name="nudge",
        )
    )
    assert dry_run_payload["dry_run"] is True
    assert dry_run_payload["personalization_applied"] == ["heavy_meeting_week", "morning_focus"]
    assert dry_run_payload["adaptation_applied"] == ["too_many_distractions"]
    assert len(dry_run_payload["actions"]) == 3
    assert {action["type"] for action in dry_run_payload["actions"]} == {"calendar_event"}
    assert dry_run_payload["actions"][0]["start"] == "2026-06-01 08:30"

    assert not (Path.home() / ".nudge" / "skills").exists()


def test_skills_import_and_delete_custom_skill_from_tmp_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    source = tmp_path / "custom-focus-rhythm.yaml"
    source.write_text(_custom_skill_yaml(), encoding="utf-8")
    custom_store = tmp_path / ".nudge" / "skills"

    import_payload = _payload(
        CliRunner().invoke(
            cli,
            ["skills", "import", str(source), "--json"],
            prog_name="nudge",
        )
    )

    assert import_payload["ok"] is True
    assert import_payload["action"] == "import"
    assert import_payload["skill"]["metadata"]["id"] == "custom-focus-rhythm"
    assert (custom_store / "custom-focus-rhythm.yaml").exists()

    list_payload = _payload(
        CliRunner().invoke(cli, ["skills", "list", "--json"], prog_name="nudge")
    )
    custom = [skill for skill in list_payload["skills"] if skill["source"] == "custom"]
    assert custom == [
        {
            "id": "custom-focus-rhythm",
            "title": "自定义专注节奏",
            "version": import_payload["skill"]["metadata"]["version"],
            "creator": "Test Suite",
            "category": "productivity",
            "source": "custom",
        }
    ]

    context = _write_json(
        tmp_path / "custom-context.json",
        {
            "assessment": {"energy": True, "workload": "normal"},
            "history": {"distraction_avg_7d": 2},
            "profile": {"start_date": "2026-06-01"},
        },
    )
    dry_run_payload = _payload(
        CliRunner().invoke(
            cli,
            [
                "skills",
                "dry-run",
                "custom-focus-rhythm",
                "--context",
                str(context),
                "--json",
            ],
            prog_name="nudge",
        )
    )
    assert dry_run_payload["personalization_applied"] == ["morning_energy"]
    assert dry_run_payload["adaptation_applied"] == []
    assert len(dry_run_payload["actions"]) == 2

    delete_payload = _payload(
        CliRunner().invoke(
            cli,
            ["skills", "delete", "custom-focus-rhythm", "--json"],
            prog_name="nudge",
        )
    )
    assert delete_payload == {
        "schema_version": "nudge.cli.v1",
        "ok": True,
        "action": "delete",
        "skill_id": "custom-focus-rhythm",
    }
    assert not (custom_store / "custom-focus-rhythm.yaml").exists()
    assert custom_store == tmp_path / ".nudge" / "skills"
