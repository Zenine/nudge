"""Shared TSV parsing helpers for Apple adapter read paths."""


def parse_tsv_rows(
    raw: str,
    *,
    required_columns: tuple[str, ...],
    optional_columns: tuple[str, ...] = (),
) -> list[dict]:
    """Parse tab-separated rows, skipping blank and malformed short rows."""
    rows = []
    required_count = len(required_columns)
    column_names = required_columns + optional_columns
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < required_count:
            continue
        row = {column: parts[index] for index, column in enumerate(required_columns)}
        for index, column in enumerate(column_names[required_count:], start=required_count):
            if len(parts) > index and parts[index]:
                row[column] = parts[index]
        rows.append(row)
    return rows
