"""Tests for Apple Notes integration through AppleScript."""

from nudge.apple.notes import (
    _note_body_html,
    create_note,
    list_note_folders,
    list_nudge_note_summaries,
)


def test_create_note_creates_target_folder_and_note(monkeypatch):
    captured = {}

    def fake_run(script, timeout=30):
        captured["script"] = script
        captured["timeout"] = timeout
        return True, "Nudge 计划"

    monkeypatch.setattr("nudge.apple.notes.run_applescript", fake_run)

    ok, message = create_note(
        title='Nudge "计划"',
        body="第一行\n第二行",
        folder_name="Nudge",
        timeout=9,
    )

    assert ok is True
    assert message == "Nudge 计划"
    assert captured["timeout"] == 9
    assert 'if not (exists folder "Nudge") then' in captured["script"]
    assert 'name:"Nudge \\"计划\\""' in captured["script"]
    assert "<pre" not in captured["script"]
    assert "-apple-system" in captured["script"]
    assert "第一行" in captured["script"]


def test_note_body_html_normalizes_markdownish_text_for_humans():
    html = _note_body_html(
        "# 周计划\n\n"
        "先看 **安全边界**。\n\n"
        "- [ ] 晨起称重\n"
        "- [x] 关机流程\n"
        "1. 生成 dry-run\n"
        "2. 确认写入\n"
    )

    assert "<h1" in html
    assert "周计划" in html
    assert "<strong>安全边界</strong>" in html
    assert "<ul" in html
    assert "&#x2610; 晨起称重" in html
    assert "&#x2611; 关机流程" in html
    assert "<ol" in html
    assert "生成 dry-run" in html
    assert "# 周计划" not in html
    assert "- [ ]" not in html


def test_note_body_html_removes_code_fences_and_renders_tables():
    html = _note_body_html(
        "## 每日主题\n\n"
        "| 日期 | 主题 |\n"
        "|---|---|\n"
        "| 2026-04-27 | 启动 |\n"
        "| 2026-04-28 | 输入稳定 |\n\n"
        "```text\n"
        "status=done / partial / skipped\n"
        "reason=too_hard / no_time\n"
        "```\n"
    )

    assert "<table" in html
    assert "<th" in html
    assert "<td" in html
    assert "2026-04-27" in html
    assert "status=done / partial / skipped" in html
    assert "```" not in html
    assert "| 日期 |" not in html
    assert "|---|---|" not in html


def test_list_note_folders_returns_visible_folder_names(monkeypatch):
    monkeypatch.setattr(
        "nudge.apple.notes.run_applescript",
        lambda script, timeout=5: (True, "Nudge\n健康\n"),
    )

    assert list_note_folders() == (True, ["Nudge", "健康"])


def test_list_nudge_note_summaries_reads_titles_without_bodies(monkeypatch):
    captured = {}

    def fake_run(script, timeout=10):
        captured["script"] = script
        captured["timeout"] = timeout
        return (
            True,
            "本周执行计划\t2026-04-26 09:00:00\t2026-04-26 09:30:00\n"
            "饮食清单\t\t2026-04-26 10:00:00\n",
        )

    monkeypatch.setattr("nudge.apple.notes.run_applescript", fake_run)

    ok, notes = list_nudge_note_summaries(limit=2, timeout=7)

    assert ok is True
    assert notes == [
        {
            "title": "本周执行计划",
            "summary": "本周执行计划",
            "created_at": "2026-04-26 09:00:00",
            "modified_at": "2026-04-26 09:30:00",
        },
        {
            "title": "饮食清单",
            "summary": "饮食清单",
            "created_at": "",
            "modified_at": "2026-04-26 10:00:00",
        },
    ]
    assert captured["timeout"] == 7
    assert 'targetFolderName to "Nudge"' in captured["script"]
    assert "maxItems to 2" in captured["script"]
    assert "body of" not in captured["script"].lower()
    assert "plaintext" not in captured["script"].lower()


def test_list_nudge_note_summaries_clamps_limit_and_returns_empty_for_missing_folder(monkeypatch):
    captured = {}

    def fake_run(script, timeout=10):
        captured["script"] = script
        return True, ""

    monkeypatch.setattr("nudge.apple.notes.run_applescript", fake_run)

    ok, notes = list_nudge_note_summaries(limit=500)

    assert ok is True
    assert notes == []
    assert "maxItems to 50" in captured["script"]
