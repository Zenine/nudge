"""Tests for `nudge skills start` runtime materialization."""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from click.testing import CliRunner

import nudge.commands.skills as skills_cmd
import nudge.state as state
from nudge.skills.runtime import SKILL_INSTANCE_KIND
from nudge.apple.adapters import AppleBackends, WriteResult
from nudge.skills.runtime import get_skill_instance, list_skill_instances, record_materialized_week


@dataclass
class _FakeCalendar:
    created: list[dict] = field(default_factory=list)
    name: str = "fake"
    fail_on_call: int | str | None = None
    raise_on_call: int | str | None = None
    calls: int = 0

    def list_calendars(self):
        return True, ["Personal"]

    def create_event(self, **kwargs):
        self.calls += 1
        if self.raise_on_call == "all" or self.raise_on_call == self.calls:
            raise RuntimeError("boom")
        if self.fail_on_call == "all" or self.fail_on_call == self.calls:
            return WriteResult(ok=False, message="boom")
        self.created.append(kwargs)
        return WriteResult(ok=True, message="ok", external_id=f"cal-{len(self.created)}")


@dataclass
class _FakeReminders:
    created: list[dict] = field(default_factory=list)
    name: str = "fake"

    def list_lists(self):
        return True, ["Tasks"]

    def probe_read(self, list_name=None):
        return True, "ok"

    def create_reminder(self, **kwargs):
        self.created.append(kwargs)
        return WriteResult(ok=True, message="ok", external_id=f"rem-{len(self.created)}")


@dataclass
class _FakeClock:
    created: list[dict] = field(default_factory=list)
    name: str = "fake"
    shortcut_name: str = "fake shortcut"

    def check(self):
        return True, "ok"

    def create_alarm(self, **kwargs):
        self.created.append(kwargs)
        return WriteResult(ok=True, message="ok", external_id=f"clock-{len(self.created)}")


@dataclass
class _FakeNotes:
    created: list[dict] = field(default_factory=list)
    name: str = "fake"

    def list_folders(self):
        return True, ["Nudge"]

    def create_note(self, **kwargs):
        self.created.append(kwargs)
        return WriteResult(ok=True, message="ok", external_id=f"note-{len(self.created)}")


def _wire_command_env(monkeypatch, tmp_path, *, calendar_fail_on_call=None, calendar_raise_on_call=None):
    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")
    monkeypatch.setattr(skills_cmd, "load_config", lambda path=None: {})
    monkeypatch.setattr(skills_cmd, "configure_state", lambda config=None: tmp_path)
    calendar = _FakeCalendar(fail_on_call=calendar_fail_on_call, raise_on_call=calendar_raise_on_call)
    backends = AppleBackends(
        calendar=calendar,
        reminders=_FakeReminders(),
        clock=_FakeClock(),
        notes=_FakeNotes(),
    )
    monkeypatch.setattr(skills_cmd, "resolve_apple_backends", lambda config: backends)
    return backends


def _context_file(tmp_path, data):
    path = tmp_path / "context.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _start_instance(tmp_path):
    start_date = date.today() - timedelta(days=3)
    context = _context_file(tmp_path, {"profile": {"start_date": start_date.isoformat()}})

    result = CliRunner().invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--context", str(context), "--weeks", "1", "--json"],
    )

    assert result.exit_code == 0, result.output
    return json.loads(result.output)["plan_id"]


def test_skills_start_json_creates_instance_and_actions(monkeypatch, tmp_path):
    backends = _wire_command_env(monkeypatch, tmp_path)
    context = _context_file(
        tmp_path,
        {
            "assessment": {
                "current_frequency": "never",
                "preferred_session_length": 45,
            },
            "profile": {"start_date": "2026-07-06"},
        },
    )

    result = CliRunner().invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--context", str(context), "--weeks", "1", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert len(payload["created"]) == 3
    assert len(backends.calendar.created) == 3

    instances = list_skill_instances()
    assert len(instances) == 1
    instance = instances[0]
    assert instance["skill_id"] == "strength-basics-12w"
    assert instance["materialized_through_week"] == 1
    assert instance["weeks_total"] == 12

    actions = state.get_actions()
    assert len(actions) == 3
    assert all(action["external_id"] for action in actions)
    assert {action["status"] for action in actions} == {"created"}


def test_skills_start_dry_run_writes_nothing(monkeypatch, tmp_path):
    backends = _wire_command_env(monkeypatch, tmp_path)
    context = _context_file(tmp_path, {"profile": {"start_date": "2026-07-06"}})

    result = CliRunner().invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--context", str(context), "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert backends.calendar.created == []
    assert list_skill_instances() == []
    assert state.get_actions() == []


