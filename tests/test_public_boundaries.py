"""Public repository privacy and overlay boundary tests."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _tracked_text() -> str:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    chunks = []
    for name in result.stdout.splitlines():
        if name == "tests/test_public_boundaries.py":
            continue
        path = ROOT / name
        if path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".pdf"}:
            continue
        chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def test_public_tree_does_not_contain_private_values():
    text = _tracked_text()

    blocked = [
        "/Users/zeninexu/github/nudge-private",
        "docs/personal",
        "百度同步盘",
        "niaite-email",
        "王珊珊",
        "玛仕度肽",
        "训记",
        "TickTick",
    ]
    for snippet in blocked:
        assert snippet not in text


def test_public_readme_documents_private_overlay_without_private_values():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Using a Private Overlay" in readme
    assert "NUDGE_CONFIG=/path/to/private/config.toml" in readme
    assert "NUDGE_STATE_DIR=/path/to/private/state" in readme
    assert "bin/nudge doctor" in readme
    assert "bin/nudge mcp serve" in readme
    assert "bin/nudge agent status" in readme
