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
8. `nudge skills start <skill-id>` runs the skill assessment, personalizes the plan, and writes the first week into Calendar/Reminders; `nudge skills adapt <plan-id> --apply` materializes the next week using your real check-in data.

## Skills Lifecycle

```bash
nudge skills list
nudge skills start strength-basics-12w
nudge log done --metric effort=8
nudge skills status
nudge skills adapt <plan-id>            # preview next week with data-driven adaptation
nudge skills adapt <plan-id> --apply    # write next week
```

Skill instances are stored locally (plans/actions in SQLite). `skills start --dry-run` and `skills adapt` without `--apply` never write to Apple apps.

## Trainer Compatibility

`nudge trainer plan` is the fitness-focused entry point for the built-in `strength-basics-12w` Skill. It reads `[user.fitness]`, creates a local Skill instance, and writes the first week through the same Apple-safe runtime used by `nudge skills start`.

```bash
nudge trainer plan --dry-run
nudge trainer plan --yes
nudge log done --metric effort=8
nudge trainer status
```

The previous LLM-generated weekly workout planner is still available as an explicit compatibility path: `nudge trainer plan --legacy-llm`.

## Maintenance

```bash
nudge docs audit
nudge docs audit --json
scripts/bootstrap_launchd.sh status
```

`nudge docs audit` is read-only. `nudge daily sync --apply --json` can create a local maintenance action when documentation errors or warnings need attention; it does not move, delete, or rewrite documentation.

## Agent / MCP Safety

Structured `agent apply` and MCP `apply_apple_actions` real writes require a caller-generated `request_id`. Nudge treats that id as an idempotency key: retrying the exact same request returns the stored result instead of writing duplicate Apple items, while reusing the same id with different actions is rejected.

Use `dry_run=true` first when generating multi-action plans. For real writes, keep the same `request_id` and payload that the user approved. If a process exits after reserving a request but before storing the final response, the same request can be retried after the stale-running window instead of being permanently stuck.

## Private Data

Keep these outside the public repository:

- `config.toml`
- local SQLite state
- API keys and OAuth tokens
- personal plans and health documents
- Apple Health exports
- app-specific local database snapshots

Use environment variables or `config.toml [llm].secrets_path` for secrets.