def test_skills_start_json_requires_context(monkeypatch, tmp_path):
    _wire_command_env(monkeypatch, tmp_path)

    result = CliRunner().invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--json"],
    )

    assert result.exit_code != 0
    assert "--context" in result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert "--context" in payload["error"]


def test_skills_start_json_partial_failure_keeps_json_clean_and_cursor_unmoved(monkeypatch, tmp_path):
    _wire_command_env(monkeypatch, tmp_path, calendar_fail_on_call=2)
    context = _context_file(
        tmp_path,
        {
            "assessment": {
                "current_frequency": "never",
                "preferred_session_length": 45,
            },
            "profile": {"start_date": "2026-07-06"},
        },
    )

    result = CliRunner().invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--context", str(context), "--weeks", "1", "--json"],
    )

    assert result.exit_code != 0
    assert result.output.strip().startswith("{")
    assert result.output.strip().endswith("}")
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["failed"]
    assert len(payload["created"]) >= 1
    assert all(action.get("_external_id") for action in payload["created"])
    assert all(action.get("action_id") for action in payload["created"])
    assert "retry_warning" in payload
    assert "不要整周重试" in payload["retry_warning"]

    actions = state.get_actions()
    assert len(actions) == len(payload["created"])
    assert all(action["external_id"] for action in actions)

    instances = list_skill_instances()
    assert len(instances) == 1
    assert instances[0]["materialized_through_week"] == 0


def test_skills_start_json_all_failures_do_not_leave_active_empty_instance(monkeypatch, tmp_path):
    _wire_command_env(monkeypatch, tmp_path, calendar_fail_on_call="all")
    context = _context_file(
        tmp_path,
        {
            "assessment": {
                "current_frequency": "never",
                "preferred_session_length": 45,
            },
            "profile": {"start_date": "2026-07-06"},
        },
    )

    result = CliRunner().invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--context", str(context), "--weeks", "1", "--json"],
    )

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["created"] == []
    assert payload["failed"]
    assert list_skill_instances() == []
    assert state.get_actions() == []


def test_skills_start_json_bad_context_outputs_versioned_payload(monkeypatch, tmp_path):
    _wire_command_env(monkeypatch, tmp_path)
    context = tmp_path / "bad-context.json"
    context.write_text("{bad json", encoding="utf-8")

    result = CliRunner().invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--json", "--context", str(context)],
    )

    assert result.exit_code == 1
    assert "Error:" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert "Cannot load context JSON" in payload["error"]


def test_skills_adapt_json_invalid_skill_reference_outputs_versioned_payload(monkeypatch, tmp_path):
    _wire_command_env(monkeypatch, tmp_path)
    plan_id = state.create_plan(
        "Skill: Missing",
        config={
            "kind": SKILL_INSTANCE_KIND,
            "skill_id": "missing-skill-id",
            "skill_version": "0.0.0",
            "context": {"profile": {"start_date": "2026-07-06"}},
            "start_date": "2026-07-06",
            "weeks_total": 1,
            "materialized_through_week": 0,
            "personalization_applied": [],
        },
    )

    result = CliRunner().invoke(skills_cmd.skills_command, ["adapt", plan_id, "--json"])

    assert result.exit_code == 1
    assert "Error:" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert "Skill" in payload["error"]
    assert "missing-skill-id" in payload["error"]


def test_skills_start_interactive_assessment(monkeypatch, tmp_path):
    backends = _wire_command_env(monkeypatch, tmp_path)

    result = CliRunner().invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--start-date", "2026-07-06"],
        input="1\n45\ny\n",
    )

    assert result.exit_code == 0, result.output
    assert len(backends.calendar.created) == 3
    instances = list_skill_instances()
    assert len(instances) == 1
    assert instances[0]["context"]["assessment"] == {
        "current_frequency": "never",
        "preferred_session_length": 45.0,
    }


