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

## Private Data

Keep these outside the public repository:

- `config.toml`
- local SQLite state
- API keys and OAuth tokens
- personal plans and health documents
- Apple Health exports
- app-specific local database snapshots

Use environment variables or `config.toml [llm].secrets_path` for secrets.
