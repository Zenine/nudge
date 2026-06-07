<!--
  Translation status:
  Source file : README.md
  Source commit: 5f1ebe9
  Translated  : 2026-06-07
  Status      : up-to-date
-->

> **Language**: [简体中文](README.md) · **English** · [日本語](README.ja.md) · [繁體中文](README.zh-TW.md)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg?style=flat-square)](LICENSE)
[![Stars](https://img.shields.io/github/stars/Zenine/nudge?style=flat-square&color=gold)](https://github.com/Zenine/nudge/stargazers)
[![Last Commit](https://img.shields.io/github/last-commit/Zenine/nudge?style=flat-square)](https://github.com/Zenine/nudge/commits/main)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](https://github.com/Zenine/nudge/pulls)
[![Docs](https://img.shields.io/badge/Docs-online-22d3ee?style=flat-square&logo=vitepress&logoColor=white)](https://zenine.github.io/nudge/)
[![Powered by Meridian](https://img.shields.io/badge/Powered%20by-Meridian-8b5cf6?style=flat-square)](https://github.com/lordmos/meridian)

<div align="center">
  <img src=".github/assets/hero.svg" alt="Nudge" width="120" />
</div>

# Nudge

Nudge is a local-first macOS CLI runtime for turning structured or natural-language plans into Apple Calendar, Reminders, Notes, and Clock actions.

This public repository contains only the reusable runtime, CLI, Apple adapters, daemon, MCP wrapper, and installation scripts. Personal plans, local configuration, private state, API keys, Health exports, and user-specific documents should stay in a private overlay.

## Quick Start

> Full docs → [Read online](https://zenine.github.io/nudge/en/quick-start)

**Step 1** — Clone the project:

```bash
git clone https://github.com/Zenine/nudge.git
cd nudge
```

**Step 2** — Install and check your local environment:

```bash
scripts/bootstrap_mac.sh
nudge doctor
```

**Step 3** — Dry-run first, then write to Apple apps:

```bash
nudge --dry-run "Project sync tomorrow at 3pm"
nudge "Project sync tomorrow at 3pm"
```

`scripts/bootstrap_mac.sh` creates a project-local `.venv`; users do not need to manage Python virtual environments manually.

## Features

- Local-first macOS CLI for Calendar, Reminders, Notes, and the optional Clock shortcut.
- Dry-run first: `nudge --dry-run "..."` shows the parse before any write.
- Private overlay support keeps personal configuration and SQLite state out of the public repository.
- MCP wrapper: `nudge mcp serve` gives agents a stable access point.
- Daily sync reconciles Reminders completions, HealthExport data, and documentation maintenance signals.
- Review loop turns weekly activity into safe adjustment suggestions.
- `scripts/verify.sh` covers tests, compile checks, CLI smoke checks, i18n drift checks, VitePress docs build, and read-only documentation audit.

## Recommended Flow

1. `nudge doctor` checks config, LLM keys, and Apple permissions.
2. `nudge --dry-run "..."` lets you inspect parsing before any Apple write.
3. `nudge "..."` writes confirmed Calendar / Reminders / Notes / Clock actions.
4. `nudge log ...` records what actually happened.
5. `nudge daily sync --json` reconciles Reminders, HealthExport, and documentation audit signals.
6. `nudge review weekly --adapt --dry-run` generates weekly review and adjustment suggestions.
7. `scripts/bootstrap_launchd.sh` can automate morning brief, daily sync, evening brief, and the daemon.

## Using a Private Overlay

Nudge can run this public runtime while reading private configuration and SQLite state from another directory. Keep personal plans, database files, API key paths, Health exports, and machine-specific settings in that private overlay.

```bash
export NUDGE_CONFIG=/path/to/private/config.toml
export NUDGE_STATE_DIR=/path/to/private/state

bin/nudge doctor
bin/nudge mcp serve
bin/nudge agent status --file /path/to/status.json
```

You can also pass private configuration for a single command:

```bash
bin/nudge --config /path/to/private/config.toml doctor
bin/nudge --config /path/to/private/config.toml --dry-run "Project sync tomorrow at 3pm"
```

If `NUDGE_CONFIG` points at a private config file, relative `[state].dir` values are resolved from that config file's directory. An explicit `--config /path/to/config.toml` takes priority over `NUDGE_CONFIG`.

## Maintenance

```bash
nudge docs audit
nudge docs audit --json
scripts/bootstrap_launchd.sh status
```

`nudge docs audit` is read-only. `nudge daily sync --apply --json` can create a local maintenance action when documentation errors or warnings need attention; it does not move, delete, or rewrite documentation.

## Platform Boundary

Nudge is macOS-first. CLI dry-runs, Skill validation, documentation audit, and JSON previews can run from the public repository; real Apple Calendar / Reminders / Notes / Clock writes, `launchd` daemon installation, and the graphical control app are macOS-only. Non-macOS environments are intended for reading docs, running tests, and previewing JSON, and do not provide cross-platform Apple writes by default.

## Testing and Verification

Use the repository verification script before committing changes:

```bash
scripts/verify.sh
```

It runs the public test suite, Python compile checks, CLI smoke checks, i18n drift checks, VitePress docs build, and read-only documentation audit.

For focused checks while developing, run:

```bash
python3 -m pytest tests/ -q
bin/nudge docs audit --json
```

## Private Data

Keep these outside the public repository:

- `config.toml`
- local SQLite state
- API keys and OAuth tokens
- personal plans and health documents
- Apple Health exports
- app-specific local database snapshots

Prefer environment variables or `config.toml [llm].secrets_path` for secrets. Do not commit secrets, tokens, databases, or personal absolute paths to the public repository.

## License

Nudge is licensed under [AGPL-3.0-only](LICENSE).

---

<sub>Built with [Meridian](https://github.com/lordmos/meridian) · open-source ops toolkit for Agent projects</sub>
