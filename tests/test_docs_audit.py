from __future__ import annotations

from datetime import date
from pathlib import Path

from nudge.docs_audit import audit_docs


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def codes(report: dict, level: str) -> list[str]:
    return [item["code"] for item in report[level]]


def test_audit_reports_junk_file_and_stale_plan(tmp_path):
    write(tmp_path / "README.md", "# Root\n")
    write(tmp_path / "docs" / ".DS_Store", "junk")
    write(tmp_path / "docs" / "superpowers" / "plans" / "2026-04-01-old-plan.md", "# Old plan\n")

    report = audit_docs(tmp_path, today=date(2026, 5, 26), stale_days=30)

    assert "DOCS_JUNK_FILE" in codes(report, "errors")
    assert "DOCS_STALE_PLAN" in codes(report, "warnings")


def test_audit_reports_entrypoint_links_to_archive(tmp_path):
    write(tmp_path / "README.md", "[old](docs/archive/old.md)\n")
    write(tmp_path / "docs" / "archive" / "old.md", "# Old\n")

    report = audit_docs(tmp_path, today=date(2026, 5, 26))

    assert "DOCS_ARCHIVE_LINKED_FROM_ENTRYPOINT" in codes(report, "errors")


def test_audit_reports_broken_markdown_link(tmp_path):
    write(tmp_path / "README.md", "[missing](docs/missing.md)\n")

    report = audit_docs(tmp_path, today=date(2026, 5, 26))

    assert "DOCS_BROKEN_LINK" in codes(report, "errors")


def test_audit_ignores_broken_links_inside_archive(tmp_path):
    write(tmp_path / "docs" / "archive" / "old.md", "[old missing](missing.md)\n")

    report = audit_docs(tmp_path, today=date(2026, 5, 26))

    assert "DOCS_BROKEN_LINK" not in codes(report, "errors")


def test_audit_ignores_markdown_links_inside_fenced_code_blocks(tmp_path):
    write(
        tmp_path / "README.md",
        """# Root

```markdown
[example](docs/missing.md)
```
""",
    )

    report = audit_docs(tmp_path, today=date(2026, 5, 26))

    assert "DOCS_BROKEN_LINK" not in codes(report, "errors")


def test_audit_suggests_long_entrypoint(tmp_path):
    write(tmp_path / "README.md", "\n".join(f"line {i}" for i in range(121)))

    report = audit_docs(tmp_path, today=date(2026, 5, 26), max_entrypoint_lines=120)

    assert "DOCS_LONG_ENTRYPOINT" in codes(report, "suggestions")


def test_audit_reports_todo_history_markers(tmp_path):
    write(tmp_path / "docs" / "TODO.md", "# TODO\n\n已完成：旧事项\n")

    report = audit_docs(tmp_path, today=date(2026, 5, 26))

    assert "DOCS_TODO_HISTORY" in codes(report, "warnings")


def test_public_docs_have_no_broken_links():
    root = Path(__file__).resolve().parents[1]

    report = audit_docs(root, today=date(2026, 5, 26))

    assert [item for item in report["errors"] if item["code"] == "DOCS_BROKEN_LINK"] == []
