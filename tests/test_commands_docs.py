from __future__ import annotations

import json

from click.testing import CliRunner

from nudge.cli import cli


def test_docs_audit_json_uses_versioned_payload(monkeypatch):
    monkeypatch.setattr(
        "nudge.commands.docs.audit_docs",
        lambda *args, **kwargs: {
            "ok": False,
            "root": "/repo",
            "summary": {"errors": 1, "warnings": 0, "suggestions": 0},
            "errors": [{"code": "DOCS_JUNK_FILE", "message": "junk", "path": "docs/.DS_Store"}],
            "warnings": [],
            "suggestions": [],
        },
    )

    result = CliRunner().invoke(cli, ["docs", "audit", "--json"], prog_name="nudge")

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["schema_version"] == "nudge.cli.v1"
    assert payload["ok"] is False
    assert payload["report"]["summary"]["errors"] == 1


def test_docs_audit_text_renders_summary(monkeypatch):
    monkeypatch.setattr(
        "nudge.commands.docs.audit_docs",
        lambda *args, **kwargs: {
            "ok": True,
            "root": "/repo",
            "summary": {"errors": 0, "warnings": 1, "suggestions": 0},
            "errors": [],
            "warnings": [{"code": "DOCS_STALE_PLAN", "message": "old", "path": "docs/superpowers/plans/x.md"}],
            "suggestions": [],
        },
    )

    result = CliRunner().invoke(cli, ["docs", "audit"], prog_name="nudge")

    assert result.exit_code == 0
    assert "Docs audit" in result.output
    assert "warnings=1" in result.output
    assert "DOCS_STALE_PLAN" in result.output


def test_docs_help_is_registered():
    result = CliRunner().invoke(cli, ["docs", "--help"], prog_name="nudge")

    assert result.exit_code == 0
    assert "audit" in result.output
