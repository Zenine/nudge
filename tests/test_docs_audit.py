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


def test_docs_audit_accepts_empty_todo_and_ignores_checkpoint_history(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
    (tmp_path / "TODO.md").write_text(
        "# TODO\n\n暂无待办。新增事项请按“可独立交付、可独立验证”的粒度补充。\n",
        encoding="utf-8",
    )
    (tmp_path / "checkpoint.md").write_text(
        "# Checkpoint\n\n"
        "## [阶段 1] 完成\n"
        "- 产出：`README.md`\n"
        "- 状态：✅\n",
        encoding="utf-8",
    )

    report = audit_docs(tmp_path)

    assert report["summary"]["warnings"] == 0
    assert not any(item["code"] == "DOCS_TODO_HISTORY" for item in report["warnings"])


def test_docs_audit_blocks_private_absolute_state_and_secret_paths(tmp_path: Path):
    private_config = "/Users/example/github/" + "nudge-private/config.toml"
    private_db = "/Users/example/.nudge/" + "nudge.db"
    fake_key = "sk-" + "test1234567890abcdef"
    (tmp_path / "README.md").write_text(
        "# Project\n\n"
        "Bad examples:\n\n"
        f"- `{private_config}`\n"
        f"- `{private_db}`\n"
        f"- `OPENAI_API_KEY={fake_key}`\n",
        encoding="utf-8",
    )

    report = audit_docs(tmp_path)

    assert report["ok"] is False
    codes = {item["code"] for item in report["errors"]}
    assert "DOCS_PRIVATE_ABSOLUTE_PATH" in codes
    assert "DOCS_SECRET_VALUE_EXAMPLE" in codes
