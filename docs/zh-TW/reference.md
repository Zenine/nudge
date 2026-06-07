<!--
  Translation status:
  Source file : docs/reference.md
  Source commit: 5f1ebe9
  Translated  : 2026-06-07
  Status      : up-to-date
-->

# 命令參考

本頁列出 Nudge 公開 runtime 中最常用、最適合寫進自動化流程的命令。所有會寫入 Apple apps 或本機 SQLite 的路徑，都應先用 dry-run 或唯讀輸出確認。

## 安全邊界

- 真實寫入 Apple Calendar、Reminders、Notes 或 Clock 前，先執行對應 dry-run 命令。
- 使用 private overlay 時，同一輪命令應使用同一個 `--config`、`NUDGE_CONFIG` 或 `NUDGE_STATE_DIR`，避免讀寫不同 SQLite。
- 不直接手寫 SQL 修改 Nudge 狀態；優先使用 `nudge log`、`nudge agent status`、`nudge reminders sync-completed`、`nudge daily sync` 等命令。
- 醫療、用藥、付款、證件、出行、家庭課程等高風險提醒，應先人工確認。

### Public safe smoke commands

下面這些命令可以在公開 repository 和臨時 `HOME` 中作為 smoke check 執行；它們只讀取 help、輸出 JSON、執行 deterministic Skill rules 或執行唯讀文件審計，不會真實寫入 Apple apps，也不應觸碰真實 user HOME。

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

`nudge doctor --json` 可能因本機沒有 `config.toml`、LLM key 或 Apple read permission 而回傳 non-zero；這仍是可解析的診斷輸出。`--llm-ping` 會主動發起 provider call，不屬於 default smoke。

## 核心命令

### `nudge doctor`

檢查本機設定、LLM key 和 macOS app permissions。

```bash
nudge doctor
nudge doctor --json
nudge doctor --llm-ping --json
nudge --config /path/to/private/config.toml doctor
```

適合在首次安裝、切換 private overlay、修復 Apple 權限後執行。`--json` 輸出可給 scripts 或 agents 讀取。`--llm-ping` 會主動發起一次很小的 provider 呼叫，預設不啟用。

### `nudge daily sync`

同步每日 Health、Reminders 和 documentation audit signals，並顯示仍需要人工處理的事項。

```bash
nudge daily sync --json
nudge daily sync --date 2026-06-06 --json
nudge daily sync --from 2026-06-01 --date 2026-06-06 --json
nudge daily sync --apply --json
```

預設是 dry-run，不寫 SQLite。加 `--apply` 後才寫入本機狀態。Health 區間使用 `--health-from` 包含起始日、`--health-to` 不包含結束日。

### `nudge review weekly`

產生週回顧；可選讓 AI 給出調整建議。

```bash
nudge review weekly
nudge review weekly --config /path/to/private/config.toml
nudge review weekly --adapt --dry-run
nudge review weekly --config /path/to/private/config.toml --adapt --dry-run
nudge review weekly --adapt --apply
```

`--dry-run` 只預覽調整 plan；`--apply` 會在確認後套用安全調整。

### `nudge mcp serve`

透過 stdio 提供 MCP JSON-RPC 服務，讓 local agents 呼叫 Nudge tools。

```bash
nudge mcp serve
nudge mcp serve --config /path/to/private/config.toml
```

此命令的 stdout 只保留給 JSON-RPC messages，不應把普通 logs 寫到 stdout。

### `nudge agent apply`

從另一個 local agent 或 automation tool 讀取 structured Apple action requests。

```bash
nudge agent apply --file request.json --dry-run --json
nudge agent apply --file request.json --config /path/to/private/config.toml --json
```

先用 `--dry-run` 檢查即將建立的 Apple items；真實執行時仍應使用 private overlay configuration。

### `nudge agent status`

從另一個 local agent 或 automation tool 更新本機 action status。

```bash
nudge agent status --file status.json --dry-run --json
nudge agent status --file status.json --config /path/to/private/config.toml --json
```

狀態回寫必須和建立 action 時使用同一套 configuration 或 state directory。

### `nudge daemon`

本機 queue runtime，用於在背景處理 Apple write requests，不經過 LLM。

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

常見 maintenance path 還包括 `nudge daemon recover`、`nudge daemon retry` 和 `nudge daemon launchd status`。

### `nudge skills`

驗證和套用確定性的 Skill Spec rules。

```bash
nudge skills validate skill.yaml --json
nudge skills import skill.yaml --json
nudge skills dry-run skill.yaml --context context.json --json
nudge skills apply skill.yaml --context context.json --json
```

`dry-run` 用於預覽 candidate actions，不寫 Apple apps；`apply` 才會套用 personalization 和 adaptation rules。

### `nudge health import`

