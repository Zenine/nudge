<!--
  Translation status:
  Source file : docs/reference.md
  Source commit: 40b12c7
  Translated  : 2026-06-07
  Status      : up-to-date
-->

# コマンドリファレンス

このページでは、Nudge の公開 runtime で自動化に使いやすい主要コマンドをまとめます。Apple apps や local SQLite に書き込む経路は、必ず先に dry-run または読み取り専用出力で確認してください。

## 安全境界

- Apple Calendar、Reminders、Notes、Clock に実際に書き込む前に、対応する dry-run コマンドを実行します。
- private overlay を使う場合、同じ workflow の中では同じ `--config`、`NUDGE_CONFIG`、または `NUDGE_STATE_DIR` を使い、同じ SQLite database を読み書きします。
- Nudge state を手書き SQL で変更しません。`nudge log`、`nudge agent status`、`nudge reminders sync-completed`、`nudge daily sync` などのコマンドを優先します。
- 医療、服薬、支払い、身分証、旅行、家族の授業などの高リスク reminder は、先に人間が確認します。

### Public safe smoke commands

次のコマンドは、公開 repository と一時 `HOME` だけで smoke check として実行できます。help の読み取り、JSON 出力、deterministic Skill rules、読み取り専用 docs audit だけを行い、実際の Apple apps には書き込まず、本物の user HOME に触れない前提です。

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

`nudge doctor --json` は、ローカル machine に `config.toml`、LLM key、Apple read permission がない場合に non-zero で終了することがあります。それでも parse 可能な診断出力です。`--llm-ping` は明示的に provider call を行うため、default smoke には含めません。

## 主要コマンド

### `nudge doctor`

本機設定、LLM key、macOS app permissions を確認します。

```bash
nudge doctor
nudge doctor --json
nudge doctor --llm-ping --json
nudge --config /path/to/private/config.toml doctor
```

初回インストール後、private overlay の切り替え後、Apple 権限の修正後に実行します。`--json` 出力は scripts や agents で読めます。`--llm-ping` は小さな provider call を明示的に実行する option で、デフォルトでは無効です。

### `nudge daily sync`

毎日の Health、Reminders、documentation audit signals を同期し、人間の処理がまだ必要な項目を表示します。

```bash
nudge daily sync --json
nudge daily sync --date 2026-06-06 --json
nudge daily sync --from 2026-06-01 --date 2026-06-06 --json
nudge daily sync --apply --json
```

デフォルトは dry-run で、SQLite には書き込みません。`--apply` を付けた場合だけ local state に書き込みます。Health range は `--health-from` が開始日を含み、`--health-to` が終了日を含みません。

### `nudge review weekly`

週次 review を生成し、必要に応じて AI に調整案を作らせます。

```bash
nudge review weekly
nudge review weekly --config /path/to/private/config.toml
nudge review weekly --adapt --dry-run
nudge review weekly --config /path/to/private/config.toml --adapt --dry-run
nudge review weekly --adapt --apply
```

`--dry-run` は調整 plan の preview のみです。`--apply` は確認後に安全な調整を適用します。

### `nudge mcp serve`

stdio で MCP JSON-RPC を提供し、local agents が Nudge tools を呼び出せるようにします。

```bash
nudge mcp serve
nudge mcp serve --config /path/to/private/config.toml
```

この command の stdout は JSON-RPC messages 専用です。通常 logs は stdout に書かないでください。

### `nudge agent apply`

別の local agent または automation tool から structured Apple action requests を読み込みます。

```bash
nudge agent apply --file request.json --dry-run --json
nudge agent apply --file request.json --config /path/to/private/config.toml --json
```

まず `--dry-run` で作成予定の Apple items を確認します。実行時も private overlay configuration を使います。

### `nudge agent status`

別の local agent または automation tool から local action status を更新します。

```bash
nudge agent status --file status.json --dry-run --json
nudge agent status --file status.json --config /path/to/private/config.toml --json
```

Status update は、その action を作成した時と同じ configuration または state directory を使う必要があります。

### `nudge daemon`

LLM を使わず、background Apple write requests を処理する local queue runtime です。

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

よく使う maintenance path には `nudge daemon recover`、`nudge daemon retry`、`nudge daemon launchd status` もあります。

### `nudge skills`

決定的な Skill Spec rules を validate し、apply します。

```bash
nudge skills validate skill.yaml --json
nudge skills import skill.yaml --json
nudge skills dry-run skill.yaml --context context.json --json
nudge skills apply skill.yaml --context context.json --json
```

`dry-run` は Apple apps に書き込まず、candidate actions を preview します。`apply` は personalization と adaptation rules を適用します。

### `nudge health import`

Apple Health export ZIP または HealthExport JSON file を解析します。

