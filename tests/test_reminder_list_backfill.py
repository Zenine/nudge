"""Pure planning contracts for legacy Reminder list ownership backfill."""

from datetime import date, datetime

import pytest

from nudge.reminder_lists import (
    ReminderListBackfillBatch,
    parse_strict_minute,
    plan_list_backfill,
    resolve_sync_lists,
    select_list_backfill_actions,
)


def _action(
    action_id: str,
    *,
    summary: object = "Example",
    scheduled_at: object = "2026-07-01 09:00",
    status: str = "pending",
    action_type: str = "reminder",
    reminder_list: object = None,
) -> dict:
    return {
        "id": action_id,
        "type": action_type,
        "summary": summary,
        "scheduled_at": scheduled_at,
        "status": status,
        "reminder_list": reminder_list,
    }


def test_resolve_sync_lists_prefers_explicit_names_and_deduplicates() -> None:
    config = {
        "general": {"default_reminder_list": "Default"},
        "reminders": {"sync_lists": ["Configured", "Configured", "Other"]},
    }

    assert resolve_sync_lists(("GPT", "Tasks", "GPT"), config) == ["GPT", "Tasks"]
    assert resolve_sync_lists((), config) == ["Configured", "Other"]


def test_resolve_sync_lists_preserves_fallback_and_invalid_input_contracts() -> None:
    assert resolve_sync_lists((), {"general": {"default_reminder_list": "Inbox"}}) == ["Inbox"]

    with pytest.raises(ValueError, match="must be an array"):
        resolve_sync_lists((), {"reminders": {"sync_lists": "Inbox"}})
    with pytest.raises(ValueError, match="non-empty strings"):
        resolve_sync_lists((" ",), {})
    with pytest.raises(ValueError, match="at least one"):
        resolve_sync_lists((), {"reminders": {"sync_lists": []}})


@pytest.mark.parametrize(
    "value",
    [
        " 2026-07-01 09:00",
        "2026-07-01 09:00 ",
        "2026-07-01 09:00junk",
        "2026-07-01 09:00:00",
        "2026-07-01 09:00+08:00",
        "2026-07-01T09:00",
        "2026-07-01 09:00Z",
        None,
        202607010900,
    ],
)
def test_parse_strict_minute_rejects_noncanonical_values(value: object) -> None:
    assert parse_strict_minute(value) is None


def test_parse_strict_minute_accepts_only_exact_canonical_minute() -> None:
    assert parse_strict_minute("2026-07-01 09:00") == datetime(2026, 7, 1, 9, 0)


def test_select_list_backfill_actions_filters_sorts_limits_and_reports_invalid() -> None:
    actions = [
        _action("a", scheduled_at="2026-07-02 08:00"),
        _action("b", scheduled_at="2026-07-01 09:00"),
        _action("before", scheduled_at="2026-06-30 23:59"),
        _action("at-to", scheduled_at="2026-08-01 00:00"),
        _action("closed", scheduled_at="2026-07-03 09:00", status="done"),
        _action("owned", scheduled_at="2026-07-03 09:00", reminder_list="Tasks"),
        _action("invalid", summary="", scheduled_at="2026-07-03 09:00"),
    ]

    batch = select_list_backfill_actions(
        actions,
        date_from=date(2026, 7, 1),
        date_to=date(2026, 8, 1),
        limit=1,
    )

    assert isinstance(batch, ReminderListBackfillBatch)
    assert batch.actions == [_action("b", scheduled_at="2026-07-01 09:00")]
    assert batch.query_dates == (date(2026, 7, 1),)
    assert batch.total_eligible == 2
    assert batch.remaining == 1
    assert batch.invalid == [
        {
            "id": "invalid",
            "summary": "",
            "scheduled_at": "2026-07-03 09:00",
            "reason": "invalid_summary_or_scheduled_at",
        }
    ]


def test_select_list_backfill_actions_keeps_stable_minute_and_id_order() -> None:
    actions = [
        _action("z", scheduled_at="2026-07-02 09:00"),
        _action("b", scheduled_at="2026-07-01 09:00"),
        _action("a", scheduled_at="2026-07-01 09:00"),
        _action("created", scheduled_at="2026-07-01 08:00", status="created"),
    ]

    batch = select_list_backfill_actions(actions, date_from=None, date_to=None)

    assert [item["id"] for item in batch.actions] == ["created", "a", "b", "z"]
    assert batch.query_dates == (date(2026, 7, 1), date(2026, 7, 2))
    assert batch.total_eligible == 4
    assert batch.remaining == 0


