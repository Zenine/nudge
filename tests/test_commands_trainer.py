"""Tests for trainer command config/state and Apple backend wiring."""

import sqlite3
from dataclasses import dataclass

import pytest
from click.testing import CliRunner

import nudge.commands.trainer as trainer_module
import nudge.state as state_module
from nudge.apple.adapters import AppleBackends, WriteResult
from nudge.commands.trainer import trainer_command


@pytest.fixture(autouse=True)
def restore_state_globals():
    original_state_dir = state_module.STATE_DIR
    original_db_path = state_module.DB_PATH
    original_legacy_json = state_module.LEGACY_JSON
    yield
    state_module.STATE_DIR = original_state_dir
    state_module.DB_PATH = original_db_path
    state_module.LEGACY_JSON = original_legacy_json


@dataclass
class FakeCalendarBackend:
    calls: list[dict]

    def create_event(self, **kwargs):
        self.calls.append(kwargs)
        return WriteResult(ok=True, message="native ignored", external_id="backend-event-123")


class UnusedBackend:
    shortcut_name = "unused"


def _write_trainer_config(config_path, state_dir):
    config_path.write_text(
        "\n".join(
            [
                "[state]",
                f'dir = "{state_dir}"',
                "",
                "[calendars]",
                'workout = "Workout Calendar"',
                "",
                "[user.fitness]",
                'level = "beginner"',
                'goals = ["strength"]',
                'equipment = ["dumbbells"]',
            ]
        ),
        encoding="utf-8",
    )


def _count_rows(db_path, table):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_trainer_plan_config_writes_private_state_and_uses_calendar_backend(
    monkeypatch, tmp_path
):
    default_state = tmp_path / "default-state"
    private_state = tmp_path / "private-state"
    config_path = tmp_path / "config.toml"
    _write_trainer_config(config_path, private_state)
    state_module.configure_state({"state": {"dir": str(default_state)}})

    calendar = FakeCalendarBackend(calls=[])
    monkeypatch.setattr(trainer_module, "get_week_events", lambda calendar_names: [])
    monkeypatch.setattr(
        trainer_module,
        "generate_workout_plan",
        lambda profile, busy: [
            {
                "day": "2026-06-08",
                "time": "07:30",
                "summary": "Strength session",
                "type": "strength",
                "duration_minutes": 45,
                "exercises": [{"name": "Squat", "sets": 3, "reps": 8}],
            }
        ],
    )
    monkeypatch.setattr(
        trainer_module,
        "resolve_apple_backends",
        lambda config: AppleBackends(
            calendar=calendar,
            reminders=UnusedBackend(),
            notes=UnusedBackend(),
            clock=UnusedBackend(),
        ),
        raising=False,
    )
    monkeypatch.setattr(
        trainer_module,
        "create_calendar_event",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("direct calendar write used")),
        raising=False,
    )

    result = CliRunner().invoke(
        trainer_command,
        ["plan", "--config", str(config_path)],
        input="y\n",
        prog_name="nudge trainer",
    )

    assert result.exit_code == 0, result.output
    assert len(calendar.calls) == 1
    assert calendar.calls[0]["calendar_name"] == "Workout Calendar"
    private_db = private_state / "nudge.db"
    default_db = default_state / "nudge.db"
    assert _count_rows(private_db, "plans") == 1
    assert _count_rows(private_db, "actions") == 1
    with sqlite3.connect(private_db) as conn:
        external_id = conn.execute("SELECT external_id FROM actions").fetchone()[0]
    assert external_id == "backend-event-123"
    assert not default_db.exists()


def test_trainer_log_and_status_config_use_same_private_state(monkeypatch, tmp_path):
    default_state = tmp_path / "default-state"
    private_state = tmp_path / "private-state"
    config_path = tmp_path / "config.toml"
    _write_trainer_config(config_path, private_state)
    state_module.configure_state({"state": {"dir": str(default_state)}})
    config = trainer_module.load_config(config_path)
    state_module.configure_state(config)
    plan_id = state_module.create_plan(goal="weekly_workout", config={})
    state_module.log_action(
        action_type="workout",
        summary="Strength session",
        scheduled_at="2026-06-08 07:30",
        external_id="backend-event-123",
        plan_id=plan_id,
    )
    state_module.configure_state({"state": {"dir": str(default_state)}})
    monkeypatch.setattr(
        trainer_module,
        "parse_workout_log",
        lambda message, latest: {"completed": True, "effort": 7, "notes": "done"},
    )

    log_result = CliRunner().invoke(
        trainer_command,
        ["log", "--config", str(config_path), "finished it"],
        prog_name="nudge trainer",
    )
    status_result = CliRunner().invoke(
        trainer_command,
        ["status", "--config", str(config_path)],
        prog_name="nudge trainer",
    )

    assert log_result.exit_code == 0, log_result.output
    assert status_result.exit_code == 0, status_result.output
    assert "已完成" in log_result.output
    assert "完成: 1" in status_result.output
    assert "Strength session" in status_result.output
    assert not (default_state / "nudge.db").exists()
