<!--
  Translation status:
  Source file : docs/reference.md
  Source commit: 5f1ebe9
  Translated  : 2026-06-07
  Status      : up-to-date
-->

# Command Reference

This page lists the Nudge public runtime commands most useful for automation. Any path that writes to Apple apps or local SQLite should be checked first with dry-run or read-only output.

## Safety Boundaries

- Run the matching dry-run command before writing to Apple Calendar, Reminders, Notes, or Clock.
- When using a private overlay, keep the same `--config`, `NUDGE_CONFIG`, or `NUDGE_STATE_DIR` across a workflow so commands read and write the same SQLite database.
- Do not hand-write SQL to change Nudge state; prefer commands such as `nudge log`, `nudge agent status`, `nudge reminders sync-completed`, and `nudge daily sync`.
- High-risk reminders such as medical, medication, payment, identity document, travel, and family class items should be confirmed manually.

### Public safe smoke commands

The following commands can run from the public repository with a temporary `HOME` as smoke checks. They read help, emit JSON, run deterministic Skill rules, or perform a read-only documentation audit; they do not write real Apple apps and should not touch the real user HOME.

```bash
tmpdir="$(mktemp -d)"
mkdir -p "$tmpdir/home"

cat > "$tmpdir/context.json" <<'JSON'
{
  "assessment": {
    "morning_energy": true,
    "meetings_load": "high"
  },
  "history": {
    "distraction_avg_7d": 6
  },
  "profile": {
    "preferred_days": ["Monday", "Wednesday", "Friday"],
    "preferred_time": "08:30",
    "start_date": "2026-06-01"
  }
}
JSON

HOME="$tmpdir/home" NUDGE_STATE_DIR="$tmpdir/state" bin/nudge --help
HOME="$tmpdir/home" NUDGE_STATE_DIR="$tmpdir/state" bin/nudge doctor --help
HOME="$tmpdir/home" NUDGE_STATE_DIR="$tmpdir/state" bin/nudge doctor --json
HOME="$tmpdir/home" NUDGE_STATE_DIR="$tmpdir/state" bin/nudge skills list --json
HOME="$tmpdir/home" NUDGE_STATE_DIR="$tmpdir/state" bin/nudge skills show deep-work-weekly-rhythm --json
HOME="$tmpdir/home" NUDGE_STATE_DIR="$tmpdir/state" bin/nudge skills validate deep-work-weekly-rhythm --json
HOME="$tmpdir/home" NUDGE_STATE_DIR="$tmpdir/state" bin/nudge skills apply deep-work-weekly-rhythm --context "$tmpdir/context.json" --json
HOME="$tmpdir/home" NUDGE_STATE_DIR="$tmpdir/state" bin/nudge skills dry-run deep-work-weekly-rhythm --context "$tmpdir/context.json" --weeks 1 --json
HOME="$tmpdir/home" NUDGE_STATE_DIR="$tmpdir/state" bin/nudge docs audit --json
```

`nudge doctor --json` may exit non-zero when the local machine has no `config.toml`, LLM key, or Apple read permission; that is still parseable diagnostic output. `--llm-ping` makes an explicit provider call and is not part of the default smoke set.

## Core Commands

### `nudge doctor`

Checks local configuration, LLM keys, and macOS app permissions.

```bash
nudge doctor
nudge doctor --json
nudge doctor --llm-ping --json
nudge --config /path/to/private/config.toml doctor
```

Use it after first install, private overlay changes, or Apple permission fixes. `--json` output is suitable for scripts and agents. `--llm-ping` actively makes a tiny provider call and is off by default.

### `nudge daily sync`

Syncs daily Health, Reminders, and documentation audit signals, then shows items still needing human handling.

```bash
nudge daily sync --json
nudge daily sync --date 2026-06-06 --json
nudge daily sync --from 2026-06-01 --date 2026-06-06 --json
nudge daily sync --apply --json
```

The default is dry-run and does not write SQLite. Add `--apply` to write local state. Health ranges use inclusive `--health-from` and exclusive `--health-to`.

### `nudge review weekly`

Generates a weekly review and can ask AI for adjustment suggestions.

```bash
nudge review weekly
nudge review weekly --config /path/to/private/config.toml
nudge review weekly --adapt --dry-run
nudge review weekly --config /path/to/private/config.toml --adapt --dry-run
nudge review weekly --adapt --apply
```

`--dry-run` previews the adjustment plan. `--apply` applies safe adjustments after confirmation.

### `nudge mcp serve`

Serves MCP JSON-RPC over stdio so local agents can call Nudge tools.

```bash
nudge mcp serve
nudge mcp serve --config /path/to/private/config.toml
```

