# Nudge

Nudge is a local-first macOS CLI base for turning structured or natural-language plans into Apple Calendar, Reminders, Notes, and Clock actions.

This public repository contains the reusable runtime, CLI, Apple adapters, daemon, MCP wrapper, and installation scripts. Personal plans, local configuration, private state, API keys, Health exports, and user-specific documents are intentionally not included.

## Quick Start

### Install from source today

```bash
git clone https://github.com/Zenine/nudge.git
cd nudge
scripts/bootstrap_mac.sh
nudge doctor
nudge --dry-run "Project sync tomorrow at 3pm"
```

`scripts/bootstrap_mac.sh` creates a project-local `.venv`; users do not need to manage Python virtual environments manually.

### Future PyPI / pipx install

`pyproject.toml` is prepared for the package name `nudge-ai-life-coach` and console script `nudge`, but this version has not been published to PyPI yet. After the release checklist is completed and the package is actually uploaded, the intended install path is:

```bash
pipx install nudge-ai-life-coach
nudge doctor
```

Until then, use the source install path above. Maintainers can follow [`docs/releasing.md`](docs/releasing.md) for the PyPI checklist.

For a full CLI reference, see [`docs/commands.md`](docs/commands.md).
架构与数据流见 [`docs/architecture.md`](docs/architecture.md)。
配置说明见 [`docs/configuration.md`](docs/configuration.md)。
LLM provider 选择见 [`docs/llm.md`](docs/llm.md)。
非 macOS 评估指南见 [`docs/non-macos.md`](docs/non-macos.md)。
公开示例库见 [`examples/README.md`](examples/README.md)。
发布记录见 [`CHANGELOG.md`](CHANGELOG.md)。

## Recommended Flow

1. `nudge doctor` checks config, LLM keys, and Apple permissions.
2. `nudge --dry-run "..."` lets you inspect parsing before any Apple write.
3. `nudge "..."` writes confirmed Calendar / Reminders / Notes / Clock actions.
4. `nudge log ...` records what actually happened.
5. `nudge feedback interview` closes overdue feedback in one structured TTY session; GPT follow-ups are optional and the final SQLite write is atomic.
6. `nudge daily sync --json` reconciles Reminders completions, HealthExport data, and documentation audit results.
7. `nudge review weekly --adapt --dry-run` turns the week into safe adjustment suggestions.
8. `scripts/bootstrap_launchd.sh` optionally automates morning brief, daily sync, evening brief, and the daemon.
9. `nudge skills start <skill-id>` runs the skill assessment, personalizes the plan, and writes the first week into Calendar/Reminders; `nudge skills adapt <plan-id> --apply` materializes the next week using your real check-in data.

## Capability Map

Nudge exposes both a human-friendly CLI and machine-friendly agent/MCP entrypoints. The full reference is in [`docs/commands.md`](docs/commands.md); this map highlights the main surfaces and whether they write to Apple apps or local state.

| Area | Commands | Typical use | Writes |
| --- | --- | --- | --- |
| Natural-language actions | `nudge "..."`, `nudge do`, `nudge chat`, `nudge schedule` | Turn a request into Calendar / Reminders / Notes / Clock actions; find and optionally book calendar slots. | Apple apps when not using `--dry-run`; SQLite action log for executed writes |
| Reminders and completion tracking | `nudge reminders sync-completed`, `nudge reminders backfill-ids`, `nudge log`, `nudge check-in`, `nudge feedback interview` | Reconcile one or more Reminders lists, backfill external IDs, and record outcomes/metrics. Repeat `--list` or configure `[reminders].sync_lists`; use the interview for bounded structured overdue feedback. | SQLite; Reminders only for explicit mutation paths |
| Health, habits, daily review | `nudge health import/daily`, `nudge habits`, `nudge daily sync`, `nudge review`, `nudge failures`, `nudge dogfood`, `nudge briefing` | Import Apple Health exports, inspect habits/streaks, generate daily/weekly review context, and surface stale or failed actions. | SQLite; notifications only when explicitly requested |
| Skills and trainer | `nudge skills list/show/validate/dry-run/start/status/adapt/create/update/delete`, `nudge trainer plan/log/status` | Run deterministic skill templates such as `strength-basics-12w`, adapt future weeks from logged metrics, and keep trainer compatibility. | SQLite and Apple apps for `start`/`adapt --apply` / trainer writes; dry-run paths are read-only |
| Agent / MCP automation | `nudge agent apply/status`, `nudge mcp serve` | Let trusted local automation submit structured action JSON or expose MCP tools. | Apple apps and SQLite after optional local-auth checks; dry-run paths are safe previews |
| Daemon, database, docs, diagnostics | `nudge daemon ...`, `nudge db backup/export/restore`, `nudge docs audit`, `nudge doctor` | Queue/retry background work, manage launchd/app helpers, back up local state, audit docs, and diagnose config/permissions. | SQLite/db files; launchd/app helper commands alter local automation only when explicitly run |

`nudge <text>` is intentionally equivalent to `nudge do <text>` when the first argument is not a known subcommand. Use `--dry-run` or command-specific preview flags before any real Apple write.

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

Use `dry_run=true` first when generating multi-action plans, then keep the same payload the user approved for the real write.

For stricter local automation, enable `[security.local_auth]` and pass `auth_token` in `agent apply/status`, MCP `apply_apple_actions`, or MCP `report_action_status` requests. See `SECURITY.md` and `docs/configuration.md`.

## Private Data

Keep these outside the public repository:

- `config.toml`
- local SQLite state
- API keys and OAuth tokens
- personal plans and health documents
- Apple Health exports
- app-specific local database snapshots

Use environment variables or `config.toml [llm].secrets_path` for secrets.
