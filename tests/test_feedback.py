"""Tests for shared feedback schema helpers."""

from nudge.feedback import (
    FEEDBACK_SCHEMA_VERSION,
    build_feedback,
    feedback_source_summary,
    normalize_feedback,
)


def test_build_feedback_adds_canonical_source_fields_and_preserves_extra_metadata():
    feedback = build_feedback(
        source="nudge log parse",
        channel="cli.log.parse",
        source_type="subjective",
        note="完成 30 分钟",
        reason="low_energy",
        next_action="keep",
        metrics={"minutes": 30},
        raw_text="今天读了 30 分钟",
        extra={"source_hint": "voice"},
    )

    assert feedback == {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "source": "nudge log parse",
        "channel": "cli.log.parse",
        "source_type": "subjective",
        "note": "完成 30 分钟",
        "reason": "low_energy",
        "next_action": "keep",
        "metrics": {"minutes": 30},
        "raw_text": "今天读了 30 分钟",
        "source_hint": "voice",
    }


def test_normalize_feedback_supports_legacy_reminders_payload_and_infers_objective_source():
    normalized = normalize_feedback(
        '{"source": "nudge reminders sync-completed", "note": "Apple 已完成", "sync_date": "2026-04-27"}'
    )

    assert normalized["schema_version"] == FEEDBACK_SCHEMA_VERSION
    assert normalized["source"] == "nudge reminders sync-completed"
    assert normalized["channel"] == "reminders.sync_completed"
    assert normalized["source_type"] == "objective"
    assert normalized["note"] == "Apple 已完成"
    assert normalized["sync_date"] == "2026-04-27"


def test_feedback_source_summary_counts_subjective_objective_agent_and_unknown_sources():
    actions = [
        {"feedback": {"source_type": "subjective", "channel": "cli.log"}},
        {"feedback": '{"source": "nudge reminders sync-completed"}'},
        {"feedback": {"source_type": "agent", "channel": "mcp.report_action_status"}},
        {"feedback": {"note": "legacy unknown"}},
        {"feedback": "freeform legacy note"},
        {"feedback": None},
    ]

    summary = feedback_source_summary(actions)

    assert summary == {
        "total": 5,
        "by_type": {"subjective": 1, "objective": 1, "agent": 1, "unknown": 2},
        "by_channel": {
            "cli.log": 1,
            "reminders.sync_completed": 1,
            "mcp.report_action_status": 1,
            "unknown": 2,
        },
    }


def test_feedback_interview_channel_is_counted_as_subjective():
    feedback = build_feedback(
        source="nudge feedback interview",
        channel="cli.feedback.interview",
        source_type="subjective",
        extra={"interview": {"protocol_version": "nudge.feedback.interview.v1"}},
    )

    summary = feedback_source_summary([{"feedback": feedback}])

    assert summary["by_type"] == {"subjective": 1}
    assert summary["by_channel"] == {"cli.feedback.interview": 1}
