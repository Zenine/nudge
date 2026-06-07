"""Apple Health export parsing and local health summary import."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

from nudge.state import save_health_import


RECORD_TYPES = {
    "HKQuantityTypeIdentifierStepCount",
    "HKQuantityTypeIdentifierDistanceWalkingRunning",
    "HKQuantityTypeIdentifierActiveEnergyBurned",
    "HKQuantityTypeIdentifierBasalEnergyBurned",
    "HKQuantityTypeIdentifierAppleExerciseTime",
    "HKQuantityTypeIdentifierAppleStandTime",
    "HKQuantityTypeIdentifierHeartRate",
    "HKQuantityTypeIdentifierRestingHeartRate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
    "HKQuantityTypeIdentifierWalkingHeartRateAverage",
    "HKQuantityTypeIdentifierVO2Max",
    "HKQuantityTypeIdentifierBodyMass",
    "HKQuantityTypeIdentifierBodyFatPercentage",
    "HKCategoryTypeIdentifierSleepAnalysis",
}


@dataclass
class HealthImportResult:
    """Parsed Apple Health export data ready for SQLite import."""

    source_path: str
    source_hash: str
    export_xml_name: str
    ignored_route_files: int
    daily_summaries: list[dict]
    workouts: list[dict]

    @property
    def date_start(self) -> str | None:
        dates = [row["date"] for row in self.daily_summaries]
        workout_dates = [str(row.get("start_at", ""))[:10] for row in self.workouts if row.get("start_at")]
        all_dates = [d for d in [*dates, *workout_dates] if d]
        return min(all_dates) if all_dates else None

    @property
    def date_end(self) -> str | None:
        dates = [row["date"] for row in self.daily_summaries]
        workout_dates = [str(row.get("start_at", ""))[:10] for row in self.workouts if row.get("start_at")]
        all_dates = [d for d in [*dates, *workout_dates] if d]
        return max(all_dates) if all_dates else None


class _DailyAccumulator:
    """Mutable accumulator for one local health summary date."""

    def __init__(self, summary_date: str):
        self.date = summary_date
        self.steps = 0.0
        self.distance_walking_running_m = 0.0
        self.active_energy_kcal = 0.0
        self.basal_energy_kcal = 0.0
        self.exercise_minutes = 0.0
        self.stand_minutes = 0.0
        self.sleep_asleep_minutes = 0.0
        self.sleep_in_bed_minutes = 0.0
        self.heart_rates: list[float] = []
        self.resting_heart_rates: list[float] = []
        self.hrv_sdnn_values: list[float] = []
        self.walking_heart_rates: list[float] = []
        self.vo2max_values: list[float] = []
        self.body_weight: tuple[str, float] | None = None
        self.body_fat: tuple[str, float] | None = None
        self.source_counts: dict[str, int] = {}

    def add_source(self, source_name: str | None) -> None:
        source = source_name or "unknown"
        self.source_counts[source] = self.source_counts.get(source, 0) + 1

    def as_dict(self) -> dict:
        return {
            "date": self.date,
            "steps": _round(self.steps, 0),
            "distance_walking_running_m": _round(self.distance_walking_running_m, 2),
            "active_energy_kcal": _round(self.active_energy_kcal, 2),
            "basal_energy_kcal": _round(self.basal_energy_kcal, 2),
            "exercise_minutes": _round(self.exercise_minutes, 2),
            "stand_minutes": _round(self.stand_minutes, 2),
            "sleep_asleep_minutes": _round(self.sleep_asleep_minutes, 2),
            "sleep_in_bed_minutes": _round(self.sleep_in_bed_minutes, 2),
            "avg_heart_rate": _avg(self.heart_rates),
            "resting_heart_rate": _avg(self.resting_heart_rates),
            "hrv_sdnn_avg": _avg(self.hrv_sdnn_values),
            "walking_heart_rate_avg": _avg(self.walking_heart_rates),
            "vo2max": _avg(self.vo2max_values),
            "body_weight_kg": self.body_weight[1] if self.body_weight else None,
            "body_fat_percent": self.body_fat[1] if self.body_fat else None,
            "source_counts": dict(sorted(self.source_counts.items())),
        }


def parse_apple_health_export(
    path: str | Path,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> HealthImportResult:
    """Parse an Apple Health export into daily summaries and workouts.

    Route GPX files are intentionally counted but ignored. Nudge stores daily
    health aggregates and workout metadata, not location traces or raw samples.
    """
    export_path = Path(path)
    if export_path.suffix.lower() == ".json":
        return parse_apple_health_export_json(
            export_path,
            date_from=date_from,
            date_to=date_to,
        )
    source_hash = _file_sha256(export_path)
    daily: dict[str, _DailyAccumulator] = {}
    workouts: list[dict] = []
    ignored_route_files = 0

    with ZipFile(export_path) as zf:
        export_xml = _find_health_export_xml(zf)
        ignored_route_files = sum(1 for name in zf.namelist() if _is_workout_route_gpx(name))
        with zf.open(export_xml) as xml_file:
            for _event, elem in ET.iterparse(xml_file, events=("end",)):
                if elem.tag == "Record":
                    _consume_record(elem.attrib, daily, date_from=date_from, date_to=date_to)
                elif elem.tag == "Workout":
                    workout = _workout_payload(elem.attrib)
                    if workout and _date_allowed(str(workout["start_at"])[:10], date_from, date_to):
                        workouts.append(workout)
                        summary_date = str(workout["start_at"])[:10]
                        accumulator = daily.setdefault(summary_date, _DailyAccumulator(summary_date))
                        accumulator.add_source(workout.get("source_name"))
                elem.clear()

    daily_summaries = [
        accumulator.as_dict()
        for summary_date, accumulator in sorted(daily.items())
        if _date_allowed(summary_date, date_from, date_to)
    ]

    return HealthImportResult(
        source_path=str(export_path),
        source_hash=source_hash,
        export_xml_name=export_xml,
        ignored_route_files=ignored_route_files,
        daily_summaries=daily_summaries,
        workouts=workouts,
    )


def apply_health_import(result: HealthImportResult) -> dict:
    """Persist one parsed health import into SQLite."""
    return save_health_import(
        source_path=result.source_path,
        source_hash=result.source_hash,
        export_xml_name=result.export_xml_name,
        date_start=result.date_start,
        date_end=result.date_end,
        daily_summaries=result.daily_summaries,
        workouts=result.workouts,
    )


def parse_apple_health_export_json(
    path: Path,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> HealthImportResult:
    """Parse HealthExport JSON into daily summaries and workout metadata."""
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    source_hash = _file_sha256(path)
    daily: dict[str, _DailyAccumulator] = {}
    workouts: list[dict] = []

    metrics = payload.get("metrics") if isinstance(payload, dict) else None
    if not isinstance(metrics, dict):
        raise ValueError("Health export JSON missing 'metrics'")

    for sample in _iter_json_records(metrics.get("steps")):
        _consume_json_record(
            date=sample.get("date"),
            source=sample.get("source"),
            value=_float(sample.get("value")),
            value_type="steps",
            daily=daily,
            date_from=date_from,
            date_to=date_to,
        )

    for sample in _iter_json_records(metrics.get("active_calories")):
        _consume_json_record(
            date=sample.get("date"),
            source=sample.get("source"),
            value=_float(sample.get("value")),
            value_type="active_energy_kcal",
            daily=daily,
            date_from=date_from,
            date_to=date_to,
        )

    for sample in _iter_json_records(metrics.get("sleep")):
        summary_date = _date_part(sample.get("date"))
        if not summary_date or not _date_allowed(summary_date, date_from, date_to):
            continue

        summary = daily.setdefault(summary_date, _DailyAccumulator(summary_date))
        summary.add_source(sample.get("source"))

        stages = sample.get("stages") or {}
        summary.sleep_in_bed_minutes += (
            (_float(stages.get("awake_min")) or 0)
            + (_float(stages.get("core_min")) or 0)
            + (_float(stages.get("deep_min")) or 0)
            + (_float(stages.get("rem_min")) or 0)
        )
        summary.sleep_asleep_minutes += (
            (_float(stages.get("core_min")) or 0)
            + (_float(stages.get("deep_min")) or 0)
            + (_float(stages.get("rem_min")) or 0)
        )

    for sample in _iter_json_records(metrics.get("heart_rate")):
        summary_date = _date_part(sample.get("date"))
        if not summary_date or not _date_allowed(summary_date, date_from, date_to):
            continue

        summary = daily.setdefault(summary_date, _DailyAccumulator(summary_date))
        summary.add_source(sample.get("source"))

        average_bpm = _float(sample.get("average_bpm"))
        if average_bpm is not None:
            summary.heart_rates.append(average_bpm)

        resting_bpm = _float(sample.get("resting_bpm"))
        if resting_bpm is not None:
            summary.resting_heart_rates.append(resting_bpm)

    for sample in _iter_json_records(metrics.get("weight")):
        summary_date = _date_part(sample.get("date"))
        if not summary_date or not _date_allowed(summary_date, date_from, date_to):
            continue

        summary = daily.setdefault(summary_date, _DailyAccumulator(summary_date))
        summary.add_source(sample.get("source"))
        weight = _float(sample.get("value_kg") if "value_kg" in sample else sample.get("value"))
        if weight is not None:
            summary.body_weight = _latest_value(summary.body_weight, {"endDate": sample.get("date")}, weight)

    body_fat_percentages = _iter_json_records(metrics.get("body_fat"))
    body_fat_percentages.extend(_iter_json_records(metrics.get("body_fat_percentage")))
    for sample in body_fat_percentages:
        summary_date = _date_part(sample.get("date"))
        if not summary_date or not _date_allowed(summary_date, date_from, date_to):
            continue

        summary = daily.setdefault(summary_date, _DailyAccumulator(summary_date))
        summary.add_source(sample.get("source"))
        body_fat = _float(sample.get("value"))
        if body_fat is not None:
            summary.body_fat = _latest_value(summary.body_fat, {"endDate": sample.get("date")}, _percent_value(body_fat))

    for sample in _iter_json_records(metrics.get("workouts")):
        start_at, end_at, payload = _workout_payload_from_json(sample)
        if not start_at or not payload:
            continue
        summary_date = _date_part(start_at)
        if not summary_date or not _date_allowed(summary_date, date_from, date_to):
            continue

        summary = daily.setdefault(summary_date, _DailyAccumulator(summary_date))
        summary.add_source(payload.get("source_name"))
        workouts.append(payload)

    daily_summaries = [
        summary.as_dict()
        for summary_date, summary in sorted(daily.items())
        if _date_allowed(summary_date, date_from, date_to)
    ]

    return HealthImportResult(
        source_path=str(path),
        source_hash=source_hash,
        export_xml_name=path.name,
        ignored_route_files=0,
        daily_summaries=daily_summaries,
        workouts=workouts,
    )


def _iter_json_records(value: object) -> list[dict]:
    """Normalize HealthExport metric section into a list of dict records."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        nested: list[dict] = []
        for nested_value in value.values():
            if isinstance(nested_value, dict):
                nested.append(nested_value)
            elif isinstance(nested_value, list):
                nested.extend(item for item in nested_value if isinstance(item, dict))
        return nested
    return []


