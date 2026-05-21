"""Apple Notes integration via AppleScript.

The Notes adapter intentionally keeps a narrow surface area:

- create notes in a named folder, creating the folder if needed;
- list visible folder names for diagnostics;
- list titles from the Nudge folder for MCP-safe discovery;
- do not read note bodies by default.
"""

from __future__ import annotations

import html
import re

from nudge.apple.common import escape, run_applescript
from nudge.config import DEFAULT_NOTES_FOLDER


MAX_NOTE_SUMMARY_LIMIT = 50
DEFAULT_NOTE_SUMMARY_LIMIT = 20
TITLE_SUMMARY_MAX_CHARS = 160


def list_note_folders(timeout: int = 5) -> tuple[bool, list[str] | str]:
    """Return visible Apple Notes folder names.

    This is read-only and intended for diagnostics. It does not read note
    bodies.
    """
    script = """set output to ""
tell application "Notes"
    repeat with acct in every account
        repeat with f in every folder of acct
            set output to output & (name of f) & "\\n"
        end repeat
    end repeat
end tell
output"""
    ok, raw = run_applescript(script, timeout=timeout)
    if not ok:
        return False, raw
    return True, [line.strip() for line in raw.splitlines() if line.strip()]


def list_nudge_note_summaries(
    *,
    limit: int = DEFAULT_NOTE_SUMMARY_LIMIT,
    folder_name: str = DEFAULT_NOTES_FOLDER,
    timeout: int = 10,
) -> tuple[bool, list[dict[str, str]] | str]:
    """Return note titles and title-derived summaries from the Nudge folder.

    This intentionally does not read note bodies. It only asks Notes for each
    note's name plus dates, then derives `summary` from the title.
    """
    safe_folder = escape(folder_name or DEFAULT_NOTES_FOLDER)
    bounded_limit = _bounded_limit(limit)
    script = f"""on sanitizeText(rawText)
    set oldDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to linefeed
    set textParts to text items of (rawText as text)
    set AppleScript's text item delimiters to " "
    set rawText to textParts as text
    set AppleScript's text item delimiters to tab
    set textParts to text items of (rawText as text)
    set AppleScript's text item delimiters to " "
    set rawText to textParts as text
    set AppleScript's text item delimiters to oldDelimiters
    return rawText
end sanitizeText

set targetFolderName to "{safe_folder}"
set maxItems to {bounded_limit}
set output to ""
tell application "Notes"
    repeat with acct in every account
        tell acct
            if exists folder targetFolderName then
                set targetFolder to folder targetFolderName
                set seenCount to 0
                repeat with noteItem in every note of targetFolder
                    if seenCount >= maxItems then exit repeat
                    set noteTitle to my sanitizeText(name of noteItem)
                    set createdText to ""
                    set modifiedText to ""
                    try
                        set createdText to my sanitizeText((creation date of noteItem) as text)
                    end try
                    try
                        set modifiedText to my sanitizeText((modification date of noteItem) as text)
                    end try
                    set output to output & noteTitle & tab & createdText & tab & modifiedText & linefeed
                    set seenCount to seenCount + 1
                end repeat
                return output
            end if
        end tell
    end repeat
end tell
output"""
    ok, raw = run_applescript(script, timeout=timeout)
    if not ok:
        return False, raw
    return True, _parse_note_summary_rows(raw)


def create_note(
    *,
    title: str,
    body: str,
    folder_name: str = DEFAULT_NOTES_FOLDER,
    timeout: int = 30,
) -> tuple[bool, str]:
    """Create one note in Apple Notes. Returns (success, title/error)."""
    safe_title = escape(title)
    safe_folder = escape(folder_name or DEFAULT_NOTES_FOLDER)
    note_body = _note_body_html(body)
    script = f"""tell application "Notes"
    launch
    set targetFolderName to "{safe_folder}"
    set targetAccount to account 1
    tell targetAccount
        if not (exists folder "{safe_folder}") then
            make new folder with properties {{name:targetFolderName}}
        end if
        set targetFolder to folder "{safe_folder}"
    end tell
    tell targetFolder
        set newNote to make new note with properties {{name:"{safe_title}", body:"{escape(note_body)}"}}
        name of newNote
    end tell
end tell"""
    return run_applescript(script, timeout=timeout)


