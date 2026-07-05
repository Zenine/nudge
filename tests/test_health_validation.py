from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import nudge.health as health


def _write_health_zip(path: Path, records: list[str]) -> Path:
    xml = "<HealthData>" + "".join(records) + "</HealthData>"
    with ZipFile(path, "w") as zf:
        zf.writestr("apple_health_export/export.xml", xml)
    return path


def _record(record_type: str, value: str, unit: str, **attrs: str) -> str:
    merged = {
        "type": record_type,
        "startDate": "2026-07-01 08:00:00 +0000",
        "endDate": "2026-07-01 08:01:00 +0000",
        "sourceName": "synthetic-app",
        "sourceVersion": "1.0",
        "device": "synthetic-device",
        "creationDate": "2026-07-01 08:02:00 +0000",
        "value": value,
        "unit": unit,
    }
    merged.update(attrs)
    attributes = " ".join(f'{key}="{val}"' for key, val in merged.items())
    return f"<Record {attributes}/>"


def test_parse_health_xml_deduplicates_identical_records(tmp_path: Path) -> None:
    duplicate_step = _record("HKQuantityTypeIdentifierStepCount", "500", "count")
    export_zip = _write_health_zip(
        tmp_path / "duplicate.zip",
        [
            duplicate_step,
            duplicate_step,
            _record(
                "HKQuantityTypeIdentifierStepCount",
                "300",
                "count",
                startDate="2026-07-01 09:00:00 +0000",
                endDate="2026-07-01 09:01:00 +0000",
                creationDate="2026-07-01 09:02:00 +0000",
            ),
        ],
    )

    result = health.parse_apple_health_export(export_zip)

    assert result.daily_summaries[0]["steps"] == 800
    assert result.daily_summaries[0]["source_counts"] == {"synthetic-app": 2}


def test_parse_health_xml_skips_invalid_units_and_outlier_values(tmp_path: Path) -> None:
    export_zip = _write_health_zip(
        tmp_path / "invalid.zip",
        [
            _record("HKQuantityTypeIdentifierStepCount", "1000", "count"),
            _record("HKQuantityTypeIdentifierStepCount", "-50", "count", startDate="2026-07-01 09:00:00 +0000"),
            _record("HKQuantityTypeIdentifierStepCount", "1000000", "count", startDate="2026-07-01 10:00:00 +0000"),
            _record("HKQuantityTypeIdentifierDistanceWalkingRunning", "1", "km"),
            _record("HKQuantityTypeIdentifierDistanceWalkingRunning", "2", "furlong", startDate="2026-07-01 09:00:00 +0000"),
            _record("HKQuantityTypeIdentifierActiveEnergyBurned", "500", "kcal"),
            _record("HKQuantityTypeIdentifierActiveEnergyBurned", "100", "parsec", startDate="2026-07-01 09:00:00 +0000"),
            _record("HKQuantityTypeIdentifierAppleExerciseTime", "30", "min"),
            _record("HKQuantityTypeIdentifierAppleExerciseTime", "1", "fortnight", startDate="2026-07-01 09:00:00 +0000"),
        ],
    )

    result = health.parse_apple_health_export(export_zip)
    summary = result.daily_summaries[0]

    assert summary["steps"] == 1000
    assert summary["distance_walking_running_m"] == 1000
    assert summary["active_energy_kcal"] == 500
    assert summary["exercise_minutes"] == 30
    assert summary["source_counts"] == {"synthetic-app": 4}


def test_parse_health_json_skips_negative_and_outlier_accumulators(tmp_path: Path) -> None:
    export_json = tmp_path / "health.json"
    export_json.write_text(
        json.dumps(
            {
                "metrics": {
                    "steps": [
                        {"date": "2026-07-01", "source": "synthetic-json", "value": 1200},
                        {"date": "2026-07-01", "source": "synthetic-json", "value": -1},
                        {"date": "2026-07-01", "source": "synthetic-json", "value": 1000000},
                    ],
                    "active_calories": [
                        {"date": "2026-07-01", "source": "synthetic-json", "value": 300},
                        {"date": "2026-07-01", "source": "synthetic-json", "value": -20},
                        {"date": "2026-07-01", "source": "synthetic-json", "value": 50000},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = health.parse_apple_health_export(export_json)
    summary = result.daily_summaries[0]

    assert summary["steps"] == 1200
    assert summary["active_energy_kcal"] == 300
    assert summary["source_counts"] == {"synthetic-json": 2}


def test_parse_health_json_skips_out_of_range_weight_and_body_fat(tmp_path: Path) -> None:
    # JSON import must apply the same range guards as the XML path
    # (weight 1..500 kg, body fat 0..100 %) so bad values are dropped, not stored.
    export_json = tmp_path / "health.json"
    export_json.write_text(
        json.dumps(
            {
                "metrics": {
                    "steps": [
                        {"date": "2026-07-01", "source": "synthetic-json", "value": 1200},
                    ],
                    "weight": [
                        {"date": "2026-07-01", "source": "synthetic-json", "value_kg": 600},
                        {"date": "2026-07-01", "source": "synthetic-json", "value_kg": 0.2},
                    ],
                    "body_fat": [
                        {"date": "2026-07-01", "source": "synthetic-json", "value": 150},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = health.parse_apple_health_export(export_json)
    summary = result.daily_summaries[0]

    assert summary["steps"] == 1200
    assert summary["body_weight_kg"] is None
    assert summary["body_fat_percent"] is None


def test_parse_health_xml_omits_day_when_all_records_are_invalid(tmp_path: Path) -> None:
    export_zip = _write_health_zip(
        tmp_path / "all-invalid.zip",
        [
            _record("HKQuantityTypeIdentifierStepCount", "-50", "count"),
            _record("HKQuantityTypeIdentifierDistanceWalkingRunning", "2", "furlong"),
        ],
    )

    result = health.parse_apple_health_export(export_zip)

    assert result.daily_summaries == []


def test_parse_health_xml_converts_body_mass_pounds_to_kg(tmp_path: Path) -> None:
    export_zip = _write_health_zip(
        tmp_path / "body-mass.zip",
        [_record("HKQuantityTypeIdentifierBodyMass", "180", "lb")],
    )

    result = health.parse_apple_health_export(export_zip)

    assert result.daily_summaries[0]["body_weight_kg"] == 81.6466
