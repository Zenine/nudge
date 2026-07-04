"""Public-safe tests for trainer compatibility over the Skills runtime."""

import json
from datetime import date

from click.testing import CliRunner

from nudge.apple.adapters import AppleBackends, WriteResult


def _isolate_state(monkeypatch, tmp_path):
    import nudge.state as state

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")
    return state


class _FakeCalendar:
    name = "fake"

    def __init__(self, *, fail_on_call=None):
        self.created = []
        self.fail_on_call = fail_on_call

    def list_calendars(self):
        return True, ["Personal"]

    def create_event(self, **kwargs):
        self.created.append(kwargs)
        if self.fail_on_call == "all" or self.fail_on_call == len(self.created):
            return WriteResult(ok=False, message="fake calendar failure", external_id=None)
        return WriteResult(ok=True, message="ok", external_id=f"cal-{len(self.created)}")


class _FakeReminders:
    name = "fake"

    def list_lists(self):
        return True, ["Reminders"]

    def probe_read(self, list_name=None):
        return True, "ok"

    def create_reminder(self, **kwargs):
        return WriteResult(ok=True, message="ok", external_id="rem-1")


class _FakeClock:
    name = "fake"
    shortcut_name = "Fake"

    def check(self):
        return True, "ok"

    def create_alarm(self, **kwargs):
        return WriteResult(ok=True, message="ok", external_id="alarm-1")


class _FakeNotes:
    name = "fake"

    def list_folders(self):
        return True, ["Nudge"]

    def create_note(self, **kwargs):
        return WriteResult(ok=True, message="ok", external_id=None)


def _wire_trainer_env(monkeypatch, tmp_path, config, *, calendar_fail_on_call=None):
    state = _isolate_state(monkeypatch, tmp_path)
    import nudge.commands.trainer as trainer_cmd
    import nudge.commands.skills as skills_cmd

    calendar = _FakeCalendar(fail_on_call=calendar_fail_on_call)
    backends = AppleBackends(
        calendar=calendar,
        reminders=_FakeReminders(),
        notes=_FakeNotes(),
        clock=_FakeClock(),
    )
    monkeypatch.setattr(trainer_cmd, "load_config", lambda path=None: config)
    monkeypatch.setattr(trainer_cmd, "configure_state", lambda cfg=None: tmp_path, raising=False)
    monkeypatch.setattr(trainer_cmd, "resolve_apple_backends", lambda cfg: backends, raising=False)
    monkeypatch.setattr(skills_cmd, "resolve_apple_backends", lambda cfg: backends)
    return state, trainer_cmd, calendar


def test_fitness_to_strength_context_maps_frequency_and_preferences():
    from nudge.commands.trainer import _fitness_to_strength_context

    context = _fitness_to_strength_context(
        {
            "fitness": {
                "strength_frequency": 0,
                "preferred_session_length": 35,
                "preferred_days": ["Tuesday", "Thursday"],
                "preferred_time": "18:30",
            }
        },
        start_date="2026-07-06",
    )

    assert context["assessment"] == {
        "current_frequency": "never",
        "preferred_session_length": 35.0,
    }
    assert context["profile"] == {
        "start_date": "2026-07-06",
        "preferred_days": ["Tuesday", "Thursday"],
        "preferred_time": "18:30",
    }


def test_fitness_to_strength_context_defaults_when_sparse():
    from nudge.commands.trainer import _fitness_to_strength_context

    context = _fitness_to_strength_context({"fitness": {}}, start_date="2026-07-06")

    assert context["assessment"]["current_frequency"] == "one_or_two"
    assert context["assessment"]["preferred_session_length"] == 45.0
    assert context["profile"]["start_date"] == "2026-07-06"


def test_fitness_to_strength_context_defaults_when_fitness_config_is_not_mapping():
    from nudge.commands.trainer import _fitness_to_strength_context

    context = _fitness_to_strength_context({"fitness": "bad"}, start_date="2026-07-06")

    assert context["assessment"] == {
        "current_frequency": "one_or_two",
        "preferred_session_length": 45.0,
    }
    assert context["profile"] == {"start_date": "2026-07-06"}