def _bounded_limit(limit: int) -> int:
    """Clamp a user-provided note listing limit to the safe range."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = DEFAULT_NOTE_SUMMARY_LIMIT
    return max(1, min(value, MAX_NOTE_SUMMARY_LIMIT))


def _parse_note_summary_rows(raw: str) -> list[dict[str, str]]:
    """Parse TSV note metadata returned by AppleScript."""
    notes = []
    for line in str(raw or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        title = parts[0].strip() if parts else ""
        if not title:
            continue
        created_at = parts[1].strip() if len(parts) > 1 else ""
        modified_at = parts[2].strip() if len(parts) > 2 else ""
        notes.append({
            "title": title,
            "summary": _title_summary(title),
            "created_at": created_at,
            "modified_at": modified_at,
        })
    return notes


def _title_summary(title: str) -> str:
    """Build a safe summary from the title only."""
    clean = " ".join(str(title or "").split())
    if len(clean) <= TITLE_SUMMARY_MAX_CHARS:
        return clean
    return clean[: TITLE_SUMMARY_MAX_CHARS - 1] + "…"


def _note_body_html(body: str) -> str:
    """Render note body as simple human-readable HTML for Apple Notes.

    Apple Notes does not render Markdown syntax as Markdown. Nudge accepts
    Markdown-ish plan text as input, then normalizes common headings and lists
    into lightweight HTML so the created note reads like a native document
    instead of a pasted source file.
    """
    lines = str(body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    parts = [
        "<html>",
        (
            '<body style="font-family: -apple-system, BlinkMacSystemFont, '
            "Helvetica, Arial, sans-serif; font-size: 14px; line-height: 1.45;\">"
        ),
    ]
    paragraph: list[str] = []
    list_mode: str | None = None
    table_rows: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            parts.append(
                '<p style="margin: 0 0 10px 0;">'
                + " ".join(paragraph)
                + "</p>"
            )
            paragraph = []

    def close_list() -> None:
        nonlocal list_mode
        if list_mode:
            parts.append(f"</{list_mode}>")
            list_mode = None

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return

        rows = [
            _markdown_table_cells(row)
            for row in table_rows
            if not _is_markdown_table_separator(row)
        ]
        rows = [row for row in rows if row]
        if rows:
            parts.append(
                '<table style="border-collapse: collapse; margin: 0 0 12px 0; width: 100%;">'
            )
            for row_index, cells in enumerate(rows):
                parts.append("<tr>")
                cell_tag = "th" if row_index == 0 and len(rows) > 1 else "td"
                for cell in cells:
                    parts.append(
                        f'<{cell_tag} style="border: 1px solid #ddd; padding: 4px 6px; '
                        'text-align: left; vertical-align: top;">'
                        f"{_inline_note_html(cell)}"
                        f"</{cell_tag}>"
                    )
                parts.append("</tr>")
            parts.append("</table>")
        table_rows = []

    def ensure_list(mode: str) -> None:
        nonlocal list_mode
        if list_mode == mode:
            return
        close_list()
        parts.append(f'<{mode} style="margin: 0 0 10px 20px; padding: 0;">')
        list_mode = mode

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            close_list()
            flush_table()
            continue

        if re.match(r"^```", stripped):
            flush_paragraph()
            close_list()
            flush_table()
            continue

        if _is_markdown_table_row(stripped):
            flush_paragraph()
            close_list()
            table_rows.append(stripped)
            continue

        flush_table()

        heading = re.match(r"^(#{1,3})\s+(.+?)\s*$", stripped)
        if heading:
            flush_paragraph()
            close_list()
            level = min(len(heading.group(1)), 3)
            font_size = {1: 22, 2: 18, 3: 16}[level]
            margin = "0 0 12px 0" if level == 1 else "12px 0 8px 0"
            parts.append(
                f'<h{level} style="font-size: {font_size}px; margin: {margin};">'
                f"{_inline_note_html(heading.group(2))}"
                f"</h{level}>"
            )
            continue

        if re.match(r"^([-*_]\s*){3,}$", stripped):
            flush_paragraph()
            close_list()
            parts.append('<hr style="border: 0; border-top: 1px solid #ddd; margin: 12px 0;">')
            continue

        checkbox = re.match(r"^\s*[-*+]\s+\[([ xX])\]\s+(.+)$", line)
        if checkbox:
            flush_paragraph()
            ensure_list("ul")
            marker = "&#x2611; " if checkbox.group(1).lower() == "x" else "&#x2610; "
            parts.append(
                '<li style="margin: 0 0 6px 0;">'
                f"{marker}{_inline_note_html(checkbox.group(2))}"
                "</li>"
            )
            continue

        unordered = re.match(r"^\s*[-*+]\s+(.+)$", line)
        if unordered:
            flush_paragraph()
            ensure_list("ul")
            parts.append(
                '<li style="margin: 0 0 6px 0;">'
                f"{_inline_note_html(unordered.group(1))}"
                "</li>"
            )
            continue

        ordered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if ordered:
            flush_paragraph()
            ensure_list("ol")
            parts.append(
                '<li style="margin: 0 0 6px 0;">'
                f"{_inline_note_html(ordered.group(1))}"
                "</li>"
            )
            continue

        close_list()
        paragraph.append(_inline_note_html(stripped))

    flush_paragraph()
    close_list()
    flush_table()
    parts.extend(["</body>", "</html>"])
    return "".join(parts)


def _is_markdown_table_row(line: str) -> bool:
    """Return true when a line looks like a Markdown pipe table row."""
    stripped = str(line or "").strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _markdown_table_cells(row: str) -> list[str]:
    """Split one Markdown pipe table row into cells."""
    stripped = str(row or "").strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_markdown_table_separator(row: str) -> bool:
    """Return true for the `|---|---|` separator row in Markdown tables."""
    cells = _markdown_table_cells(row)
    return bool(cells) and all(
        re.match(r"^:?-{3,}:?$", cell.replace(" ", "")) for cell in cells
    )


def _inline_note_html(text: str) -> str:
    """Escape inline text and render a tiny Markdown-ish subset."""
    escaped = html.escape(str(text or "").strip())
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+?)`", r"<code>\1</code>", escaped)
    return escaped
