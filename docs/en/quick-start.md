<!--
  Translation status:
  Source file : docs/quick-start.md
  Source commit: 0cb38bb
  Translated  : 2026-06-02
  Status      : up-to-date
-->

# Quick Start

Nudge is a local-first macOS CLI runtime for turning structured or natural-language plans into Apple Calendar, Reminders, Notes, and Clock actions.

## Three Steps

### 1. Clone the project

```bash
git clone https://github.com/Zenine/nudge.git
cd nudge
```

### 2. Install and check the environment

```bash
scripts/bootstrap_mac.sh
nudge doctor
```

`scripts/bootstrap_mac.sh` creates a project-local `.venv`, so you do not need to manage Python virtual environments manually.

### 3. Dry-run first, then run

```bash
nudge --dry-run "Project sync tomorrow at 3pm"
nudge "Project sync tomorrow at 3pm"
```

Dry-run shows the parsed action. Run the command without `--dry-run` only after the result looks right.

## Use a Private Overlay

Nudge's recommended boundary is "public runtime, private state." Keep personal plans, local config, SQLite state, API keys, Health exports, and machine-specific paths in a private overlay.

```bash
export NUDGE_CONFIG=/path/to/private/config.toml
export NUDGE_STATE_DIR=/path/to/private/state

bin/nudge doctor
bin/nudge mcp serve
```

You can also pass config for one command:

```bash
bin/nudge --config /path/to/private/config.toml doctor
```

## You Only Need To Do Three Things

1. Run `nudge doctor` to confirm Apple permissions and config.
2. Use `--dry-run` before any real write.
3. Run `scripts/verify.sh` before committing code changes.

## Resume After Interruption

If an AI assistant is maintaining this repository, resume with:

```text
请读 checkpoint.md，继续上次未完成的工作。
```

## Learn More

- [README](https://github.com/Zenine/nudge#readme)
- [FAQ](./faq.md)
- [GitHub](https://github.com/Zenine/nudge)