def test_fitness_to_strength_context_defaults_when_frequency_is_list_or_dict():
    from nudge.commands.trainer import _fitness_to_strength_context

    for raw_frequency in ([], {}):
        context = _fitness_to_strength_context(
            {"fitness": {"current_frequency": raw_frequency}},
            start_date="2026-07-06",
        )

        assert context["assessment"]["current_frequency"] == "one_or_two"


def test_fitness_to_strength_context_ignores_non_iterable_preferred_days():
    from nudge.commands.trainer import _fitness_to_strength_context

    context = _fitness_to_strength_context(
        {"fitness": {"preferred_days": 123}},
        start_date="2026-07-06",
    )

    assert context["profile"] == {"start_date": "2026-07-06"}


def test_fitness_to_strength_context_wraps_string_preferred_days():
    from nudge.commands.trainer import _fitness_to_strength_context

    context = _fitness_to_strength_context(
        {"fitness": {"preferred_days": "Tuesday"}},
        start_date="2026-07-06",
    )

    assert context["profile"] == {
        "start_date": "2026-07-06",
        "preferred_days": ["Tuesday"],
    }


def _fitness_config(*, start_date=None, preferred_days=None):
    fitness = {
        "strength_frequency": 0,
        "preferred_session_length": 35,
        "preferred_days": preferred_days or ["Monday", "Wednesday", "Friday"],
        "preferred_time": "07:00",
    }
    if start_date is not None:
        fitness["start_date"] = start_date
    return {
        "user": {
            "fitness": fitness,
        }
    }


def test_trainer_plan_dry_run_uses_strength_skill_without_writes(monkeypatch, tmp_path):
    state, trainer_cmd, calendar = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--dry-run", "--start-date", "2026-07-06", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["skill_id"] == "strength-basics-12w"
    assert len(payload["actions"]) == 3
    assert calendar.created == []
    assert state.get_actions() == []


def test_trainer_plan_creates_strength_skill_instance(monkeypatch, tmp_path):
    state, trainer_cmd, calendar = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--start-date", "2026-07-06", "--yes", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["skill_id"] == "strength-basics-12w"
    assert payload["legacy"] is False
    assert len(payload["created"]) == 3
    assert len(calendar.created) == 3

    from nudge.skills.runtime import list_skill_instances

    instance = list_skill_instances()[0]
    assert instance["skill_id"] == "strength-basics-12w"
    assert instance["materialized_through_week"] == 1
    assert instance["context"]["assessment"]["current_frequency"] == "never"

    actions = state.get_actions(plan_id=instance["plan_id"])
    assert len(actions) == 3
    assert all(a["external_id"] for a in actions)


def test_trainer_plan_uses_fitness_start_date_default_for_actions_and_context(monkeypatch, tmp_path):
    config = _fitness_config(start_date="2026-07-16", preferred_days=["Thursday"])
    state, trainer_cmd, calendar = _wire_trainer_env(monkeypatch, tmp_path, config)

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--yes", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["created"][0]["start"].startswith("2026-07-16 ")
    assert calendar.created[0]["start"].date().isoformat() == "2026-07-16"

    from nudge.skills.runtime import list_skill_instances

    instance = list_skill_instances()[0]
    assert instance["start_date"] == "2026-07-16"
    assert instance["context"]["profile"]["start_date"] == "2026-07-16"

    actions = state.get_actions(plan_id=instance["plan_id"])
    assert actions[0]["scheduled_at"].startswith("2026-07-16 ")


def test_trainer_plan_json_accepts_toml_date_start_date(monkeypatch, tmp_path):
    config = _fitness_config(start_date=date(2026, 7, 6))
    _state, trainer_cmd, calendar = _wire_trainer_env(monkeypatch, tmp_path, config)

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["actions"][0]["start"].startswith("2026-07-06")
    assert calendar.created == []


def test_trainer_plan_json_object_start_date_outputs_stable_json_error(monkeypatch, tmp_path):
    _state, trainer_cmd, _calendar = _wire_trainer_env(
        monkeypatch,
        tmp_path,
        _fitness_config(start_date=object()),
    )

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--dry-run", "--json"],
    )

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "Error:" not in result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert payload["error"] == "--start-date 必须是 YYYY-MM-DD 格式"