def _consume_record(
    attrs: dict[str, str],
    daily: dict[str, _DailyAccumulator],
    *,
    date_from: str | None,
    date_to: str | None,
) -> None:
    record_type = attrs.get("type", "")
    if record_type not in RECORD_TYPES:
        return

    summary_date = _record_summary_date(attrs)
    if not summary_date or not _date_allowed(summary_date, date_from, date_to):
        return

    accumulator = daily.setdefault(summary_date, _DailyAccumulator(summary_date))
    accumulator.add_source(attrs.get("sourceName"))

    value = _float(attrs.get("value"))
    unit = attrs.get("unit", "")
    if value is None and record_type != "HKCategoryTypeIdentifierSleepAnalysis":
        return

    if record_type == "HKQuantityTypeIdentifierStepCount":
        accumulator.steps += value or 0
    elif record_type == "HKQuantityTypeIdentifierDistanceWalkingRunning":
        accumulator.distance_walking_running_m += _distance_to_meters(value or 0, unit)
    elif record_type == "HKQuantityTypeIdentifierActiveEnergyBurned":
        accumulator.active_energy_kcal += _energy_to_kcal(value or 0, unit)
    elif record_type == "HKQuantityTypeIdentifierBasalEnergyBurned":
        accumulator.basal_energy_kcal += _energy_to_kcal(value or 0, unit)
    elif record_type == "HKQuantityTypeIdentifierAppleExerciseTime":
        accumulator.exercise_minutes += _duration_to_minutes(value or 0, unit)
    elif record_type == "HKQuantityTypeIdentifierAppleStandTime":
        accumulator.stand_minutes += _duration_to_minutes(value or 0, unit)
    elif record_type == "HKQuantityTypeIdentifierHeartRate":
        accumulator.heart_rates.append(value or 0)
    elif record_type == "HKQuantityTypeIdentifierRestingHeartRate":
        accumulator.resting_heart_rates.append(value or 0)
    elif record_type == "HKQuantityTypeIdentifierHeartRateVariabilitySDNN":
        accumulator.hrv_sdnn_values.append(value or 0)
    elif record_type == "HKQuantityTypeIdentifierWalkingHeartRateAverage":
        accumulator.walking_heart_rates.append(value or 0)
    elif record_type == "HKQuantityTypeIdentifierVO2Max":
        accumulator.vo2max_values.append(value or 0)
    elif record_type == "HKQuantityTypeIdentifierBodyMass":
        accumulator.body_weight = _latest_value(accumulator.body_weight, attrs, value or 0)
    elif record_type == "HKQuantityTypeIdentifierBodyFatPercentage":
        accumulator.body_fat = _latest_value(
            accumulator.body_fat,
            attrs,
            _percent_value(value or 0),
        )
    elif record_type == "HKCategoryTypeIdentifierSleepAnalysis":
        minutes = _interval_minutes(attrs.get("startDate"), attrs.get("endDate"))
        sleep_value = attrs.get("value", "")
        if "InBed" in sleep_value:
            accumulator.sleep_in_bed_minutes += minutes
        elif "Asleep" in sleep_value:
            accumulator.sleep_asleep_minutes += minutes