This command reserves stdout for JSON-RPC messages, so normal logs should not be written to stdout.

### `nudge agent apply`

Reads structured Apple action requests from another local agent or automation tool.

```bash
nudge agent apply --file request.json --dry-run --json
nudge agent apply --file request.json --config /path/to/private/config.toml --json
```

Use `--dry-run` first to inspect the Apple items that would be created. Real execution should still use private overlay configuration.

### `nudge agent status`

Updates local action status from another local agent or automation tool.

```bash
nudge agent status --file status.json --dry-run --json
nudge agent status --file status.json --config /path/to/private/config.toml --json
```

Status updates must use the same configuration or state directory that created the action.

### `nudge daemon`

Runs the local queue runtime for background Apple write requests without LLM.

```bash
nudge daemon enqueue --type agent.apply --file request.json --json
nudge daemon enqueue --config /path/to/private/config.toml --type agent.apply --file request.json --json
nudge daemon queue --config /path/to/private/config.toml --json
nudge daemon status --config /path/to/private/config.toml --json
nudge daemon recover --config /path/to/private/config.toml --json
nudge daemon retry --config /path/to/private/config.toml --request-id req-123 --json
nudge daemon health --config /path/to/private/config.toml --json
nudge daemon run --config /path/to/private/config.toml --once
nudge daemon status --json
nudge daemon health --json
```

Common maintenance paths also include `nudge daemon recover`, `nudge daemon retry`, and `nudge daemon launchd status`.

### `nudge skills`

Validates and applies deterministic Skill Spec rules.

```bash
nudge skills validate skill.yaml --json
nudge skills import skill.yaml --json
nudge skills dry-run skill.yaml --context context.json --json
nudge skills apply skill.yaml --context context.json --json
```

`dry-run` previews candidate actions without writing Apple apps. `apply` applies personalization and adaptation rules.

### `nudge health import`

Parses an Apple Health export ZIP or HealthExport JSON file.

```bash
nudge health import export.zip --json
nudge health import export.zip --from 2026-06-01 --to 2026-06-07 --json
nudge health import export.zip --config /path/to/private/config.toml --apply --json
nudge health import export.zip --apply --json
```

The default only parses and reports aggregate counts; it does not write SQLite. `--from` is inclusive and `--to` is exclusive. Workout route GPX files in ZIP exports are counted in `ignored_route_files`, but route traces are not imported.

### `nudge habits`

Views habit streaks or records one habit completion.

```bash
nudge habits --config /path/to/private/config.toml
nudge habits --config /path/to/private/config.toml log reading
```

Logging a habit writes to local SQLite. When using a private overlay, pass the same configuration explicitly.

### `nudge dogfood weekly`

Generates a read-only weekly dogfood report and can save it under the current state dir.

```bash
nudge dogfood weekly --config /path/to/private/config.toml
nudge dogfood weekly --config /path/to/private/config.toml --save
nudge dogfood weekly --config /path/to/private/config.toml --json
```

`--save` writes the report to `dogfood/YYYY-WW.md` under the current state dir. `--json` and `--export-json` are useful for pre-release automation.

## Skills End-to-End Example

The following flow uses only the public repository and a temporary directory. It can run without a private overlay and without real Apple write permissions. `skills apply` only applies deterministic personalization / adaptation rules and prints the transformed Skill; `skills dry-run` generates candidate Calendar actions and still does not write Apple apps.

```bash
tmpdir="$(mktemp -d)"
mkdir -p "$tmpdir/home"

cat > "$tmpdir/context.json" <<'JSON'
{
  "assessment": {
    "morning_energy": true,
    "meetings_load": "high"
  },
  "history": {
    "distraction_avg_7d": 6
  },
  "profile": {
    "preferred_days": ["Monday", "Wednesday", "Friday"],
    "preferred_time": "08:30",
    "start_date": "2026-06-01"
  }
}
JSON

HOME="$tmpdir/home" bin/nudge skills list --json
HOME="$tmpdir/home" bin/nudge skills show deep-work-weekly-rhythm --json
HOME="$tmpdir/home" bin/nudge skills validate deep-work-weekly-rhythm --json
HOME="$tmpdir/home" bin/nudge skills apply deep-work-weekly-rhythm --context "$tmpdir/context.json" --json
HOME="$tmpdir/home" bin/nudge skills dry-run deep-work-weekly-rhythm --context "$tmpdir/context.json" --weeks 1 --json
```

