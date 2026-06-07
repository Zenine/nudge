from pathlib import Path

from click.testing import CliRunner

from nudge.cli import cli


def _help(args: list[str]) -> str:
    result = CliRunner().invoke(cli, [*args, "--help"], prog_name="nudge")
    assert result.exit_code == 0, result.output
    return result.output


def test_public_cli_help_exposes_release_reference_surface():
    expected_help = {
        ("doctor",): ["--llm-ping"],
        ("skills", "import"): ["SKILL_SOURCE", "--bump-version", "--json"],
        ("daemon", "enqueue"): ["--config", "--json"],
        ("daemon", "queue"): ["--config", "--json"],
        ("daemon", "status"): ["--config", "--json"],
        ("daemon", "recover"): ["--config", "--json"],
        ("daemon", "retry"): ["--config", "--request-id", "--json"],
        ("daemon", "health"): ["--config", "--notify", "--json"],
        ("daemon", "run"): ["--config", "--once"],
        ("health", "import"): ["--config", "--apply", "--json"],
        ("habits",): ["--config"],
        ("review", "weekly"): ["--config", "--adapt", "--dry-run", "--apply"],
        ("dogfood", "weekly"): ["--config", "--save", "--json", "--export-json"],
    }

    for args, expected_tokens in expected_help.items():
        output = _help(list(args))
        for token in expected_tokens:
            assert token in output, f"missing {token!r} from help for nudge {' '.join(args)}"


def test_reference_docs_cover_release_cli_surface_in_all_languages():
    docs = [
        Path("docs/reference.md"),
        Path("docs/en/reference.md"),
        Path("docs/ja/reference.md"),
        Path("docs/zh-TW/reference.md"),
    ]
    required_snippets = [
        "nudge doctor --llm-ping --json",
        "nudge skills import",
        "nudge daemon enqueue --config /path/to/private/config.toml",
        "nudge daemon queue --config /path/to/private/config.toml",
        "nudge daemon status --config /path/to/private/config.toml",
        "nudge daemon recover --config /path/to/private/config.toml",
        "nudge daemon retry --config /path/to/private/config.toml",
        "nudge daemon health --config /path/to/private/config.toml",
        "nudge daemon run --config /path/to/private/config.toml",
        "nudge health import export.zip --config /path/to/private/config.toml",
        "nudge habits --config /path/to/private/config.toml",
        "nudge review weekly --config /path/to/private/config.toml",
        "nudge dogfood weekly --config /path/to/private/config.toml",
    ]

    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for snippet in required_snippets:
            assert snippet in text, f"missing {snippet!r} from {doc}"