def _consume_json_record(
    *,
    date: str | None,
    source: str | None,
    value: float | None,
    value_type: str,
    daily: dict[str, _DailyAccumulator],
    date_from: str | None,
    date_to: str | None,
) -> None:
    if value is None:
        return

    summary_date = _date_part(date)
    if not summary_date or not _date_allowed(summary_date, date_from, date_to):
        return

    accumulator = daily.setdefault(summary_date, _DailyAccumulator(summary_date))
    accumulator.add_source(source)
    if value_type == "steps":
        accumulator.steps += value
    elif value_type == "active_energy_kcal":
        accumulator.active_energy_kcal += value
    else:
        raise ValueError("unsupported json value_type")


def _workout_payload_from_json(attrs: dict) -> tuple[str | None, str | None, dict | None]:
    start_at = _date_time_to_local(attrs.get("date"), 0)
    if start_at is None:
        return None, None, None

    duration = (
        _float(attrs.get("duration_min"))
        or _float(attrs.get("duration"))
        or 0.0
    )
    end_at = _date_time_to_local(attrs.get("date"), duration)
    if end_at is None:
        return None, None, None

    source_name = attrs.get("source") or "unknown"
    workout_type = _normalize_workout_type(attrs.get("type", ""))
    energy = _energy_to_kcal(_float(attrs.get("calories")) or 0, "kcal")
    distance = (
        _distance_to_meters(_float(attrs.get("distance_km")) or 0, "km")
        if attrs.get("distance_km") is not None
        else _distance_to_meters(_float(attrs.get("distance")) or 0, "m")
    )

    payload = {
        "source_name": source_name,
        "workout_type": workout_type,
        "start_at": start_at,
        "end_at": end_at,
        "duration_minutes": _round(duration, 2),
        "active_energy_kcal": _round(energy, 2),
        "distance_m": _round(distance, 2),
    }
    payload["external_id"] = _workout_external_id({
        "source_name": source_name,
        "workout_type": workout_type,
        "start_at": start_at,
        "end_at": end_at,
        "duration_minutes": _round(duration, 2),
        "active_energy_kcal": _round(energy, 2),
        "distance_m": _round(distance, 2),
    })
    return start_at, end_at, payload


