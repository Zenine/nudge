import json
import zipfile

from click.testing import CliRunner

from nudge.cli import cli
from nudge.health import parse_apple_health_export


def test_health_import_json_uses_inclusive_from_and_exclusive_to(tmp_path):
    export = tmp_path / "health-export.json"
    export.write_text(
        json.dumps(
            {
                "metrics": {
                    "steps": [
                        {"date": "2026-06-01", "value": 100, "source": "Watch"},
                        {"date": "2026-06-02", "value": 200, "source": "Watch"},
                        {"date": "2026-06-03", "value": 300, "source": "Watch"},
                    ],
                    "workouts": [
                        {
                            "date": "2026-06-02 07:00:00",
                            "type": "Running",
                            "duration_min": 30,
                            "calories": 240,
                            "distance_km": 5,
                            "source": "Watch",
                        },
                        {
                            "date": "2026-06-03 07:00:00",
                            "type": "Running",
                            "duration_min": 25,
                            "source": "Watch",
                        },
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "health",
            "import",
            str(export),
            "--from",
            "2026-06-02",
            "--to",
            "2026-06-03",
            "--json",
        ],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["date_start"] == "2026-06-02"
    assert payload["date_end"] == "2026-06-02"
    assert payload["summary"] == {
        "daily": 1,
        "workouts": 1,
        "ignored_route_files": 0,
        "export_xml": "health-export.json",
    }


def test_health_import_zip_counts_route_gpx_and_keeps_workout_external_id(tmp_path):
    export = tmp_path / "apple-health.zip"
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData>
  <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" startDate="2026-06-01 08:00:00 +0800" endDate="2026-06-01 08:05:00 +0800" value="100"/>
  <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" startDate="2026-06-02 08:00:00 +0800" endDate="2026-06-02 08:05:00 +0800" value="200"/>
  <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" startDate="2026-06-03 08:00:00 +0800" endDate="2026-06-03 08:05:00 +0800" value="300"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeRunning" sourceName="Watch" startDate="2026-06-02 07:00:00 +0800" endDate="2026-06-02 07:30:00 +0800" duration="30" durationUnit="min" totalEnergyBurned="240" totalEnergyBurnedUnit="kcal" totalDistance="5" totalDistanceUnit="km"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeRunning" sourceName="Watch" startDate="2026-06-03 07:00:00 +0800" endDate="2026-06-03 07:30:00 +0800" duration="30" durationUnit="min"/>
</HealthData>
"""
    with zipfile.ZipFile(export, "w") as archive:
        archive.writestr("export.xml", xml)
        archive.writestr("workout-routes/route-1.gpx", "<gpx/>")
        archive.writestr("apple_health_export/workout-routes/route-2.gpx", "<gpx/>")

    result = CliRunner().invoke(
        cli,
        [
            "health",
            "import",
            str(export),
            "--from",
            "2026-06-02",
            "--to",
            "2026-06-03",
            "--json",
        ],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["summary"] == {
        "daily": 1,
        "workouts": 1,
        "ignored_route_files": 2,
        "export_xml": "export.xml",
    }
    assert payload["date_start"] == "2026-06-02"
    assert payload["date_end"] == "2026-06-02"

    parsed = parse_apple_health_export(export, date_from="2026-06-02", date_to="2026-06-03")
    assert len(parsed.workouts) == 1
    assert len(parsed.workouts[0]["external_id"]) == 40