def test_trainer_plan_json_missing_fitness_outputs_json_error(monkeypatch, tmp_path):
    _state, trainer_cmd, _calendar = _wire_trainer_env(monkeypatch, tmp_path, {"user": {}})

    runner = CliRunner()
    result = runner.invoke(trainer_cmd.trainer_command, ["plan", "--json"])

    assert result.exit_code == 1
    assert "Error:" not in result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert "[user.fitness]" in payload["error"]


def test_trainer_plan_json_bad_start_date_outputs_json_error(monkeypatch, tmp_path):
    _state, trainer_cmd, _calendar = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--json", "--start-date", "bad"],
    )

    assert result.exit_code == 1
    assert "Error:" not in result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert "--start-date" in payload["error"]


def test_trainer_plan_json_bad_preferred_time_outputs_json_error(monkeypatch, tmp_path):
    config = _fitness_config()
    config["user"]["fitness"]["preferred_time"] = "bad-time"
    _state, trainer_cmd, _calendar = _wire_trainer_env(monkeypatch, tmp_path, config)

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--dry-run", "--json"],
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "Error:" not in result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert payload["error"]


def test_trainer_plan_json_bad_backend_outputs_json_error_without_creating_plan(monkeypatch, tmp_path):
    state, trainer_cmd, _calendar = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())

    def _raise_bad_backend(_config):
        raise RuntimeError("bad backend")

    monkeypatch.setattr(trainer_cmd, "resolve_apple_backends", _raise_bad_backend, raising=False)

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--start-date", "2026-07-06", "--yes", "--json"],
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert "bad backend" in payload["error"]

    from nudge.skills.runtime import list_skill_instances

    assert list_skill_instances() == []
    assert state.get_actions() == []


def test_trainer_plan_json_legacy_llm_outputs_json_error(monkeypatch, tmp_path):
    _state, trainer_cmd, _calendar = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--json", "--legacy-llm"],
    )

    assert result.exit_code == 1
    assert "Error:" not in result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert "--legacy-llm" in payload["error"]


def test_trainer_plan_partial_calendar_failure_returns_retry_warning_and_keeps_week_zero(
    monkeypatch,
    tmp_path,
):
    state, trainer_cmd, _calendar = _wire_trainer_env(
        monkeypatch,
        tmp_path,
        _fitness_config(),
        calendar_fail_on_call=2,
    )

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--start-date", "2026-07-06", "--yes", "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert "retry_warning" in payload
    assert len(payload["created"]) == 2
    assert len(payload["failed"]) == 1
    assert all(created["action_id"] for created in payload["created"])

    from nudge.skills.runtime import list_skill_instances

    instance = list_skill_instances()[0]
    assert instance["materialized_through_week"] == 0
    actions = state.get_actions(plan_id=instance["plan_id"])
    assert len(actions) == 2


def test_trainer_plan_all_calendar_failures_do_not_leave_active_empty_instance(
    monkeypatch,
    tmp_path,
):
    state, trainer_cmd, _calendar = _wire_trainer_env(
        monkeypatch,
        tmp_path,
        _fitness_config(),
        calendar_fail_on_call="all",
    )

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--start-date", "2026-07-06", "--yes", "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["created"] == []
    assert payload["failed"]

    from nudge.skills.runtime import list_skill_instances

    assert list_skill_instances() == []
    assert state.get_actions() == []




def _create_strength_instance(start_date="2026-07-06"):
    from nudge.skills.runtime import create_skill_instance

    return create_skill_instance(
        {
            "metadata": {
                "id": "strength-basics-12w",
                "version": "test",
                "title": "Strength Basics 12w",
            }
        },
        {"assessment": {}, "profile": {"start_date": start_date}},
        start_date=start_date,
        weeks_total=12,
        materialized_through_week=1,
        personalization_applied=[],
    )


