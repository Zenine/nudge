# Nudge

Nudge is a local-first macOS CLI base for turning structured or natural-language plans into Apple Calendar, Reminders, Notes, and Clock actions.

This public repository contains the reusable runtime, CLI, Apple adapters, daemon, MCP wrapper, and installation scripts. Personal plans, local configuration, private state, API keys, Health exports, and user-specific documents are intentionally not included.

## Quick Start

```bash
git clone https://github.com/Zenine/nudge.git
cd nudge
scripts/bootstrap_mac.sh
nudge doctor
nudge --dry-run "Project sync tomorrow at 3pm"
```

`scripts/bootstrap_mac.sh` creates a project-local `.venv`; users do not need to manage Python virtual environments manually.

## Recommended Flow

1. `nudge doctor` checks config, LLM keys, and Apple permissions.
2. `nudge --dry-run "..."` lets you inspect parsing before any Apple write.
3. `nudge "..."` writes confirmed Calendar / Reminders / Notes / Clock actions.
4. `nudge log ...` records what actually happened.
5. `nudge daily sync --json` reconciles Reminders completions, HealthExport data, and documentation audit results.
6. `nudge review weekly --adapt --dry-run` turns the week into safe adjustment suggestions.
7. `scripts/bootstrap_launchd.sh` optionally automates morning brief, daily sync, evening brief, and the daemon.

## Maintenance

```bash
nudge docs audit
nudge docs audit --json
scripts/bootstrap_launchd.sh status
```

`nudge docs audit` is read-only. `nudge daily sync --apply --json` can create a local maintenance action when documentation errors or warnings need attention; it does not move, delete, or rewrite documentation.

## Using a Private Overlay

Nudge can run this public runtime while reading private configuration and SQLite state from another directory. Keep personal plans, database files, API key paths, Health exports, and machine-specific settings in that private overlay.

```bash
export NUDGE_CONFIG=/path/to/private/config.toml
# Optional: override the state directory without editing config.toml.
export NUDGE_STATE_DIR=/path/to/private/state

bin/nudge doctor
bin/nudge mcp serve
bin/nudge agent status --file /path/to/status.json
```

If `NUDGE_CONFIG` points at a private config file, relative `[state].dir` values are resolved from that config file's directory. An explicit `--config /path/to/config.toml` takes priority over `NUDGE_CONFIG`.

## Private Data

Keep these outside the public repository:

- `config.toml`
- local SQLite state
- API keys and OAuth tokens
- personal plans and health documents
- Apple Health exports
- app-specific local database snapshots

Use environment variables or `config.toml [llm].secrets_path` for secrets.