def _workout_payload(attrs: dict[str, str]) -> dict | None:
    start_at = _normalize_datetime(attrs.get("startDate"))
    end_at = _normalize_datetime(attrs.get("endDate"))
    if not start_at:
        return None

    workout_type = _normalize_workout_type(attrs.get("workoutActivityType", ""))
    source_name = attrs.get("sourceName") or "unknown"
    duration = _duration_to_minutes(
        _float(attrs.get("duration")) or _interval_minutes(attrs.get("startDate"), attrs.get("endDate")),
        attrs.get("durationUnit", "min"),
    )
    energy = _energy_to_kcal(
        _float(attrs.get("totalEnergyBurned")) or 0,
        attrs.get("totalEnergyBurnedUnit", "kcal"),
    )
    distance = _distance_to_meters(
        _float(attrs.get("totalDistance")) or 0,
        attrs.get("totalDistanceUnit", "m"),
    )
    external_id = _workout_external_id({
        "source_name": source_name,
        "workout_type": workout_type,
        "start_at": start_at,
        "end_at": end_at,
        "duration_minutes": _round(duration, 2),
        "active_energy_kcal": _round(energy, 2),
        "distance_m": _round(distance, 2),
    })
    return {
        "external_id": external_id,
        "source_name": source_name,
        "workout_type": workout_type,
        "start_at": start_at,
        "end_at": end_at,
        "duration_minutes": _round(duration, 2),
        "active_energy_kcal": _round(energy, 2),
        "distance_m": _round(distance, 2),
    }


