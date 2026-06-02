#!/usr/bin/env python3
# Meridian template · llms-full.txt generator
"""Walk docs/**/*.md + top-level README.md, concatenate into llms-full.txt.

Output goes to BOTH:
  - <repo>/llms-full.txt       (repo-root copy; visible in GitHub tree)
  - <repo>/docs/public/llms-full.txt  (served at {SITE_URL}/llms-full.txt)

Strips YAML frontmatter and VitePress-specific components (::: blocks) so LLMs
get clean prose.

Usage:
  python3 scripts/generate-llms-full.py              # default: zh-CN only
  python3 scripts/generate-llms-full.py --all-langs  # include en/ja/zh-TW too
  python3 scripts/generate-llms-full.py --path /tmp/other  # custom root
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.S)
VITEPRESS_BLOCK_RE = re.compile(r"^:::[a-z]+.*?\n.*?^:::$", re.S | re.M)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def clean(text: str) -> str:
    text = FRONTMATTER_RE.sub("", text, count=1)
    text = VITEPRESS_BLOCK_RE.sub("", text)
    text = HTML_COMMENT_RE.sub("", text)
    return text.strip() + "\n"


def collect_docs(root: Path, all_langs: bool) -> list[Path]:
    docs: list[Path] = []
    # Always include the main README
    readme = root / "README.md"
    if readme.exists():
        docs.append(readme)
    # VitePress docs — zh-CN (default: only top-level .md in docs/)
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        for p in sorted(docs_dir.glob("*.md")):
            docs.append(p)
        if all_langs:
            for lang in ("en", "ja", "zh-TW"):
                lang_dir = docs_dir / lang
                if lang_dir.is_dir():
                    for p in sorted(lang_dir.glob("*.md")):
                        docs.append(p)
    return docs


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate llms-full.txt from docs + README")
    ap.add_argument("--path", default=".", help="project root (default: cwd)")
    ap.add_argument("--all-langs", action="store_true",
                    help="include en/ja/zh-TW docs (default: zh-CN only)")
    args = ap.parse_args()

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        sys.exit(2)

    docs = collect_docs(root, args.all_langs)
    if not docs:
        print("error: no source docs found (no README.md or docs/*.md)", file=sys.stderr)
        sys.exit(2)

    parts: list[str] = []
    for p in docs:
        rel = p.relative_to(root)
        parts.append(f"<!-- source: {rel} -->\n")
        parts.append(clean(p.read_text(encoding="utf-8")))
        parts.append("\n---\n\n")

    output = "".join(parts).rstrip() + "\n"

    out1 = root / "llms-full.txt"
    out2 = root / "docs" / "public" / "llms-full.txt"
    out1.write_text(output, encoding="utf-8")
    out2.parent.mkdir(parents=True, exist_ok=True)
    out2.write_text(output, encoding="utf-8")

    print(f"wrote {out1.relative_to(root)} ({len(output):,} chars, {len(docs)} source docs)")
    print(f"wrote {out2.relative_to(root)}")


if __name__ == "__main__":
    main()