def test_skills_status_lists_instances_with_progress(monkeypatch, tmp_path):
    _wire_command_env(monkeypatch, tmp_path)
    context = _context_file(tmp_path, {"profile": {"start_date": "2026-07-06"}})

    start_result = CliRunner().invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--context", str(context), "--json"],
    )

    assert start_result.exit_code == 0, start_result.output
    start_payload = json.loads(start_result.output)
    actions = state.get_actions(plan_id=start_payload["plan_id"])
    state.complete_action(actions[0]["id"], completed_at="2026-07-06 08:00")

    result = CliRunner().invoke(skills_cmd.skills_command, ["status", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    instance = payload["instances"][0]
    assert instance["plan_id"] == start_payload["plan_id"]
    assert instance["skill_id"] == "strength-basics-12w"
    assert instance["actions_total"] == 4
    assert instance["actions_done"] == 1
    assert instance["materialized_through_week"] == 1
    assert instance["weeks_total"] == 12


def test_skills_status_empty(monkeypatch, tmp_path):
    _wire_command_env(monkeypatch, tmp_path)

    result = CliRunner().invoke(skills_cmd.skills_command, ["status"])

    assert result.exit_code == 0, result.output
    assert "没有进行中的 Skill 实例" in result.output


def test_skills_adapt_preview_uses_history_and_does_not_write(monkeypatch, tmp_path):
    backends = _wire_command_env(monkeypatch, tmp_path)
    plan_id = _start_instance(tmp_path)
    writes_before = len(backends.calendar.created)

    for action in state.get_actions(plan_id=plan_id):
        state.complete_action(action["id"], feedback={"metrics": {"effort": 9}})

    result = CliRunner().invoke(skills_cmd.skills_command, ["adapt", plan_id, "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["applied"] is False
    assert "too_hard_deload" in payload["adaptation_applied"]
    assert payload["from_week"] == 2
    assert all(action["week"] == 2 for action in payload["actions"])
    assert all(action["duration_minutes"] <= 35 for action in payload["actions"])
    assert payload["history"]["effort_avg_7d"] == 9.0

    assert len(backends.calendar.created) == writes_before
    instance = get_skill_instance(plan_id)
    assert instance["materialized_through_week"] == 1
    assert "history" not in instance["context"]


def test_skills_adapt_apply_materializes_next_week(monkeypatch, tmp_path):
    backends = _wire_command_env(monkeypatch, tmp_path)
    plan_id = _start_instance(tmp_path)
    writes_before = len(backends.calendar.created)
    actions_before = len(state.get_actions(plan_id=plan_id))

    result = CliRunner().invoke(skills_cmd.skills_command, ["adapt", plan_id, "--apply", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["applied"] is True
    assert len(payload["created"]) == 4
    assert len(backends.calendar.created) == writes_before + 4
    assert len(state.get_actions(plan_id=plan_id)) == actions_before + 4
    assert get_skill_instance(plan_id)["materialized_through_week"] == 2


def test_skills_adapt_apply_json_partial_exception_keeps_created_and_cursor(monkeypatch, tmp_path):
    backends = _wire_command_env(monkeypatch, tmp_path, calendar_raise_on_call=5)
    plan_id = _start_instance(tmp_path)
    writes_before = len(backends.calendar.created)
    actions_before = len(state.get_actions(plan_id=plan_id))
    cursor_before = get_skill_instance(plan_id)["materialized_through_week"]

    result = CliRunner().invoke(skills_cmd.skills_command, ["adapt", plan_id, "--apply", "--json"])

    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["created"]
    assert payload["created"][0]["action_id"]
    assert payload["failed"]
    assert "boom" in payload["failed"][0]["error"]
    assert "retry_warning" in payload
    assert get_skill_instance(plan_id)["materialized_through_week"] == cursor_before
    assert len(backends.calendar.created) >= writes_before + 1
    assert len(state.get_actions(plan_id=plan_id)) == actions_before + len(payload["created"])


def test_skills_adapt_unknown_instance_fails(monkeypatch, tmp_path):
    _wire_command_env(monkeypatch, tmp_path)

    result = CliRunner().invoke(skills_cmd.skills_command, ["adapt", "missing", "--json"])

    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert "找不到 Skill 实例" in payload["error"]


def test_skills_adapt_apply_beyond_total_weeks_writes_nothing_and_keeps_cursor(monkeypatch, tmp_path):
    backends = _wire_command_env(monkeypatch, tmp_path)
    plan_id = _start_instance(tmp_path)
    record_materialized_week(plan_id, 12)
    writes_before = len(backends.calendar.created)
    actions_before = len(state.get_actions(plan_id=plan_id))

    result = CliRunner().invoke(skills_cmd.skills_command, ["adapt", plan_id, "--apply", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["applied"] is True
    assert payload["created"] == []
    assert payload["failed"] == []
    assert len(backends.calendar.created) == writes_before
    assert len(state.get_actions(plan_id=plan_id)) == actions_before
    assert get_skill_instance(plan_id)["materialized_through_week"] == 12
    assert "WARN" not in result.stdout
    assert "WARN requested week 13 exceeds Skill total weeks 12" in result.stderr
