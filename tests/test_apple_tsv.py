from nudge.apple.tsv import parse_tsv_rows


def test_parse_tsv_rows_skips_blank_and_malformed_rows():
    raw = "\nstandup\t2026-06-07 09:00\t2026-06-07 09:30\tWork\textra\nmissing-start-only\n\t\t\n"

    rows = parse_tsv_rows(raw, required_columns=("summary", "start", "end", "calendar"))

    assert rows == [
        {
            "summary": "standup",
            "start": "2026-06-07 09:00",
            "end": "2026-06-07 09:30",
            "calendar": "Work",
        }
    ]


def test_parse_tsv_rows_maps_non_empty_optional_columns_only():
    raw = (
        "take meds\t08:00\tHealth\t2026-06-07 08:05\t2026-06-07 08:00\n"
        "water plants\t09:00\tHome\t\t2026-06-07 09:00\n"
        "too-short\t09:00\n"
    )

    rows = parse_tsv_rows(
        raw,
        required_columns=("name", "due_time", "list"),
        optional_columns=("completed_at", "due_at"),
    )

    assert rows == [
        {
            "name": "take meds",
            "due_time": "08:00",
            "list": "Health",
            "completed_at": "2026-06-07 08:05",
            "due_at": "2026-06-07 08:00",
        },
        {
            "name": "water plants",
            "due_time": "09:00",
            "list": "Home",
            "due_at": "2026-06-07 09:00",
        },
    ]
