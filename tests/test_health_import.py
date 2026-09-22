"""Tests for Apple Health export import helpers."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile


def _write_health_export_zip(path: Path) -> Path:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData []>
<HealthData locale="zh_CN">
  <ExportDate value="2026-04-27 12:04:00 +0800"/>
  <Me HKCharacteristicTypeIdentifierDateOfBirth="1980-01-01"/>
  <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" creationDate="2026-04-27 09:00:00 +0800" startDate="2026-04-27 08:00:00 +0800" endDate="2026-04-27 08:10:00 +0800" value="1000"/>
  <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Apple Watch" unit="count" creationDate="2026-04-27 13:00:00 +0800" startDate="2026-04-27 12:00:00 +0800" endDate="2026-04-27 12:20:00 +0800" value="2000"/>
  <Record type="HKQuantityTypeIdentifierDistanceWalkingRunning" sourceName="Apple Watch" unit="km" startDate="2026-04-27 12:00:00 +0800" endDate="2026-04-27 12:20:00 +0800" value="1.2"/>
  <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" sourceName="Apple Watch" unit="kcal" startDate="2026-04-27 12:00:00 +0800" endDate="2026-04-27 12:20:00 +0800" value="120"/>
  <Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="Apple Watch" unit="min" startDate="2026-04-27 12:00:00 +0800" endDate="2026-04-27 12:20:00 +0800" value="20"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Apple Watch" unit="count/min" startDate="2026-04-27 10:00:00 +0800" endDate="2026-04-27 10:01:00 +0800" value="80"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Apple Watch" unit="count/min" startDate="2026-04-27 10:02:00 +0800" endDate="2026-04-27 10:03:00 +0800" value="100"/>
  <Record type="HKQuantityTypeIdentifierRestingHeartRate" sourceName="Apple Watch" unit="count/min" startDate="2026-04-27 08:00:00 +0800" endDate="2026-04-27 08:01:00 +0800" value="68"/>
  <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" sourceName="Apple Watch" unit="ms" startDate="2026-04-27 08:00:00 +0800" endDate="2026-04-27 08:01:00 +0800" value="35"/>
  <Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Scale" unit="kg" startDate="2026-04-27 07:00:00 +0800" endDate="2026-04-27 07:00:00 +0800" value="86.4"/>
  <Record type="HKQuantityTypeIdentifierBodyFatPercentage" sourceName="Scale" unit="%" startDate="2026-04-27 07:00:00 +0800" endDate="2026-04-27 07:00:00 +0800" value="0.268"/>
  <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Apple Watch" startDate="2026-04-26 23:00:00 +0800" endDate="2026-04-27 06:00:00 +0800" value="HKCategoryValueSleepAnalysisAsleepCore"/>
  <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Apple Watch" startDate="2026-04-26 22:45:00 +0800" endDate="2026-04-27 06:15:00 +0800" value="HKCategoryValueSleepAnalysisInBed"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeWalking" sourceName="Keep" duration="30" durationUnit="min" totalEnergyBurned="180" totalEnergyBurnedUnit="kcal" totalDistance="2.5" totalDistanceUnit="km" startDate="2026-04-27 18:30:00 +0800" endDate="2026-04-27 19:00:00 +0800"/>
</HealthData>
"""
    with ZipFile(path, "w") as zf:
        zf.writestr("apple_health_export/export.xml", xml)
        zf.writestr("apple_health_export/workout-routes/route.gpx", "<gpx/>")
    return path


