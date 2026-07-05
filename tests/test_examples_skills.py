"""Public-safe test: the shipped skill example + context run cleanly in dry-run.

Guards the copy-paste command in docs/non-macos.md and examples/README.md so the
first-run smoke test that non-macOS / CI users follow keeps working.
"""

from pathlib import Path

from click.testing import CliRunner

from nudge.cli import cli


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "examples" / "skills" / "custom-skill-template.yaml"
CONTEXT = ROOT / "examples" / "skills" / "context.example.json"


def test_shipped_context_example_drives_template_dry_run():
    assert CONTEXT.exists(), "docs reference examples/skills/context.example.json"

    result = CliRunner().invoke(
        cli,
        ["skills", "dry-run", str(TEMPLATE), "--context", str(CONTEXT), "--weeks", "1"],
        prog_name="nudge",
    )

    assert result.exit_code == 0, result.output
    # The example context must actually exercise personalization, not just parse.
    assert "Personalization: use_user_session_count" in result.output
