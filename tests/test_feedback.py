"""Tests for feedback payload normalization boundaries."""

from __future__ import annotations

from nudge.feedback import (
    FEEDBACK_SCHEMA_VERSION,
    build_feedback,
    feedback_source_label,
    feedback_source_summary,
    normalize_feedback,
)


def test_build_feedback_infers_channel_and_source_type_from_source():
    feedback = build_feedback(source="nudge log parse", note="完成了")

    assert feedback["schema_version"] == FEEDBACK_SCHEMA_VERSION
    assert feedback["channel"] == "cli.log.parse"
    assert feedback["source_type"] == "subjective"
    assert feedback["note"] == "完成了"


def test_build_feedback_drops_invalid_status_reason_and_next_action():
    feedback = build_feedback(
        source="nudge log",
        reason="不是合法原因",
        next_action="稍后再说",
    )

    assert "reason" not in feedback
    assert "next_action" not in feedback


def test_build_feedback_keeps_valid_status_reason_and_next_action():
    feedback = build_feedback(source="nudge log", reason="conflict", next_action="reschedule")

    assert feedback["reason"] == "conflict"
    assert feedback["next_action"] == "reschedule"


def test_normalize_feedback_handles_invalid_json_and_non_dict_json():
    assert normalize_feedback("[]") == {}
    assert normalize_feedback("{broken") == {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "note": "{broken",
        "source_type": "unknown",
    }


def test_feedback_source_summary_ignores_empty_feedback_and_strips_bad_metrics():
    summary = feedback_source_summary(
        [
            {"feedback": {"source": "nudge log", "metrics": ["bad"]}},
            {"feedback": None},
            {"feedback": '{"source": "nudge reminders sync-completed"}'},
        ]
    )

    assert summary == {
        "total": 2,
        "by_type": {"subjective": 1, "objective": 1},
        "by_channel": {"cli.log": 1, "reminders.sync_completed": 1},
    }
    assert "metrics" not in normalize_feedback({"source": "nudge log", "metrics": ["bad"]})


def test_feedback_source_label_uses_channel_over_source():
    assert feedback_source_label({"source_type": "system", "source": "raw", "channel": "sleep.auto_skip"}) == (
        "system:sleep.auto_skip"
    )