```bash
nudge health import export.zip --json
nudge health import export.zip --from 2026-06-01 --to 2026-06-07 --json
nudge health import export.zip --config /path/to/private/config.toml --apply --json
nudge health import export.zip --apply --json
```

デフォルトでは解析して aggregate counts を表示するだけで、SQLite には書き込みません。`--from` は開始日を含み、`--to` は終了日を含みません。ZIP 内の workout route GPX は `ignored_route_files` に数えますが、route traces は import しません。

### `nudge habits`

Habit streaks を表示するか、habit の完了を 1 回記録します。

```bash
nudge habits --config /path/to/private/config.toml
nudge habits --config /path/to/private/config.toml log reading
```

Habit の記録は local SQLite に書き込みます。private overlay を使う場合は、同じ configuration を明示的に渡します。

### `nudge dogfood weekly`

読み取り専用の weekly dogfood report を生成し、必要に応じて現在の state dir に保存します。

```bash
nudge dogfood weekly --config /path/to/private/config.toml
nudge dogfood weekly --config /path/to/private/config.toml --save
nudge dogfood weekly --config /path/to/private/config.toml --json
```

`--save` は現在の state dir の `dogfood/YYYY-WW.md` に report を書き込みます。`--json` と `--export-json` は release 前の automation に適しています。

## Skills エンドツーエンド例

次の flow は公開リポジトリと一時ディレクトリだけを使います。private overlay も実際の Apple 書き込み権限も不要です。`skills apply` は deterministic personalization / adaptation rules を適用して変換後の Skill を出力するだけです。`skills dry-run` は candidate Calendar actions を生成しますが、Apple apps には書き込みません。

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

この context では、builtin Skill が `heavy_meeting_week`、`morning_focus`、`too_many_distractions` に一致します。会議が多い週は weekly session count を減らし、朝の energy が高い場合は morning slot を優先し、最近の distraction pressure が高い場合は default session length を 50 分に下げます。`profile.preferred_time` は最終的な dry-run action の開始時刻を上書きできるため、candidate actions は `2026-06-01 08:30` から始まります。

Custom Skills も validate → import → dry-run → delete を通せます。この例も一時的な `HOME` を使うため、書き込み先は `$tmpdir/home/.nudge/skills` だけで、実際の user directory には触れません。

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

## Runtime log の切り詰めと secrets 境界

Runtime logs は現在の state dir 配下の `logs/nudge-runtime.jsonl` に書かれます。private overlay を使う場合は、同じ `--config`、`NUDGE_CONFIG`、または `NUDGE_STATE_DIR` で対応する log を読んでください。この log を公開リポジトリへ commit しないでください。

Log entries は書き込み前に sanitize されます。

- String fields は最大 2000 文字です。
- Numbers と booleans はそのまま保持されます。
- Lists は先頭 10 items まで保持し、各 item は string 化したうえで最大 1000 文字です。
- その他の objects は string 化したうえで最大 2000 文字です。
- `log_error_report` は structured code、message、detail、next steps だけを記録し、raw provider output や raw AppleScript output は保存しません。

これらの切り詰め rules は log size と sensitive output を誤って保存する risk を下げますが、secrets boundary ではありません。API keys、OAuth tokens、account passwords、private keys、Health exports、personal plans、private absolute machine paths は private overlay、environment variables、または commit しない local configuration に置いてください。公開 docs と examples には real secrets を含めないでください。

## Daemon プラットフォーム境界

Nudge daemon は macOS-first の local queue runtime です。`nudge daemon enqueue`、`queue`、`status`、`recover`、`retry` は troubleshooting と tests に使えます。実際の Apple writes には macOS Apple apps と対応する permissions が必要です。

`nudge daemon launchd ...` と graphical control app は macOS only です。非 macOS systems では launchd status が unsupported platform を報告します。この project は Linux / Windows 向け Apple-write replacement layer をデフォルトでは提供しません。Cross-platform environments では docs build、tests、Skill dry-run、JSON preview を実行できますが、実際の Calendar / Reminders / Notes / Clock execution は macOS host に残してください。

## 公開と Webmaster 検証

Documentation site は GitHub Pages と VitePress を使います。

- GitHub Pages は GitHub Actions workflow を build source として使うべきです。
- Site URL は `https://zenine.github.io/nudge/` です。
- Sitemap URL は `https://zenine.github.io/nudge/sitemap.xml` です。
- Google / Bing verification tokens は `docs/.vitepress/verification-meta.mts` に書きます。secrets や account credentials は書きません。

Webmaster verification tokens を更新した後は、次を実行します。

```bash
python3 scripts/check-i18n-drift.py
cd docs && npm run docs:build
scripts/verify.sh
```