解析 Apple Health export ZIP 或 HealthExport JSON file。

```bash
nudge health import export.zip --json
nudge health import export.zip --from 2026-06-01 --to 2026-06-07 --json
nudge health import export.zip --config /path/to/private/config.toml --apply --json
nudge health import export.zip --apply --json
```

預設只解析並報告 aggregate counts，不寫 SQLite。`--from` 包含起始日期，`--to` 不包含結束日期。ZIP 中的 workout route GPX 會計入 `ignored_route_files`，但不會匯入路線軌跡。

### `nudge habits`

查看 habit streak 或記錄一次 habit 完成。

```bash
nudge habits --config /path/to/private/config.toml
nudge habits --config /path/to/private/config.toml log reading
```

記錄 habit 會寫入本機 SQLite；使用 private overlay 時應明確傳入同一個 configuration。

### `nudge dogfood weekly`

產生唯讀 weekly dogfood report，可選保存到目前 state dir。

```bash
nudge dogfood weekly --config /path/to/private/config.toml
nudge dogfood weekly --config /path/to/private/config.toml --save
nudge dogfood weekly --config /path/to/private/config.toml --json
```

`--save` 會把 report 寫入目前 state dir 的 `dogfood/YYYY-WW.md`；`--json` 和 `--export-json` 適合發布前 automation 檢查。

## Skills 端到端範例

下面的流程只使用公開儲存庫和臨時目錄，可以在沒有 private overlay、沒有真實 Apple 寫入權限的環境裡執行。`skills apply` 只套用 deterministic personalization / adaptation rules 並輸出變換後的 Skill；`skills dry-run` 才產生 candidate Calendar actions，仍不會寫入 Apple apps。

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

在上面的 context 中，builtin Skill 會命中 `heavy_meeting_week`、`morning_focus` 和 `too_many_distractions`：會議多會減少每週 session 數，上午精力好會偏向早間時間，最近分心過多會把預設 session 時長降到 50 分鐘。`profile.preferred_time` 仍可覆蓋最終 dry-run action 的開始時間，所以 candidate actions 會從 `2026-06-01 08:30` 開始。

自訂 Skill 也可以完整走 validate → import → dry-run → delete。這裡仍使用臨時 `HOME`，只寫入 `$tmpdir/home/.nudge/skills`，不會觸碰真實使用者目錄。

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

## Runtime log 截斷和密鑰邊界

Runtime log 寫到目前 state dir 下的 `logs/nudge-runtime.jsonl`。如果使用 private overlay，應透過同一個 `--config`、`NUDGE_CONFIG` 或 `NUDGE_STATE_DIR` 讀取對應 log；不要把此 log 提交到公開儲存庫。

Log entries 會先清洗再寫入：

- 字串欄位最多保留 2000 個字元。
- 數字和布林值原樣保留。
- Lists 最多保留前 10 項，每項轉換為字串後最多 1000 個字元。
- 其他 objects 會轉換為字串後最多保留 2000 個字元。
- `log_error_report` 只記錄 structured code、message、detail 和 next steps，不寫 raw provider output 或 raw AppleScript output。

這些截斷 rules 用於降低 log 體積和誤存 sensitive output 的風險，但不是 secrets boundary。API keys、OAuth tokens、account passwords、private keys、Health exports、personal plans 和 private absolute machine paths 仍必須留在 private overlay、environment variables 或未提交的本機 configuration 中；公開 docs 和 examples 不得包含 real secrets。

## Daemon 平台邊界

Nudge 的 daemon 是 macOS-first 的本機 queue runtime。`nudge daemon enqueue`、`queue`、`status`、`recover`、`retry` 等 SQLite queue commands 可以用於排查和測試；真正執行 Apple 寫入仍依賴 macOS Apple apps 和對應權限。

`nudge daemon launchd ...` 和 graphical control app 只支援 macOS。非 macOS 環境下，launchd status 會回報 unsupported platform；專案不預設實作 Linux / Windows 的 Apple 寫入替代層。跨平台環境可以執行文件建置、tests、Skill dry-run 和 JSON preview，但應把真實 Calendar / Reminders / Notes / Clock 執行留給 macOS 主機。

## 發布和 Webmaster 驗證

Documentation site 使用 GitHub Pages 和 VitePress：

- GitHub Pages 應使用 GitHub Actions workflow 作為 build source。
- Site URL 是 `https://zenine.github.io/nudge/`。
- Sitemap URL 是 `https://zenine.github.io/nudge/sitemap.xml`。
- Google / Bing verification tokens 應寫入 `docs/.vitepress/verification-meta.mts`，不要寫入 secrets 或 account credentials。

更新 Webmaster verification tokens 後，執行：

```bash
python3 scripts/check-i18n-drift.py
cd docs && npm run docs:build
scripts/verify.sh
```
