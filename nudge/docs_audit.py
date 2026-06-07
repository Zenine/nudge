"""Read-only documentation audit helpers."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse


ENTRYPOINTS = ("README.md", "README_CN.md")
JUNK_FILENAMES = {".DS_Store", "Thumbs.db"}
IGNORED_DOCS_DIRS = {"node_modules", ".vitepress"}
TODO_HISTORY_MARKERS = ("[x]", "✅", "Done", "已完成")
DUPLICATE_HEADING_EXEMPT_FILES = {Path("CHANGELOG.md")}
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
PRIVATE_ABSOLUTE_PATH_RE = re.compile(
    r"/Users/[^\s`\"')]+/(?:"
    r"github/nudge-private(?:/[^\s`\"')]+)*|"
    r"Desktop/[^\s`\"')]*DB_backup(?:/[^\s`\"')]+)*|"
    r"\.nudge/[^\s`\"')]*nudge\.db|"
    r"github/nudge-public/\.nudge/[^\s`\"')]*nudge\.db"
    r")"
)
SECRET_VALUE_EXAMPLE_RE = re.compile(
    r"(?i)\b(?:[a-z0-9]+_)*(?:api[_-]?key|token|secret|password|credential)\b"
    r"\s*[:=]\s*(?:sk-[A-Za-z0-9_-]{12,}|[\"'](?:sk-[A-Za-z0-9_-]{12,}|[A-Za-z0-9_./+=-]{24,})[\"'])"
)
PUBLIC_BOUNDARY_TEXT_FILES = (
    Path("llms.txt"),
    Path("docs/public/llms.txt"),
    Path("llms-full.txt"),
    Path("docs/public/llms-full.txt"),
)


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
    _check_markdown_images(root_path, report)
    _check_duplicate_headings(root_path, report)
    _check_docs_index_alignment(root_path, report)
    _check_public_boundaries(root_path, report)
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
        if _is_ignored_docs_path(root, path):
            continue
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
            resolved = _resolve_markdown_link(path, target)
            if resolved is not None and _is_in_archive(root, resolved):
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
            if _is_external_link(target):
                continue
            resolved = _resolve_markdown_link(path, target) or path
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
                continue
            anchor = _anchor_from_target(target)
            if anchor and resolved.suffix.lower() == ".md" and not _has_anchor(resolved, anchor):
                _add(
                    report,
                    "errors",
                    "DOCS_BROKEN_ANCHOR",
                    "Markdown 内部链接指向不存在的标题锚点。",
                    path.relative_to(root),
                    target=target,
                )


def _check_markdown_images(root: Path, report: dict) -> None:
    for path in _markdown_files(root):
        if _is_in_archive(root, path):
            continue
        for target in _markdown_image_targets(path):
            if _is_external_link(target):
                continue
            resolved = _resolve_markdown_link(path, target)
            if resolved is None:
                continue
            if not resolved.exists():
                _add(
                    report,
                    "errors",
                    "DOCS_BROKEN_IMAGE",
                    "Markdown 图片链接指向不存在的资源。",
                    path.relative_to(root),
                    target=target,
                )


def _check_duplicate_headings(root: Path, report: dict) -> None:
    for path in _markdown_files(root):
        if _is_in_archive(root, path) or _is_duplicate_heading_exempt(root, path):
            continue
        slugs: set[str] = set()
        for heading in _heading_slugs(path):
            if heading in slugs:
                _add(
                    report,
                    "warnings",
                    "DOCS_DUPLICATE_HEADING",
                    "Markdown 文件包含生成相同 slug 的重复标题。",
                    path.relative_to(root),
                    slug=heading,
                )
                break
            slugs.add(heading)


def _check_docs_index_alignment(root: Path, report: dict) -> None:
    docs_readme = root / "docs" / "README.md"
    if not docs_readme.exists():
        return

    docs_targets = _public_doc_targets(root, docs_readme)
    docs_targets.discard("docs/README.md")
    for entrypoint in ENTRYPOINTS:
        readme = root / entrypoint
        if not readme.exists():
            continue
        readme_targets = _public_doc_targets(root, readme)
        readme_targets.discard("docs/README.md")
        if readme_targets != docs_targets:
            _add(
                report,
                "suggestions",
                "DOCS_INDEX_MISMATCH",
                f"{entrypoint} 与 docs/README.md 的 docs target 列表不一致。",
                Path(entrypoint),
                missing_from_readme=sorted(docs_targets - readme_targets),
                missing_from_docs_readme=sorted(readme_targets - docs_targets),
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


def _check_public_boundaries(root: Path, report: dict) -> None:
    for path in _public_boundary_files(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        relative = path.relative_to(root)
        if PRIVATE_ABSOLUTE_PATH_RE.search(text):
            _add(
                report,
                "errors",
                "DOCS_PRIVATE_ABSOLUTE_PATH",
                "公开文档包含私有绝对路径或个人状态库路径。",
                relative,
            )
        if SECRET_VALUE_EXAMPLE_RE.search(text):
            _add(
                report,
                "errors",
                "DOCS_SECRET_VALUE_EXAMPLE",
                "公开文档包含真实形态的密钥、token 或密码示例。",
                relative,
            )


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
        candidates.extend(
            path for path in docs.rglob("*.md")
            if not _is_ignored_docs_path(root, path)
        )
    return sorted(set(candidates))


def _public_boundary_files(root: Path) -> list[Path]:
    candidates = _markdown_files(root)
    for rel_path in PUBLIC_BOUNDARY_TEXT_FILES:
        path = root / rel_path
        if path.exists():
            candidates.append(path)
    return sorted(set(candidates))


def _is_ignored_docs_path(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return relative.parts[:1] == ("docs",) and any(
        part in IGNORED_DOCS_DIRS for part in relative.parts[1:]
    )


def _is_in_archive(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return relative.parts[:1] == ("docs",) and "archive" in relative.parts


def _is_duplicate_heading_exempt(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return relative in DUPLICATE_HEADING_EXEMPT_FILES


def _markdown_link_targets(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    text = _strip_fenced_code_blocks(text)
    return [match.strip() for match in MARKDOWN_LINK_RE.findall(text)]


def _markdown_image_targets(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    text = _strip_fenced_code_blocks(text)
    return [match.strip() for match in MARKDOWN_IMAGE_RE.findall(text)]


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


def _anchor_from_target(target: str) -> str | None:
    if "#" not in target:
        return None
    anchor = target.split("#", 1)[1].strip()
    return unquote(anchor) or None


def _has_anchor(path: Path, anchor: str) -> bool:
    return _github_heading_slug(anchor) in set(_heading_slugs(path))


def _heading_slugs(path: Path) -> list[str]:
    text = _strip_fenced_code_blocks(path.read_text(encoding="utf-8"))
    return [_github_heading_slug(match.group(2)) for match in MARKDOWN_HEADING_RE.finditer(text)]


def _github_heading_slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.strip().lower()
    text = "".join(char for char in text if char.isalnum() or char.isspace() or char == "-")
    return re.sub(r"-+", "-", re.sub(r"\s+", "-", text)).strip("-")


def _public_doc_targets(root: Path, path: Path) -> set[str]:
    targets: set[str] = set()
    for target in _markdown_link_targets(path):
        if _is_external_link(target):
            continue
        resolved = _resolve_markdown_link(path, target)
        if resolved is None or resolved.suffix.lower() != ".md":
            continue
        try:
            relative = resolved.relative_to(root.resolve())
        except ValueError:
            continue
        if relative.parts[:1] == ("docs",) and not _is_in_archive(root, resolved):
            targets.add(relative.as_posix())
    return targets


def _finalize(report: dict) -> None:
    report["summary"] = {
        "errors": len(report["errors"]),
        "warnings": len(report["warnings"]),
        "suggestions": len(report["suggestions"]),
    }
    report["ok"] = report["summary"]["errors"] == 0
