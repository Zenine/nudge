"""Tests for the health import CLI."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from click.testing import CliRunner

from nudge.cli import cli


def _write_health_export_zip(path: Path) -> Path:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData []>
<HealthData locale="zh_CN">
  <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" startDate="2026-04-27 08:00:00 +0800" endDate="2026-04-27 08:10:00 +0800" value="3210"/>
  <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" sourceName="Apple Watch" unit="kcal" startDate="2026-04-27 12:00:00 +0800" endDate="2026-04-27 12:20:00 +0800" value="123"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeTraditionalStrengthTraining" sourceName="Keep" duration="35" durationUnit="min" totalEnergyBurned="210" totalEnergyBurnedUnit="kcal" startDate="2026-04-27 18:30:00 +0800" endDate="2026-04-27 19:05:00 +0800"/>
</HealthData>
"""
    with ZipFile(path, "w") as zf:
        zf.writestr("apple_health_export/export.xml", xml)
    return path


def _write_health_export_json(path: Path) -> Path:
    payload = {
        "metrics": {
            "steps": [{"date": "2026-04-27", "value": 12000, "source": "iPhone"}],
            "active_calories": [{"date": "2026-04-27", "value": 560, "source": "Keep"}],
            "sleep": [
                {
                    "date": "2026-04-27",
                    "source": "Apple Watch",
                    "stages": {"awake_min": 20, "core_min": 280, "deep_min": 60, "rem_min": 40},
                }
            ],
            "heart_rate": [{"date": "2026-04-27", "average_bpm": 84, "resting_bpm": 68}],
            "workouts": [
                {
                    "date": "2026-04-27",
                    "type": "walking",
                    "source": "Keep",
                    "duration_min": 30,
                    "distance_km": 2.5,
                    "calories": 220,
                }
            ],
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_health_export_empty_json(path: Path) -> Path:
    path.write_text(json.dumps({"metrics": {}}, ensure_ascii=False), encoding="utf-8")
    return path


def test_health_import_json_dry_run_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.state.LEGACY_JSON", tmp_path / "state.json")

    export_path = _write_health_export_zip(tmp_path / "health.zip")
    result = CliRunner().invoke(cli, ["health", "import", str(export_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["summary"]["daily"] == 1
    assert payload["summary"]["workouts"] == 1

    daily = CliRunner().invoke(cli, ["health", "daily", "--from", "2026-04-27", "--to", "2026-04-28", "--json"])
    assert daily.exit_code == 0
    assert json.loads(daily.output)["daily"] == []


def test_health_import_apply_then_daily_json(tmp_path, monkeypatch):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.state.LEGACY_JSON", tmp_path / "state.json")

    export_path = _write_health_export_zip(tmp_path / "health.zip")
    result = CliRunner().invoke(cli, ["health", "import", str(export_path), "--apply", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["dry_run"] is False
    assert payload["updated"] == {"daily_upserted": 1, "workouts_upserted": 1}

    daily = CliRunner().invoke(cli, ["health", "daily", "--from", "2026-04-27", "--to", "2026-04-28", "--json"])
    assert daily.exit_code == 0
    daily_payload = json.loads(daily.output)
    assert daily_payload["ok"] is True
    assert daily_payload["daily"][0]["date"] == "2026-04-27"
    assert daily_payload["daily"][0]["steps"] == 3210
    assert daily_payload["daily"][0]["active_energy_kcal"] == 123
    assert daily_payload["workouts"][0]["source_name"] == "Keep"
    assert daily_payload["workouts"][0]["workout_type"] == "traditional_strength_training"


def test_health_import_json_dry_run_supports_local_json_export(tmp_path, monkeypatch):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.state.LEGACY_JSON", tmp_path / "state.json")

    export_path = _write_health_export_json(tmp_path / "health.json")
    result = CliRunner().invoke(cli, ["health", "import", str(export_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["summary"]["daily"] == 1
    assert payload["summary"]["workouts"] == 1

    daily = CliRunner().invoke(cli, ["health", "daily", "--from", "2026-04-27", "--to", "2026-04-28", "--json"])
    assert daily.exit_code == 0
    assert json.loads(daily.output)["daily"] == []


def test_health_import_json_dry_run_shows_full_export_tip_when_sparse(tmp_path, monkeypatch):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.state.LEGACY_JSON", tmp_path / "state.json")

    export_path = _write_health_export_empty_json(tmp_path / "health.json")
    result = CliRunner().invoke(cli, ["health", "import", str(export_path)])

    assert result.exit_code == 0
    assert "提示：" in result.output
    assert "Apple Health 导出 ZIP" in result.output
