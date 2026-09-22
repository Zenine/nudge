"""Tests for built-in Skill examples."""

import json
from pathlib import Path

from click.testing import CliRunner

from nudge.cli import cli
from nudge.skills.builtins import get_builtin_skill, list_builtin_skills
from nudge.skills.schema import validate_skill


ROOT = Path(__file__).resolve().parents[1]


def test_builtin_skills_include_three_real_examples():
    builtins = list_builtin_skills()

    assert [skill["id"] for skill in builtins] == [
        "strength-basics-12w",
        "deep-learning-sprint-4w",
        "deep-work-weekly-rhythm",
    ]
    assert {skill["category"] for skill in builtins} == {"fitness", "learning", "productivity"}

    for item in builtins:
        skill = get_builtin_skill(item["id"])
        validate_skill(skill)
        assert skill["metadata"]["id"] == item["id"]
        assert skill["plan_template"]["phases"][0]["sessions"]


def test_skills_list_command_outputs_builtin_ids():
    result = CliRunner().invoke(cli, ["skills", "list"], prog_name="nudge")

    assert result.exit_code == 0, result.output
    assert "strength-basics-12w" in result.output
    assert "deep-learning-sprint-4w" in result.output
    assert "deep-work-weekly-rhythm" in result.output


def test_skills_show_command_outputs_builtin_json():
    result = CliRunner().invoke(
        cli,
        ["skills", "show", "deep-learning-sprint-4w", "--json"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["skill"]["metadata"]["id"] == "deep-learning-sprint-4w"


def test_validate_apply_and_dry_run_accept_builtin_skill_ids(tmp_path):
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps({
        "assessment": {
            "current_frequency": "never",
            "preferred_session_length": 45,
        },
        "profile": {"start_date": "2026-04-27"},
    }))

    validate_result = CliRunner().invoke(
        cli,
        ["skills", "validate", "strength-basics-12w"],
        prog_name="nudge",
    )
    assert validate_result.exit_code == 0, validate_result.output
    assert "PASS" in validate_result.output

    apply_result = CliRunner().invoke(
        cli,
        ["skills", "apply", "strength-basics-12w", "--context", str(context_path), "--json"],
        prog_name="nudge",
    )
    assert apply_result.exit_code == 0, apply_result.output
    apply_payload = json.loads(apply_result.output)
    assert apply_payload["personalization_applied"]

    dry_run_result = CliRunner().invoke(
        cli,
        [
            "skills",
            "dry-run",
            "strength-basics-12w",
            "--context",
            str(context_path),
            "--json",
        ],
        prog_name="nudge",
    )
    assert dry_run_result.exit_code == 0, dry_run_result.output
    dry_run_payload = json.loads(dry_run_result.output)
    assert dry_run_payload["dry_run"] is True
    assert dry_run_payload["actions"][0]["source"] == "skill_dry_run"
    assert dry_run_payload["actions"][0]["skill_id"] == "strength-basics-12w"


def test_package_data_includes_builtin_skill_yamls():
    pyproject = (ROOT / "pyproject.toml").read_text()

    assert '"nudge.skills"' in pyproject
    assert '"builtins/*.yaml"' in pyproject
