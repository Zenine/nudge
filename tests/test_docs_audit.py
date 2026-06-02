from pathlib import Path

from nudge.docs_audit import audit_docs


def test_docs_audit_ignores_vitepress_dependency_tree(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
    package_docs = tmp_path / "docs" / "node_modules" / "pkg"
    package_docs.mkdir(parents=True)
    (package_docs / "README.md").write_text("[broken](missing.md)\n", encoding="utf-8")

    report = audit_docs(tmp_path)

    assert report["ok"] is True
    assert report["summary"]["errors"] == 0
