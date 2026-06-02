#!/usr/bin/env python3
# Meridian template v3.2 · i18n drift detector
"""Multi-language drift detector for Meridian-operated projects.

Runs at repo root (or pass --path). Performs six checks:

  1. Structure parity    — H1/H2 count & level sequence across lang versions
  2. Translation header  — required `<!-- Translation status ... -->` block present
  3. Language switcher   — `> **语言 / Language**: ...` line present, current lang bolded
  4. Source freshness    — git log diff between recorded `Source commit` and current HEAD
  5. Glossary coverage   — every base H2 has a row in i18n/glossary.md section C,
                           and each translation's H2 matches glossary's recorded rendering
  6. Placeholder residue — no unreplaced `{{VAR}}` tokens in produced files

Exit 0 on clean, 1 on errors. --strict also fails on warnings.

Usage:
    python3 scripts/check-i18n-drift.py                 # cwd as root
    python3 scripts/check-i18n-drift.py --path /tmp/foo  # custom root
    python3 scripts/check-i18n-drift.py --strict        # warnings → errors

Python 3.8+ stdlib only. No deps.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_BASE_LANG: str = "zh-CN"
DEFAULT_TARGET_LANGS: Tuple[str, ...] = ("en", "ja", "zh-TW")
LANG_LABELS: Dict[str, str] = {
    "en": "English",
    "ja": "日本語",
    "zh": "简体中文",
    "zh-TW": "繁體中文",
    "zh-CN": "简体中文",
}

# ---------- ANSI colors (only if TTY) ----------

def _c(s: str, code: str) -> str:
    if not sys.stdout.isatty():
        return s
    return f"\033[{code}m{s}\033[0m"

def red(s):    return _c(s, "31")
def green(s):  return _c(s, "32")
def yellow(s): return _c(s, "33")
def dim(s):    return _c(s, "2")
def bold(s):   return _c(s, "1")

# ---------- IO helpers ----------

def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""

# ---------- Parsers ----------

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)

def extract_headings(content: str) -> List[Tuple[int, str]]:
    """Return [(level, text), ...]; strips fenced code blocks & HTML comments first."""
    stripped = re.sub(r"^```[\s\S]*?^```", "", content, flags=re.M)
    stripped = re.sub(r"<!--[\s\S]*?-->", "", stripped)
    return [(len(m.group(1)), m.group(2).strip()) for m in HEADING_RE.finditer(stripped)]

HEADER_RE = re.compile(
    r"<!--\s*Translation status:\s*"
    r"Source file\s*:\s*(?P<source_file>.+?)\s*"
    r"Source commit\s*:\s*(?P<source_commit>.+?)\s*"
    r"Translated\s*:\s*(?P<translated>.+?)\s*"
    r"Status\s*:\s*(?P<status>.+?)\s*-->",
    re.S,
)

def parse_translation_header(content: str) -> Optional[Dict[str, str]]:
    m = HEADER_RE.search(content)
    if not m:
        return None
    return {k: v.strip() for k, v in m.groupdict().items()}

SWITCHER_RE = re.compile(
    r"\*\*\s*(?:[语語]言\s*/\s*)?Language\s*\*\*\s*[：:]\s*(.+)"
)

def parse_switcher(content: str) -> Tuple[Optional[set], Optional[set]]:
    m = SWITCHER_RE.search(content)
    if not m:
        return None, None
    line = m.group(1)
    linked = set(re.findall(r"\[([^\]]+)\]\([^)]+\)", line))
    bolded = set(re.findall(r"\*\*([^*]+)\*\*", line))
    return linked | bolded, bolded

# ---------- File discovery ----------

def find_readme_group(
    root: Path, base_lang: str, target_langs: Tuple[str, ...]
) -> Optional[Dict[str, Optional[Path]]]:
    # README.md is always the source (base), regardless of --base-lang label.
    # --base-lang only affects the label displayed and glossary column naming.
    base = root / "README.md"
    if not base.exists():
        return None
    group: Dict[str, Optional[Path]] = {base_lang: base}
    for code in target_langs:
        p = root / f"README.{code}.md"
        group[code] = p if p.exists() else None
    return group

def find_docs_groups(
    root: Path, base_lang: str, target_langs: Tuple[str, ...]
) -> List[Dict[str, Optional[Path]]]:
    docs = root / "docs"
    if not docs.is_dir():
        return []
    groups: List[Dict[str, Optional[Path]]] = []
    for p in sorted(docs.glob("*.md")):
        g: Dict[str, Optional[Path]] = {base_lang: p}
        for code in target_langs:
            tp = docs / code / p.name
            g[code] = tp if tp.exists() else None
        groups.append(g)
    return groups

# ---------- Report aggregator ----------

class Report:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

# ---------- Checks ----------

def check_structure(
    group: Dict[str, Optional[Path]], base_lang: str, target_langs: Tuple[str, ...],
    root: Path, report: Report,
) -> None:
    base = group.get(base_lang)
    if not base:
        return
    base_h = [(l, t) for l, t in extract_headings(read(base)) if l <= 2]
    base_name = str(base.relative_to(root))
    for code in target_langs:
        p = group.get(code)
        if not p:
            report.err(f"{base_name}: missing {code} translation")
            continue
        t_h = [(l, t) for l, t in extract_headings(read(p)) if l <= 2]
        rel = str(p.relative_to(root))
        if len(base_h) != len(t_h):
            report.err(
                f"{rel}: H1+H2 count mismatch (base={len(base_h)}, {code}={len(t_h)})"
            )
        if [l for l, _ in base_h] != [l for l, _ in t_h]:
            report.err(f"{rel}: H1/H2 level sequence diverges from base")

def check_translation_header(
    group: Dict[str, Optional[Path]], target_langs: Tuple[str, ...],
    root: Path, report: Report,
) -> None:
    for code in target_langs:
        p = group.get(code)
        if not p:
            continue
        rel = str(p.relative_to(root))
        hdr = parse_translation_header(read(p))
        if not hdr:
            report.err(f"{rel}: missing/malformed translation status comment block")
            continue
        if hdr["status"].lower() not in {"up-to-date", "stale", "in-progress"}:
            report.warn(f"{rel}: unknown Status '{hdr['status']}'")

def check_switcher(group: Dict[str, Optional[Path]], root: Path, report: Report) -> None:
    for _lang, p in group.items():
        if not p:
            continue
        rel = str(p.relative_to(root))
        # VitePress docs/ files rely on the built-in locale dropdown; skip markdown switcher check
        if rel.startswith("docs/") or rel.startswith("docs\\"):
            continue
        langs, bolded = parse_switcher(read(p))
        if langs is None:
            report.warn(f"{rel}: no '语言 / Language' switcher line found")
            continue
        if len(langs) < 4:
            report.warn(f"{rel}: switcher lists {len(langs)} langs, expected 4")
        if not bolded:
            report.warn(f"{rel}: no current language bolded in switcher")

def _git_commits_since(root: Path, rel: str, since: str) -> Optional[List[str]]:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "log", f"{since}..HEAD", "--oneline", "--", rel],
            stderr=subprocess.DEVNULL,
        ).decode()
        return [line.split()[0] for line in out.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

_HASH_RE = re.compile(r"^[0-9a-f]{6,40}$")

def check_source_freshness(
    group: Dict[str, Optional[Path]], base_lang: str, target_langs: Tuple[str, ...],
    root: Path, report: Report,
) -> None:
    base = group.get(base_lang)
    if not base:
        return
    base_rel = str(base.relative_to(root))
    for code in target_langs:
        p = group.get(code)
        if not p:
            continue
        rel = str(p.relative_to(root))
        hdr = parse_translation_header(read(p))
        if not hdr:
            continue
        commit = hdr["source_commit"]
        if commit.startswith("(") or not _HASH_RE.match(commit):
            report.warn(f"{rel}: Source commit '{commit}' is not a resolvable hash")
            continue
        diffs = _git_commits_since(root, base_rel, commit)
        if diffs is None:
            report.warn(f"{rel}: git log failed (commit '{commit[:7]}' may not exist)")
            continue
        if diffs:
            report.err(
                f"{rel}: STALE — base has {len(diffs)} new commits since '{commit[:7]}'"
            )

GLOSS_SECTION_RE = re.compile(
    r"^##\s+C\.\s+(?:UI\s+标签|Section\s+Headings).*?\n(?P<body>.+?)(?=^##|\Z)",
    re.S | re.M,
)
GLOSS_ROW_RE = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
    re.M,
)

def load_glossary_c_section(
    root: Path, target_langs: Tuple[str, ...]
) -> Optional[Dict[str, Dict[str, str]]]:
    """Parse glossary C section. Column order: base, then target_langs (in given order)."""
    gp = root / "i18n" / "glossary.md"
    if not gp.exists():
        return None
    content = read(gp)
    m = GLOSS_SECTION_RE.search(content)
    if not m:
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for cols in GLOSS_ROW_RE.findall(m.group("body")):
        base_term = cols[0].strip()
        if not base_term or base_term.startswith("-") or "简体中文" in base_term or base_term.lower() in {"english (source)", "source"}:
            continue
        row: Dict[str, str] = {}
        for i, code in enumerate(target_langs, start=1):
            if i < len(cols):
                row[code] = cols[i].strip()
        out[base_term] = row
    return out

def check_glossary_coverage(
    group: Dict[str, Optional[Path]],
    glossary: Optional[Dict[str, Dict[str, str]]],
    base_lang: str,
    target_langs: Tuple[str, ...],
    root: Path,
    report: Report,
) -> None:
    if glossary is None or not glossary:
        return
    base = group.get(base_lang)
    if not base:
        return
    base_name = str(base.relative_to(root))
    base_h2 = [t for l, t in extract_headings(read(base)) if l == 2]
    # Report uncovered base H2 once per file (not once per target language)
    for zh in base_h2:
        if zh not in glossary:
            report.warn(f"{base_name}: H2 '{zh}' not in glossary C section")
    for code in target_langs:
        p = group.get(code)
        if not p:
            continue
        rel = str(p.relative_to(root))
        t_h2 = [t for l, t in extract_headings(read(p)) if l == 2]
        for i, zh in enumerate(base_h2):
            if i >= len(t_h2):
                break
            recorded = glossary.get(zh)
            if not recorded:
                continue
            expected = recorded.get(code, "")
            if expected and expected != t_h2[i]:
                report.err(
                    f"{rel}: H2 '{t_h2[i]}' != glossary '{expected}' (for zh='{zh}')"
                )

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Z_][A-Z0-9_]*)\s*\}\}")

def check_placeholder_residue(paths: List[Path], root: Path, report: Report) -> None:
    for p in paths:
        if not p or not p.exists():
            continue
        content = read(p)
        stripped = re.sub(r"^```[\s\S]*?^```", "", content, flags=re.M)
        stripped = re.sub(r"`[^`]+`", "", stripped)
        found = PLACEHOLDER_RE.findall(stripped)
        if found:
            rel = str(p.relative_to(root))
            uniq = sorted(set(found))
            report.err(f"{rel}: unreplaced placeholders: " + ", ".join("{{" + v + "}}" for v in uniq))

# ---------- Main ----------

def main() -> None:
    ap = argparse.ArgumentParser(description="i18n drift detector (Meridian)")
    ap.add_argument("--path", default=".", help="project root (default: cwd)")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument("--quiet", action="store_true", help="suppress per-group file listing")
    ap.add_argument(
        "--base-lang", default=DEFAULT_BASE_LANG,
        help=f"source language code (default: {DEFAULT_BASE_LANG})",
    )
    ap.add_argument(
        "--target-langs", default=",".join(DEFAULT_TARGET_LANGS),
        help=f"comma-separated target language codes (default: {','.join(DEFAULT_TARGET_LANGS)})",
    )
    args = ap.parse_args()

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(red(f"error: {root} is not a directory"))
        sys.exit(2)

    base_lang: str = args.base_lang
    target_langs: Tuple[str, ...] = tuple(
        c.strip() for c in args.target_langs.split(",") if c.strip()
    )

    report = Report()
    tracked_files: List[Path] = []

    readme_group = find_readme_group(root, base_lang, target_langs)
    if readme_group:
        if not args.quiet:
            print(bold("README group:"))
            for lang, p in readme_group.items():
                mark = str(p.relative_to(root)) if p else dim("<missing>")
                print(f"  {lang:<6} {mark}")
        for p in readme_group.values():
            if p:
                tracked_files.append(p)
        check_structure(readme_group, base_lang, target_langs, root, report)
        check_translation_header(readme_group, target_langs, root, report)
        check_switcher(readme_group, root, report)
        check_source_freshness(readme_group, base_lang, target_langs, root, report)

    docs_groups = find_docs_groups(root, base_lang, target_langs)
    for g in docs_groups:
        if not args.quiet:
            print(bold(f"\nDocs group: {g[base_lang].name}"))
            for lang, p in g.items():
                mark = str(p.relative_to(root)) if p else dim("<missing>")
                print(f"  {lang:<6} {mark}")
        for p in g.values():
            if p:
                tracked_files.append(p)
        check_structure(g, base_lang, target_langs, root, report)
        check_translation_header(g, target_langs, root, report)
        check_switcher(g, root, report)
        check_source_freshness(g, base_lang, target_langs, root, report)

    glossary = load_glossary_c_section(root, target_langs)
    glossary_path = root / "i18n" / "glossary.md"
    if glossary is None:
        report.warn("i18n/glossary.md not found — glossary coverage check skipped")
    else:
        if readme_group:
            check_glossary_coverage(readme_group, glossary, base_lang, target_langs, root, report)
        for g in docs_groups:
            check_glossary_coverage(g, glossary, base_lang, target_langs, root, report)
        if glossary_path.exists():
            tracked_files.append(glossary_path)

    check_placeholder_residue(tracked_files, root, report)

    print()
    if report.errors:
        print(red(bold(f"[FAIL] {len(report.errors)} error(s):")))
        for e in report.errors:
            print(red(f"  - {e}"))
    if report.warnings:
        print(yellow(bold(f"[WARN] {len(report.warnings)} warning(s):")))
        for w in report.warnings:
            print(yellow(f"  - {w}"))
    if not report.errors and not report.warnings:
        print(green(bold("[PASS] no drift detected")))

    fail = bool(report.errors) or (args.strict and bool(report.warnings))
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