def _write_health_export_json(path: Path) -> Path:
    payload = {
        "date_range": {
            "start": "2026-04-26",
            "end": "2026-04-28T00:00:00Z",
        },
        "metrics": {
            "steps": [{"date": "2026-04-27", "value": 12000}],
            "active_calories": [{"date": "2026-04-27", "value": 560}],
            "heart_rate": [{"date": "2026-04-27", "average_bpm": 84, "resting_bpm": 68}],
            "weight": [{"date": "2026-04-27", "source": "Scale", "value_kg": 79.1}],
            "sleep": [
                {
                    "date": "2026-04-27",
                    "stages": {
                        "awake_min": 20,
                        "core_min": 280,
                        "deep_min": 60,
                        "rem_min": 40,
                    },
                }
            ],
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
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_incremental_health_export_json(path: Path) -> Path:
    payload = {
        "date_range": {
            "start": "2026-04-27T12:00:00Z",
            "end": "2026-04-27T12:30:00Z",
        },
        "metrics": {
            "steps": [],
            "active_calories": [{"date": "2026-04-27", "source": "OtherExport", "value": 3}],
            "heart_rate": [{"date": "2026-04-27", "source": "OtherExport", "average_bpm": 68}],
            "weight": [],
            "workouts": [],
        },
        "sync_type": "incremental",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_parse_apple_health_export_zip_builds_daily_summary_without_routes(tmp_path):
    from nudge.health import parse_apple_health_export

    export_path = _write_health_export_zip(tmp_path / "health.zip")
    result = parse_apple_health_export(export_path)

    assert result.source_path == str(export_path)
    assert result.ignored_route_files == 1
    assert result.date_start == "2026-04-27"
    assert result.date_end == "2026-04-27"
    assert len(result.daily_summaries) == 1

    daily = result.daily_summaries[0]
    assert daily["date"] == "2026-04-27"
    assert daily["steps"] == 3000
    assert daily["distance_walking_running_m"] == 1200
    assert daily["active_energy_kcal"] == 120
    assert daily["exercise_minutes"] == 20
    assert daily["sleep_asleep_minutes"] == 420
    assert daily["sleep_in_bed_minutes"] == 450
    assert daily["avg_heart_rate"] == 90
    assert daily["resting_heart_rate"] == 68
    assert daily["hrv_sdnn_avg"] == 35
    assert daily["body_weight_kg"] == 86.4
    assert daily["body_fat_percent"] == 26.8
    assert daily["source_counts"]["Keep"] == 1

    assert len(result.workouts) == 1
    workout = result.workouts[0]
    assert workout["source_name"] == "Keep"
    assert workout["workout_type"] == "walking"
    assert workout["duration_minutes"] == 30
    assert workout["active_energy_kcal"] == 180
    assert workout["distance_m"] == 2500


def test_parse_apple_health_export_json_builds_daily_summary_and_workouts(tmp_path):
    from nudge.health import parse_apple_health_export

    export_path = _write_health_export_json(tmp_path / "health.json")
    result = parse_apple_health_export(export_path)

    assert result.source_path == str(export_path)
    assert result.ignored_route_files == 0
    assert result.date_start == "2026-04-27"
    assert result.date_end == "2026-04-27"
    assert len(result.daily_summaries) == 1

    daily = result.daily_summaries[0]
    assert daily["date"] == "2026-04-27"
    assert daily["steps"] == 12000
    assert daily["active_energy_kcal"] == 560
    assert daily["avg_heart_rate"] == 84
    assert daily["resting_heart_rate"] == 68
    assert daily["sleep_asleep_minutes"] == 380
    assert daily["sleep_in_bed_minutes"] == 400
    assert daily["body_weight_kg"] == 79.1

    workout = result.workouts[0]
    assert workout["source_name"] == "Keep"
    assert workout["workout_type"] == "walking"
    assert workout["duration_minutes"] == 30
    assert workout["active_energy_kcal"] == 220
    assert workout["distance_m"] == 2500


def test_apply_health_import_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.state.LEGACY_JSON", tmp_path / "state.json")

    from nudge.health import apply_health_import, parse_apple_health_export
    from nudge.state import get_health_daily_summaries, get_health_workouts

    result = parse_apple_health_export(_write_health_export_zip(tmp_path / "health.zip"))

    first = apply_health_import(result)
    second = apply_health_import(result)

    assert first == {"daily_upserted": 1, "workouts_upserted": 1}
    assert second == {"daily_upserted": 1, "workouts_upserted": 1}
    assert len(get_health_daily_summaries("2026-04-27", "2026-04-28")) == 1
    assert len(get_health_workouts("2026-04-27", "2026-04-28")) == 1


def test_apply_health_import_preserves_existing_daily_fields_from_other_sources(tmp_path, monkeypatch):
    monkeypatch.setattr("nudge.state.STATE_DIR", tmp_path)
    monkeypatch.setattr("nudge.state.DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr("nudge.state.LEGACY_JSON", tmp_path / "state.json")

    from nudge.health import apply_health_import, parse_apple_health_export
    from nudge.state import get_health_daily_summaries

    full_result = parse_apple_health_export(_write_health_export_json(tmp_path / "full.json"))
    incremental_result = parse_apple_health_export(_write_incremental_health_export_json(tmp_path / "incremental.json"))

    apply_health_import(full_result)
    apply_health_import(incremental_result)

    daily = get_health_daily_summaries("2026-04-27", "2026-04-28")[0]
    assert daily["body_weight_kg"] == 79.1
    assert daily["active_energy_kcal"] == 560
    assert daily["source_counts"]["Scale"] == 1
    assert daily["source_counts"]["OtherExport"] == 2