def test_trainer_status_counts_partial_separately_from_pending(monkeypatch, tmp_path):
    state, trainer_cmd, _ = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())
    plan_id = _create_strength_instance()
    state.log_action("workout", "Done workout", plan_id=plan_id, status="done")
    state.log_action("workout", "Partial workout", plan_id=plan_id, status="partial")
    state.log_action("workout", "Pending workout", plan_id=plan_id)

    runner = CliRunner()
    result = runner.invoke(trainer_cmd.trainer_command, ["status"])

    assert result.exit_code == 0, result.output
    assert "◐ 部分完成: 1" in result.output
    assert "○ 待完成: 1" in result.output
    assert "○ 待完成: 2" not in result.output


def test_trainer_status_mentions_additional_active_strength_instances(monkeypatch, tmp_path):
    state, trainer_cmd, _ = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())
    first_plan_id = _create_strength_instance(start_date="2026-07-06")
    second_plan_id = _create_strength_instance(start_date="2026-07-13")
    state.log_action("workout", "First strength workout", plan_id=first_plan_id)
    state.log_action("workout", "Second strength workout", plan_id=second_plan_id)

    runner = CliRunner()
    result = runner.invoke(trainer_cmd.trainer_command, ["status"])

    assert result.exit_code == 0, result.output
    assert "另有 1 个" in result.output
    assert "进行中的 strength Skill 实例" in result.output


def test_trainer_status_empty_strength_actions_warns_and_falls_back_to_legacy(monkeypatch, tmp_path):
    state, trainer_cmd, _ = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())
    _create_strength_instance()
    legacy_plan_id = state.create_plan(goal="weekly_workout", config={"source": "legacy-test"})
    state.log_action(
        "workout",
        "Legacy weekly workout",
        scheduled_at="2026-07-06 07:00",
        plan_id=legacy_plan_id,
    )

    runner = CliRunner()
    result = runner.invoke(trainer_cmd.trainer_command, ["status"])

    assert result.exit_code == 0, result.output
    assert "WARN strength Skill 实例没有已登记动作，继续检查旧版训练计划。" in result.output
    assert "训练计划" in result.output
    assert "Legacy weekly workout" in result.output


def test_trainer_status_skips_empty_strength_instance_and_shows_later_valid_instance(
    monkeypatch,
    tmp_path,
):
    state, trainer_cmd, _ = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())
    valid_plan_id = _create_strength_instance(start_date="2026-07-06")
    state.log_action("workout", "Effective strength workout", plan_id=valid_plan_id)
    empty_plan_id = _create_strength_instance(start_date="2026-07-13")
    with state._db() as conn:
        conn.execute("UPDATE plans SET created_at = ? WHERE id = ?", ("2026-07-05 00:00:00", valid_plan_id))
        conn.execute("UPDATE plans SET created_at = ? WHERE id = ?", ("2026-07-06 00:00:00", empty_plan_id))

    runner = CliRunner()
    result = runner.invoke(trainer_cmd.trainer_command, ["status"])

    assert result.exit_code == 0, result.output
    assert "WARN strength Skill 实例没有已登记动作" in result.output
    assert "Skill 训练计划" in result.output
    assert valid_plan_id in result.output
    assert empty_plan_id not in result.output


def test_trainer_status_prefers_strength_skill_instance(monkeypatch, tmp_path):
    state, trainer_cmd, _ = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())
    runner = CliRunner()
    plan = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--start-date", "2026-07-06", "--yes", "--json"],
    )
    assert plan.exit_code == 0, plan.output

    result = runner.invoke(trainer_cmd.trainer_command, ["status"])

    assert result.exit_code == 0, result.output
    assert "Skill 训练计划" in result.output
    assert "strength-basics-12w" in result.output
    assert "W1/12" in result.output


def test_trainer_log_guides_for_skill_backed_actions(monkeypatch, tmp_path):
    _state, trainer_cmd, _ = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())
    runner = CliRunner()
    plan = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--start-date", "2026-07-06", "--yes", "--json"],
    )
    assert plan.exit_code == 0, plan.output

    result = runner.invoke(trainer_cmd.trainer_command, ["log", "完成了，强度8"])

    assert result.exit_code == 0, result.output
    assert "nudge log done --metric effort=8" in result.output
    assert "nudge skills adapt" in result.output
