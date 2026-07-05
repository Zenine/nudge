# Contributing to Nudge

Thanks for helping improve Nudge. Nudge is an AGPL-3.0, local-first macOS CLI for turning plans into Apple Calendar, Reminders, Notes, and Clock actions.

## Development setup

```bash
git clone https://github.com/Zenine/nudge.git
cd nudge
scripts/bootstrap_mac.sh
```

`scripts/bootstrap_mac.sh` creates a project-local `.venv` and installs the CLI for local development. If you prefer to manage your own environment, use Python 3.12+ and install the project dependencies from `pyproject.toml` / `requirements.txt`.

## Verification

Before opening a pull request, run the public verification entrypoint:

```bash
scripts/verify.sh
```

This runs the test suite, Python compile checks, CLI smoke checks, and the documentation audit. Keep tests offline and deterministic. CI runs this same script on Linux, so tests for shared logic must not require Apple permissions or a logged-in macOS desktop.

## Apple write safety

Changes that affect Apple Calendar, Reminders, Notes, Clock, AppleScript, EventKit, Shortcuts, MCP, or agent write paths should prioritize:

1. `--dry-run` behavior before real writes.
2. Fake/offline tests for generated actions, validation, idempotency, and error handling.
3. Clear user confirmation for real writes.

Do not add tests that write to real Apple apps in public CI.

## Privacy and local data

Do not commit or paste private local data. Keep these out of the repository, issues, pull requests, logs, fixtures, and screenshots:

- `config.toml` with personal values.
- Local SQLite databases or app state.
- API keys, OAuth tokens, passwords, or other secrets.
- Apple Health exports or health-derived raw data.
- Personal plans, reminders, calendar data, notes, or database snapshots.

Use synthetic examples in tests and documentation.

## Pull requests

- Keep changes focused and explain the user-visible behavior.
- Add or update tests for behavior changes.
- Update documentation when commands, configuration, privacy expectations, or safety behavior changes.
- Confirm `scripts/verify.sh` was run and summarize the result in the PR.
