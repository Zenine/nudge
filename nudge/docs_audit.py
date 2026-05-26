"""Read-only documentation audit helpers."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse


ENTRYPOINTS = ("README.md", "README.zh-CN.md")
JUNK_FILENAMES = {".DS_Store", "Thumbs.db"}
TODO_HISTORY_MARKERS = ("[x]", "✅", "Done", "已完成")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def audit_docs(
    root: str | Path,
    *,
    today: date | None = None,
    stale_days: int = 30,
    max_entrypoint_lines: int = 500,
) -> dict:
    """Return a read-only documentation audit report."""
    root_path = Path(root)
    current_date = today or date.today()
    report = {
        "ok": True,
        "root": str(root_path),
        "summary": {"errors": 0, "warnings": 0, "suggestions": 0},
        "errors": [],
        "warnings": [],
        "suggestions": [],
    }

    _check_junk_files(root_path, report)
    _check_stale_superpowers(root_path, report, current_date, stale_days)
    _check_entrypoint_archive_links(root_path, report)
    _check_markdown_links(root_path, report)
    _check_todo_history(root_path, report)
    _check_long_entrypoints(root_path, report, max_entrypoint_lines)
    _finalize(report)
    return report


def _add(
    report: dict,
    level: str,
    code: str,
    message: str,
    path: Path | None = None,
    **extra,
) -> None:
    item = {"code": code, "message": message}
    if path is not None:
        item["path"] = str(path)
    item.update(extra)
    report[level].append(item)


def _check_junk_files(root: Path, report: dict) -> None:
    docs = root / "docs"
    if not docs.exists():
        return
    for path in docs.rglob("*"):
        if path.name in JUNK_FILENAMES:
            _add(
                report,
                "errors",
                "DOCS_JUNK_FILE",
                "文档目录包含系统垃圾文件。",
                path.relative_to(root),
            )


def _check_stale_superpowers(root: Path, report: dict, today: date, stale_days: int) -> None:
    for rel_dir, code, label in (
        (Path("docs/superpowers/plans"), "DOCS_STALE_PLAN", "实施计划"),
        (Path("docs/superpowers/specs"), "DOCS_ARCHIVE_CANDIDATE", "设计 spec"),
    ):
        base = root / rel_dir
        if not base.exists():
            continue
        for path in sorted(base.glob("*.md")):
            created = _date_from_filename(path.name)
            if created is None:
                continue
            age_days = (today - created).days
            if age_days > stale_days:
                _add(
                    report,
                    "warnings",
                    code,
                    f"{label}已超过 {stale_days} 天，建议评估是否归档。",
                    path.relative_to(root),
                    age_days=age_days,
                )


def _date_from_filename(name: str) -> date | None:
    match = re.match(r"(\d{4}-\d{2}-\d{2})-", name)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _check_entrypoint_archive_links(root: Path, report: dict) -> None:
    for entrypoint in ENTRYPOINTS:
        path = root / entrypoint
        if not path.exists():
            continue
        for target in _markdown_link_targets(path):
            if target.startswith("docs/archive/"):
                _add(
                    report,
                    "errors",
                    "DOCS_ARCHIVE_LINKED_FROM_ENTRYPOINT",
                    "README 入口不应直接链接归档文档。",
                    Path(entrypoint),
                    target=target,
                )


def _check_markdown_links(root: Path, report: dict) -> None:
    for path in _markdown_files(root):
        if _is_in_archive(root, path):
            continue
        for target in _markdown_link_targets(path):
            if _is_external_link(target) or target.startswith("#"):
                continue
            resolved = _resolve_markdown_link(path, target)
            if resolved is None:
                continue
            if not resolved.exists():
                _add(
                    report,
                    "errors",
                    "DOCS_BROKEN_LINK",
                    "Markdown 内部链接指向不存在的文件。",
                    path.relative_to(root),
                    target=target,
                )


def _check_todo_history(root: Path, report: dict) -> None:
    for rel_path in (Path("docs/TODO.md"), Path("TODO.md")):
        path = root / rel_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in TODO_HISTORY_MARKERS:
            if marker in text:
                _add(
                    report,
                    "warnings",
                    "DOCS_TODO_HISTORY",
                    "TODO 文档疑似包含已完成历史记录。",
                    rel_path,
                    marker=marker,
                )
                return


def _check_long_entrypoints(root: Path, report: dict, max_lines: int) -> None:
    for entrypoint in ENTRYPOINTS:
        path = root / entrypoint
        if not path.exists():
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > max_lines:
            _add(
                report,
                "suggestions",
                "DOCS_LONG_ENTRYPOINT",
                f"入口文档超过 {max_lines} 行，建议继续收敛。",
                Path(entrypoint),
                line_count=line_count,
            )


def _markdown_files(root: Path) -> list[Path]:
    candidates = [path for path in root.glob("*.md")]
    docs = root / "docs"
    if docs.exists():
        candidates.extend(docs.rglob("*.md"))
    return sorted(set(candidates))


def _is_in_archive(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return relative.parts[:2] == ("docs", "archive")


def _markdown_link_targets(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    text = _strip_fenced_code_blocks(text)
    return [match.strip() for match in MARKDOWN_LINK_RE.findall(text)]


def _strip_fenced_code_blocks(text: str) -> str:
    kept: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append(line)
    return "\n".join(kept)


def _is_external_link(target: str) -> bool:
    parsed = urlparse(target)
    return parsed.scheme in {"http", "https", "mailto"}


def _resolve_markdown_link(source: Path, target: str) -> Path | None:
    clean = unquote(target.split("#", 1)[0]).strip()
    if not clean:
        return None
    return (source.parent / clean).resolve()


def _finalize(report: dict) -> None:
    report["summary"] = {
        "errors": len(report["errors"]),
        "warnings": len(report["warnings"]),
        "suggestions": len(report["suggestions"]),
    }
    report["ok"] = report["summary"]["errors"] == 0
