from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_verify_script_runs_docs_build_and_i18n_drift_check():
    script = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")

    assert "scripts/check-i18n-drift.py" in script
    assert "npm run docs:build" in script


def test_verify_script_smokes_public_command_groups():
    script = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    commands = [
        "agent",
        "briefing",
        "daily",
        "daily sync",
        "daemon",
        "docs",
        "docs audit",
        "doctor",
        "health",
        "log",
        "mcp",
        "reminders",
        "review",
        "skills",
        "trainer",
    ]

    for command in commands:
        assert f"bin/nudge {command} --help" in script