@pytest.mark.parametrize(
    ("date_from", "date_to"),
    [
        (date(2026, 7, 1), date(2026, 7, 1)),
        (date(2026, 7, 2), date(2026, 7, 1)),
    ],
)
def test_select_list_backfill_actions_requires_to_later_than_from(
    date_from: date,
    date_to: date,
) -> None:
    with pytest.raises(ValueError) as exc_info:
        select_list_backfill_actions([], date_from=date_from, date_to=date_to)

    assert str(exc_info.value) == "--to must be later than --from"


def test_select_list_backfill_actions_enforces_default_and_maximum_batch_sizes() -> None:
    actions = [_action(f"action-{index:03d}") for index in range(501)]

    default_batch = select_list_backfill_actions(actions, date_from=None, date_to=None)
    maximum_batch = select_list_backfill_actions(
        actions,
        date_from=None,
        date_to=None,
        limit=500,
    )

    assert len(default_batch.actions) == 100
    assert default_batch.total_eligible == 501
    assert default_batch.remaining == 401
    assert len(maximum_batch.actions) == 500
    assert maximum_batch.total_eligible == 501
    assert maximum_batch.remaining == 1


def test_select_list_backfill_actions_classifies_only_open_legacy_invalid_rows() -> None:
    actions = [
        _action("empty-list", reminder_list=""),
        _action("blank-summary", summary="   "),
        _action("bad-time", scheduled_at="2026-07-01T09:00"),
        _action("other-type", action_type="calendar_event", reminder_list=""),
        _action("closed", status="done", reminder_list=""),
        _action("owned", reminder_list="Tasks"),
    ]

    batch = select_list_backfill_actions(actions, date_from=None, date_to=None)

    assert batch.actions == []
    assert batch.invalid == [
        {
            "id": "empty-list",
            "summary": "Example",
            "scheduled_at": "2026-07-01 09:00",
            "reason": "empty_reminder_list",
        },
        {
            "id": "blank-summary",
            "summary": "   ",
            "scheduled_at": "2026-07-01 09:00",
            "reason": "invalid_summary_or_scheduled_at",
        },
        {
            "id": "bad-time",
            "summary": "Example",
            "scheduled_at": "2026-07-01T09:00",
            "reason": "invalid_summary_or_scheduled_at",
        },
    ]


@pytest.mark.parametrize("limit", [True, False, 0, -1, 501, 1.5, "100"])
def test_select_list_backfill_actions_rejects_invalid_limits(limit: object) -> None:
    with pytest.raises(ValueError, match="limit"):
        select_list_backfill_actions([], date_from=None, date_to=None, limit=limit)  # type: ignore[arg-type]


def test_reminder_list_backfill_batch_is_frozen() -> None:
    batch = ReminderListBackfillBatch(
        actions=[],
        query_dates=(),
        invalid=[],
        total_eligible=0,
        remaining=0,
    )

    with pytest.raises((AttributeError, TypeError)):
        batch.remaining = 1  # type: ignore[misc]


def test_plan_list_backfill_matches_exact_title_and_minute() -> None:
    action = _action("exact", summary="Buy milk", scheduled_at="2026-07-01 09:00")
    apple_row = {
        "name": "Buy milk",
        "due_at": "2026-07-01 09:00",
        "list": "Tasks",
    }

    plan = plan_list_backfill([action], [apple_row])

    assert plan == {
        "candidates": [
            {
                "id": "exact",
                "summary": "Buy milk",
                "scheduled_at": "2026-07-01 09:00",
                "status": "pending",
                "current_reminder_list": None,
                "target_list": "Tasks",
                "match_type": "exact_title",
            }
        ],
        "missing": [],
        "ambiguous": [],
    }


def test_plan_list_backfill_matches_only_trailing_duplicate_date_normalization() -> None:
    action = _action(
        "normalized",
        summary="Buy milk, 2026-07-01 09:00",
        scheduled_at="2026-07-01 09:00",
    )
    apple_row = {
        "name": "Buy milk",
        "due_at": "2026-07-01 09:00",
        "list": "Inbox",
    }

    plan = plan_list_backfill([action], [apple_row])

    assert plan["candidates"][0]["match_type"] == "normalized_trailing_date"
    assert plan["candidates"][0]["target_list"] == "Inbox"


def test_plan_list_backfill_keeps_duplicate_rows_and_sorts_distinct_matched_lists() -> None:
    action = _action("duplicate", summary="Same", scheduled_at="2026-07-01 09:00")
    rows = [
        {"name": "Same", "due_at": "2026-07-01 09:00", "list": "Zulu"},
        {"name": "Same", "due_at": "2026-07-01 09:00", "list": "Alpha"},
    ]

    cross_list = plan_list_backfill([action], rows)
    same_list = plan_list_backfill([action], [{**row, "list": "Tasks"} for row in rows])

    assert cross_list["ambiguous"][0]["matches"] == 2
    assert cross_list["ambiguous"][0]["matched_lists"] == ["Alpha", "Zulu"]
    assert same_list["ambiguous"][0]["matches"] == 2
    assert same_list["ambiguous"][0]["matched_lists"] == ["Tasks"]


