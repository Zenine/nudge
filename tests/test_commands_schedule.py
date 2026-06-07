import json
from datetime import date

from click.testing import CliRunner

from nudge.commands.schedule import schedule_command


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 6, 8)


def _event(summary, start, end, calendar="Work"):
    return {
        "summary": summary,
        "start": start,
        "end": end,
        "calendar": calendar,
    }


def _run_schedule(monkeypatch, request, events, profile=None):
    profile = profile or {
        "schedule": {
            "work_hours": ["09:00", "18:00"],
            "personal_hours": ["18:00", "21:00"],
        }
    }

    monkeypatch.setattr("nudge.commands.schedule.date", FixedDate)
    monkeypatch.setattr("nudge.commands.schedule.load_config", lambda config_path=None: {})
    monkeypatch.setattr("nudge.commands.schedule.get_user_profile", lambda config: profile)
    monkeypatch.setattr("nudge.commands.schedule.get_configured_calendar_names", lambda config: ["Work"])
    monkeypatch.setattr("nudge.commands.schedule.get_week_events", lambda calendar_names=None: events)

    result = CliRunner().invoke(
        schedule_command,
        ["--json", request],
        prog_name="nudge schedule",
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_schedule_recommends_two_hour_deep_work_slot_from_fake_calendar(monkeypatch):
    payload = _run_schedule(
        monkeypatch,
        "找2小时深度工作时间",
        [
            _event("standup", "2026-06-08 09:00", "2026-06-08 10:00"),
            _event("lunch", "2026-06-08 12:00", "2026-06-08 13:00"),
            _event("review", "2026-06-08 15:00", "2026-06-08 16:00"),
        ],
    )

    assert payload["ok"] is True
    assert payload["request"] == "找2小时深度工作时间"
    assert payload["duration_minutes"] == 120
    assert payload["preference"] == "work"
    assert payload["recommended_slot"] == {
        "date": "2026-06-08",
        "day_name": "周一",
        "start": "10:00",
        "end": "12:00",
        "duration_minutes": 120,
    }


def test_schedule_filters_slots_shorter_than_requested_duration(monkeypatch):
    payload = _run_schedule(
        monkeypatch,
        "找90分钟工作时间",
        [
            _event("short before", "2026-06-08 10:00", "2026-06-08 10:30"),
            _event("short after", "2026-06-08 12:00", "2026-06-08 17:00"),
        ],
    )

    assert payload["ok"] is True
    assert payload["duration_minutes"] == 90
    assert payload["recommended_slot"]["start"] == "10:30"
    assert payload["recommended_slot"]["end"] == "12:00"
    assert all(slot["duration_minutes"] >= 90 for slot in payload["candidate_slots"])


def test_schedule_respects_today_and_tomorrow_date_filters(monkeypatch):
    today_payload = _run_schedule(monkeypatch, "今天找2小时工作时间", [])
    tomorrow_payload = _run_schedule(monkeypatch, "明天找2小时工作时间", [])

    assert today_payload["recommended_slot"]["date"] == "2026-06-08"
    assert tomorrow_payload["recommended_slot"]["date"] == "2026-06-09"


def test_schedule_uses_personal_hours_for_personal_requests(monkeypatch):
    payload = _run_schedule(monkeypatch, "今天找1小时个人时间", [])

    assert payload["preference"] == "personal"
    assert payload["recommended_slot"]["start"] == "18:00"
    assert payload["recommended_slot"]["end"] == "19:00"


def test_schedule_reports_no_available_slot(monkeypatch):
    payload = _run_schedule(
        monkeypatch,
        "今天找2小时深度工作时间",
        [
            _event("busy all day", "2026-06-08 09:00", "2026-06-08 18:00"),
            _event("free tomorrow should not count", "2026-06-09 09:00", "2026-06-09 10:00"),
        ],
    )

    assert payload == {
        "ok": False,
        "request": "今天找2小时深度工作时间",
        "duration_minutes": 120,
        "preference": "work",
        "recommended_slot": None,
        "candidate_slots": [],
        "message": "没有找到满足需求的可用时间段",
    }
