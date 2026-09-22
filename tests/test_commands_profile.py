"""Tests for local profile memory command."""

import json
import os

from click.testing import CliRunner

from nudge.cli import cli
from nudge.feedback import build_feedback
from nudge.state import complete_action, get_latest_evaluation, log_action, update_action_status


def run_cli(args, home_dir):
    env = dict(os.environ)
    env["HOME"] = str(home_dir)
    return CliRunner().invoke(cli, args, prog_name="nudge", env=env)


def _setup_state(monkeypatch, tmp_path):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.state.LEGACY_JSON", tmp_path / "state.json")


def test_profile_build_derives_and_saves_memory(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    monkeypatch.setattr("nudge.commands.profile.date", _FixedDate)
    morning = log_action("calendar_event", "晨间跑步", scheduled_at="2026-07-01 07:30")
    evening = log_action("reminder", "晚间阅读 30 分钟", scheduled_at="2026-07-02 22:00")
    complete_action(morning, feedback=build_feedback(source="nudge log", source_type="subjective", note="早上状态好"))
    update_action_status(
        evening,
        "skipped",
        feedback=build_feedback(
            source="nudge log",
            source_type="subjective",
            reason="low_energy",
            next_action="reschedule",
            note="晚上太累",
        ),
    )

    result = run_cli(["profile", "build", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["profile"]["preferred_hours"]["07"] == 1
    assert payload["profile"]["avoid_hours"]["22"] == 1
    assert payload["profile"]["blocker_patterns"]["low_energy"] == 1
    assert any("优先安排在 07" in item for item in payload["profile"]["constraints"])

    saved = get_latest_evaluation(period="profile_memory")
    assert saved is not None
    assert saved["metrics"]["preferred_hours"]["07"] == 1


def test_profile_show_reads_latest_saved_profile(monkeypatch, tmp_path):
    _setup_state(monkeypatch, tmp_path)
    monkeypatch.setattr("nudge.commands.profile.date", _FixedDate)
    action_id = log_action("calendar_event", "晨间写作", scheduled_at="2026-07-01 08:00")
    complete_action(action_id)
    build = run_cli(["profile", "build", "--json"], tmp_path)
    assert build.exit_code == 0, build.output

    result = run_cli(["profile", "show", "--json"], tmp_path)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["profile"]["preferred_hours"]["08"] == 1


class _FixedDate:
    @classmethod
    def today(cls):
        from datetime import date

        return date(2026, 7, 5)