def _find_health_export_xml(zf: ZipFile) -> str:
    for info in zf.infolist():
        if not info.filename.lower().endswith(".xml"):
            continue
        with zf.open(info) as candidate:
            sample = candidate.read(2048).decode("utf-8", errors="replace")
        if "HealthData" in sample:
            return info.filename
    raise ValueError("Apple Health export XML not found in zip")


def _is_workout_route_gpx(name: str) -> bool:
    parts = Path(name).parts
    return "workout-routes" in parts and name.lower().endswith(".gpx")


def _record_summary_date(attrs: dict[str, str]) -> str | None:
    if attrs.get("type") == "HKCategoryTypeIdentifierSleepAnalysis":
        return _date_part(attrs.get("endDate"))
    return _date_part(attrs.get("startDate") or attrs.get("creationDate"))


def _date_part(value: str | None) -> str | None:
    return value[:10] if value else None


def _normalize_datetime(value: str | None) -> str | None:
    if not value:
        return None
    return value[:16]


def _date_time_to_local(value: str | None, duration_min: float = 0) -> str | None:
    parsed = _parse_datetime_like(value)
    if parsed is None:
        return None
    if duration_min:
        parsed = parsed + timedelta(minutes=duration_min)
    return parsed.strftime("%Y-%m-%d %H:%M")


def _parse_datetime_like(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.count("-") == 2 and len(text) == 10:
        try:
            return datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
    normalized = text
    if text.endswith("Z"):
        normalized = text[:-1] + "+00:00"
    if len(normalized) >= 5 and normalized[-5] in {"+", "-"} and ":" not in normalized[-5:]:
        normalized = f"{normalized[:-5]}{normalized[-5:-2]}:{normalized[-2:]}"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        pass
    else:
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
            return parsed.replace(tzinfo=None)
        return parsed

    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=None)
        except ValueError:
            pass

    base = _date_part(text)
    if not base:
        return None
    try:
        return datetime.strptime(base, "%Y-%m-%d")
    except ValueError:
        return None


def _parse_health_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _interval_minutes(start: str | None, end: str | None) -> float:
    start_dt = _parse_health_datetime(start)
    end_dt = _parse_health_datetime(end)
    if not start_dt or not end_dt:
        return 0.0
    return max(0.0, (end_dt - start_dt).total_seconds() / 60)


def _date_allowed(summary_date: str, date_from: str | None, date_to: str | None) -> bool:
    if date_from and summary_date < date_from:
        return False
    if date_to and summary_date >= date_to:
        return False
    return True


def _float(value: str | None) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _distance_to_meters(value: float, unit: str) -> float:
    normalized = unit.lower()
    if normalized == "km":
        return value * 1000
    if normalized in {"mi", "mile", "miles"}:
        return value * 1609.344
    return value


def _energy_to_kcal(value: float, unit: str) -> float:
    normalized = unit.lower()
    if normalized in {"kj", "kilojoule", "kilojoules"}:
        return value / 4.184
    return value


def _duration_to_minutes(value: float, unit: str) -> float:
    normalized = unit.lower()
    if normalized in {"h", "hr", "hour", "hours"}:
        return value * 60
    if normalized in {"s", "sec", "second", "seconds"}:
        return value / 60
    return value


def _percent_value(value: float) -> float:
    return value * 100 if value <= 1 else value


def _latest_value(current: tuple[str, float] | None, attrs: dict[str, str], value: float) -> tuple[str, float]:
    timestamp = attrs.get("endDate") or attrs.get("startDate") or attrs.get("creationDate") or ""
    normalized = timestamp[:19]
    if current is None or normalized >= current[0]:
        return normalized, _round(value, 4)
    return current


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return _round(sum(values) / len(values), 2)


def _round(value: float, digits: int) -> float | int:
    rounded = round(value, digits)
    return int(rounded) if digits == 0 else rounded


def _normalize_workout_type(value: str) -> str:
    raw = str(value or "").replace("HKWorkoutActivityType", "")
    if not raw:
        return "unknown"
    result = []
    for index, char in enumerate(raw):
        if char.isupper() and index > 0 and raw[index - 1].islower():
            result.append("_")
        result.append(char.lower())
    return "".join(result).strip("_") or "unknown"


def _workout_external_id(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