def test_plan_list_backfill_marks_all_actions_ambiguous_when_they_claim_one_row() -> None:
    actions = [
        _action("first", summary="Shared", scheduled_at="2026-07-01 09:00"),
        _action("second", summary="Shared", scheduled_at="2026-07-01 09:00"),
    ]
    rows = [{"name": "Shared", "due_at": "2026-07-01 09:00", "list": "Tasks"}]

    plan = plan_list_backfill(actions, rows)

    assert plan["candidates"] == []
    assert [item["id"] for item in plan["ambiguous"]] == ["first", "second"]
    assert [item["matches"] for item in plan["ambiguous"]] == [1, 1]


def test_plan_list_backfill_requires_equal_minutes() -> None:
    action = _action("different-minute", summary="Same", scheduled_at="2026-07-01 09:00")
    rows = [{"name": "Same", "due_at": "2026-07-01 09:01", "list": "Tasks"}]

    plan = plan_list_backfill([action], rows)

    assert plan["candidates"] == []
    assert plan["ambiguous"] == []
    assert plan["missing"] == [
        {
            "id": "different-minute",
            "summary": "Same",
            "scheduled_at": "2026-07-01 09:00",
            "status": "pending",
        }
    ]


@pytest.mark.parametrize("apple_name", ["buy milk", "Buy"])
def test_plan_list_backfill_does_not_casefold_or_substring_match(apple_name: str) -> None:
    action = _action("strict-title", summary="Buy milk", scheduled_at="2026-07-01 09:00")
    row = {"name": apple_name, "due_at": "2026-07-01 09:00", "list": "Tasks"}

    plan = plan_list_backfill([action], [row])

    assert plan["candidates"] == []
    assert [item["id"] for item in plan["missing"]] == ["strict-title"]


def test_plan_list_backfill_outputs_only_contract_fields_when_apple_rows_have_extras() -> None:
    actions = [
        _action("candidate", summary="Candidate", scheduled_at="2026-07-01 09:00"),
        _action("missing", summary="Missing", scheduled_at="2026-07-01 10:00"),
        _action("ambiguous", summary="Ambiguous", scheduled_at="2026-07-01 11:00"),
    ]
    rows = [
        {
            "name": "Candidate",
            "due_at": "2026-07-01 09:00",
            "list": "Tasks",
            "notes": "private candidate note",
            "other": {"secret": True},
        },
        {
            "name": "Missing",
            "due_at": "2026-07-01 10:01",
            "list": "Tasks",
            "notes": "private non-match note",
        },
        {
            "name": "Ambiguous",
            "due_at": "2026-07-01 11:00",
            "list": "Alpha",
            "notes": "private first note",
        },
        {
            "name": "Ambiguous",
            "due_at": "2026-07-01 11:00",
            "list": "Zulu",
            "notes": "private second note",
        },
    ]

    plan = plan_list_backfill(actions, rows)

    assert set(plan["candidates"][0]) == {
        "id",
        "summary",
        "scheduled_at",
        "status",
        "current_reminder_list",
        "target_list",
        "match_type",
    }
    assert set(plan["missing"][0]) == {"id", "summary", "scheduled_at", "status"}
    assert set(plan["ambiguous"][0]) == {
        "id",
        "summary",
        "scheduled_at",
        "status",
        "matched_lists",
        "matches",
    }


@pytest.mark.parametrize(
    "bad_minute",
    [
        " 2026-07-01 09:00",
        "2026-07-01 09:00 ",
        "2026-07-01 09:00junk",
        "2026-07-01 09:00:00",
        "2026-07-01 09:00+08:00",
        "2026-07-01T09:00",
        "2026-07-01 09:00Z",
    ],
)
def test_plan_list_backfill_rejects_noncanonical_action_and_apple_minutes(
    bad_minute: str,
) -> None:
    valid_action = _action("valid", summary="Same", scheduled_at="2026-07-01 09:00")
    bad_action = _action("bad", summary="Same", scheduled_at=bad_minute)
    valid_row = {"name": "Same", "due_at": "2026-07-01 09:00", "list": "Tasks"}
    bad_row = {"name": "Same", "due_at": bad_minute, "list": "Tasks"}

    bad_action_plan = plan_list_backfill([bad_action], [valid_row])
    bad_row_plan = plan_list_backfill([valid_action], [bad_row])

    assert [item["id"] for item in bad_action_plan["missing"]] == ["bad"]
    assert [item["id"] for item in bad_row_plan["missing"]] == ["valid"]