With this context, the builtin Skill matches `heavy_meeting_week`, `morning_focus`, and `too_many_distractions`: a heavy meeting week lowers the weekly session count, morning energy prefers the morning slot, and recent distraction pressure lowers the default session length to 50 minutes. `profile.preferred_time` can still override the final dry-run action start time, so candidate actions begin at `2026-06-01 08:30`.

Custom Skills can also run through validate → import → dry-run → delete. This example keeps using the temporary `HOME`, so it only writes to `$tmpdir/home/.nudge/skills` and does not touch the real user directory.

```bash
cat > "$tmpdir/custom-focus-rhythm.yaml" <<'YAML'
schema_version: "0.1"
kind: skill
metadata:
  id: custom-focus-rhythm
  title: 自定义专注节奏
  version: 1.0.0
  creator: Docs Example
  category: productivity
audience:
  goals:
    - 保护专注时间
  level: beginner
assessment:
  - id: energy
    question: 你上午精力好吗？
    type: boolean
personalization:
  - id: morning_energy
    when:
      "==":
        - var: assessment.energy
        - true
    apply:
      - op: set
        path: plan_template.defaults.preferred_time
        value: "09:30"
plan_template:
  defaults:
    sessions_per_week: 2
    session_minutes: 45
    preferred_days: [Monday, Wednesday]
    preferred_time: "14:00"
  phases:
    - id: week
      title: 每周执行
      weeks: 1
      sessions:
        - id: focus_1
          title: 专注块 1
          duration_minutes: 45
        - id: focus_2
          title: 专注块 2
          duration_minutes: 45
tracking:
  metrics:
    - id: distraction_count
      type: number
adaptation:
  - id: distraction_overload
    trigger:
      ">":
        - var: history.distraction_avg_7d
        - 5
    apply:
      - op: set
        path: plan_template.defaults.session_minutes
        value: 30
YAML

cat > "$tmpdir/custom-context.json" <<'JSON'
{
  "assessment": {
    "energy": true
  },
  "history": {
    "distraction_avg_7d": 2
  },
  "profile": {
    "start_date": "2026-06-01"
  }
}
JSON

HOME="$tmpdir/home" bin/nudge skills validate "$tmpdir/custom-focus-rhythm.yaml" --json
HOME="$tmpdir/home" bin/nudge skills import "$tmpdir/custom-focus-rhythm.yaml" --json
HOME="$tmpdir/home" bin/nudge skills dry-run custom-focus-rhythm --context "$tmpdir/custom-context.json" --json
HOME="$tmpdir/home" bin/nudge skills delete custom-focus-rhythm --json
```

## Runtime Log Truncation and Secret Boundaries

Runtime logs are written to `logs/nudge-runtime.jsonl` under the current state dir. When using a private overlay, read the matching log through the same `--config`, `NUDGE_CONFIG`, or `NUDGE_STATE_DIR`; do not commit this log to the public repository.

Log entries are sanitized before they are written:

- String fields keep at most 2000 characters.
- Numbers and booleans are kept as-is.
- Lists keep at most the first 10 items, and each item is converted to a string with at most 1000 characters.
- Other objects are converted to strings with at most 2000 characters.
- `log_error_report` records only structured code, message, detail, and next steps; it does not store raw provider output or raw AppleScript output.

These truncation rules reduce log size and the risk of accidentally storing sensitive output, but they are not a secrets boundary. API keys, OAuth tokens, account passwords, private keys, Health exports, personal plans, and private absolute machine paths must still stay in a private overlay, environment variables, or uncommitted local configuration. Public docs and examples must not contain real secrets.

## Daemon Platform Boundary

The Nudge daemon is a macOS-first local queue runtime. `nudge daemon enqueue`, `queue`, `status`, `recover`, and `retry` can be used for troubleshooting and tests; real Apple writes still depend on macOS Apple apps and their permissions.

`nudge daemon launchd ...` and the graphical control app are macOS-only. On non-macOS systems, launchd status reports an unsupported platform. The project does not provide a Linux / Windows Apple-write replacement layer by default. Cross-platform environments can run docs builds, tests, Skill dry-runs, and JSON previews, but real Calendar / Reminders / Notes / Clock execution should stay on a macOS host.

## Publishing and Webmaster Verification

The documentation site uses GitHub Pages and VitePress:

- GitHub Pages should use the GitHub Actions workflow as its build source.
- The site URL is `https://zenine.github.io/nudge/`.
- The sitemap URL is `https://zenine.github.io/nudge/sitemap.xml`.
- Google / Bing verification tokens should be written to `docs/.vitepress/verification-meta.mts`; do not write secrets or account credentials.

After updating webmaster verification tokens, run:

```bash
python3 scripts/check-i18n-drift.py
cd docs && npm run docs:build
scripts/verify.sh
```
