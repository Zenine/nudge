import json
import os
from pathlib import Path

from click.testing import CliRunner

from nudge.cli import cli
from nudge.commands.doctor import CheckResult


REFERENCE_DOCS = [
    Path("docs/reference.md"),
    Path("docs/en/reference.md"),
    Path("docs/ja/reference.md"),
    Path("docs/zh-TW/reference.md"),
]

README_DOCS = [
    Path("README.md"),
    Path("README.en.md"),
    Path("README.ja.md"),
    Path("README.zh-TW.md"),
]

SAFE_SMOKE_COMMANDS = [
    "bin/nudge --help",
    "bin/nudge doctor --help",
    "bin/nudge doctor --json",
    "bin/nudge skills list --json",
    "bin/nudge skills show deep-work-weekly-rhythm --json",
    "bin/nudge skills validate deep-work-weekly-rhythm --json",
    "bin/nudge skills apply deep-work-weekly-rhythm --context \"$tmpdir/context.json\" --json",
    "bin/nudge skills dry-run deep-work-weekly-rhythm --context \"$tmpdir/context.json\" --weeks 1 --json",
    "bin/nudge docs audit --json",
]


def _invoke(args: list[str], *, env: dict[str, str] | None = None):
    runner = CliRunner()
    return runner.invoke(cli, args, prog_name="nudge", env=env)


def _json_result(args: list[str], *, env: dict[str, str] | None = None) -> dict:
    result = _invoke(args, env=env)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _write_context(tmp_path: Path) -> Path:
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "assessment": {"morning_energy": True, "meetings_load": "high"},
                "history": {"distraction_avg_7d": 6},
                "profile": {
                    "preferred_days": ["Monday", "Wednesday", "Friday"],
                    "preferred_time": "08:30",
                    "start_date": "2026-06-01",
                },
            }
        ),
        encoding="utf-8",
    )
    return context


def test_reference_docs_explicitly_mark_public_safe_smoke_commands():
    for doc in REFERENCE_DOCS:
        text = doc.read_text(encoding="utf-8")
        assert "Public safe smoke" in text or "公开仓安全 smoke" in text, doc
        for command in SAFE_SMOKE_COMMANDS:
            assert command in text, f"missing {command!r} from {doc}"


def test_public_safe_smoke_commands_execute_without_user_home_or_apple_writes(
    monkeypatch,
    tmp_path,
):
    real_home = Path.home()
    sandbox_home = tmp_path / "home"
    sandbox_home.mkdir()
    env = {
        "HOME": str(sandbox_home),
        "NUDGE_STATE_DIR": str(tmp_path / "state"),
    }
    context = _write_context(tmp_path)

    monkeypatch.setattr(
        "nudge.commands.doctor.run_checks",
        lambda config_path=None, config=None, *, llm_ping=False: [
            CheckResult("PASS", "Config", "public smoke config"),
            CheckResult("WARN", "Calendar", "Apple read skipped in docs smoke"),
        ],
    )
    monkeypatch.setattr("nudge.commands.doctor.load_config", lambda config_path=None: {})
    monkeypatch.setattr("nudge.commands.doctor.log_doctor_checks", lambda checks, config=None: None)

    help_result = _invoke(["--help"], env=env)
    assert help_result.exit_code == 0, help_result.output

    doctor_help = _invoke(["doctor", "--help"], env=env)
    assert doctor_help.exit_code == 0, doctor_help.output
    assert "--llm-ping" in doctor_help.output

    doctor_payload = _json_result(["doctor", "--json"], env=env)
    assert doctor_payload["ok"] is True
    assert doctor_payload["checks"][0]["name"] == "Config"

    list_payload = _json_result(["skills", "list", "--json"], env=env)
    assert any(skill["id"] == "deep-work-weekly-rhythm" for skill in list_payload["skills"])

    show_payload = _json_result(["skills", "show", "deep-work-weekly-rhythm", "--json"], env=env)
    assert show_payload["skill"]["metadata"]["id"] == "deep-work-weekly-rhythm"

    validate_payload = _json_result(["skills", "validate", "deep-work-weekly-rhythm", "--json"], env=env)
    assert validate_payload["ok"] is True

    apply_payload = _json_result(
        ["skills", "apply", "deep-work-weekly-rhythm", "--context", str(context), "--json"],
        env=env,
    )
    assert apply_payload["personalization_applied"] == ["heavy_meeting_week", "morning_focus"]

    dry_run_payload = _json_result(
        [
            "skills",
            "dry-run",
            "deep-work-weekly-rhythm",
            "--context",
            str(context),
            "--weeks",
            "1",
            "--json",
        ],
        env=env,
    )
    assert dry_run_payload["dry_run"] is True
    assert {action["type"] for action in dry_run_payload["actions"]} == {"calendar_event"}

    docs_audit_payload = _json_result(["docs", "audit", "--json"], env=env)
    assert "report" in docs_audit_payload

    assert not (real_home / ".nudge" / "skills").exists()


def test_docs_mark_private_overlay_or_write_examples_as_not_direct_smoke():
    write_or_private_examples = [
        "nudge \"Project sync tomorrow at 3pm\"",
        "nudge daily sync --apply --json",
        "nudge review weekly --adapt --apply",
        "nudge agent apply --file request.json --config /path/to/private/config.toml --json",
        "nudge agent status --file status.json --config /path/to/private/config.toml --json",
        "nudge daemon enqueue --type agent.apply --file request.json --json",
        "nudge health import export.zip --apply --json",
        "nudge habits --config /path/to/private/config.toml log reading",
        "scripts/bootstrap_launchd.sh",
    ]
    guard_words = [
        "不要直接执行",
        "do not run directly",
        "直接執行しない",
        "不要直接執行",
        "private overlay",
        "dry-run",
    ]

    for doc in [*REFERENCE_DOCS, *README_DOCS]:
        text = doc.read_text(encoding="utf-8")
        for example in write_or_private_examples:
            if example not in text:
                continue
            index = text.index(example)
            window = text[max(0, index - 500): index + len(example) + 500]
            assert any(word in window for word in guard_words), (
                f"{doc} must mark {example!r} as private/write-only or not direct smoke"
            )
