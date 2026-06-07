# 命令参考

本页列出 Nudge 公开 runtime 中最常用、最适合写进自动化流程的命令。所有会写入 Apple 应用或本地 SQLite 的路径，都应先用 dry-run 或只读输出确认。

## 安全边界

- 真实写入 Apple Calendar、Reminders、Notes 或 Clock 前，先运行对应 dry-run 命令。
- 使用 private overlay 时，同一轮命令应使用同一个 `--config`、`NUDGE_CONFIG` 或 `NUDGE_STATE_DIR`，避免读写不同 SQLite。
- 不直接手写 SQL 修改 Nudge 状态；优先使用 `nudge log`、`nudge agent status`、`nudge reminders sync-completed`、`nudge daily sync` 等命令。
- 医疗、用药、付款、证件、出行、家庭课程等高风险提醒，应先人工确认。

### 公开仓安全 smoke 命令

下面这些命令可以在公开仓库和临时 `HOME` 中作为 smoke check 执行；它们只读取帮助、输出 JSON、运行 Skill deterministic 规则或执行只读文档审计，不会真实写入 Apple apps，也不应触碰真实用户 HOME。

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

`nudge doctor --json` 可能因为本机没有 `config.toml`、LLM key 或 Apple 读取权限而返回非零状态；这仍是可解析的诊断输出。`--llm-ping` 会主动发起 provider 调用，不属于默认 smoke。

## 核心命令

### `nudge doctor`

检查本机配置、LLM key 和 macOS 应用权限。

```bash
nudge doctor
nudge doctor --json
nudge doctor --llm-ping --json
nudge --config /path/to/private/config.toml doctor
```

适合在首次安装、切换 private overlay、修复 Apple 权限后运行。`--json` 输出可给脚本或 agent 读取。`--llm-ping` 会主动发起一次很小的 provider 调用，默认不启用。

### `nudge daily sync`

同步每日 Health、Reminders 和文档审计信号，并显示仍需要人工处理的事项。

```bash
nudge daily sync --json
nudge daily sync --date 2026-06-06 --json
nudge daily sync --from 2026-06-01 --date 2026-06-06 --json
nudge daily sync --apply --json
```

默认是 dry-run，不写 SQLite。加 `--apply` 后才写入本地状态。Health 区间使用 `--health-from` 包含起始日、`--health-to` 不包含结束日。

### `nudge review weekly`

生成周复盘；可选让 AI 给出调整建议。

```bash
nudge review weekly
nudge review weekly --config /path/to/private/config.toml
nudge review weekly --adapt --dry-run
nudge review weekly --config /path/to/private/config.toml --adapt --dry-run
nudge review weekly --adapt --apply
```

`--dry-run` 只预览调整计划；`--apply` 会在确认后应用安全调整。

### `nudge mcp serve`

通过 stdio 提供 MCP JSON-RPC 服务，让本地 agent 调用 Nudge 工具。

```bash
nudge mcp serve
nudge mcp serve --config /path/to/private/config.toml
```

该命令的 stdout 只保留给 JSON-RPC 消息，不应把普通日志写到 stdout。

### `nudge agent apply`

从另一个本地 agent 或自动化工具读取结构化 Apple action 请求。

```bash
nudge agent apply --file request.json --dry-run --json
nudge agent apply --file request.json --config /path/to/private/config.toml --json
```

先用 `--dry-run` 检查即将创建的 Apple 项目；真实执行时仍应使用 private overlay 配置。

### `nudge agent status`

从另一个本地 agent 或自动化工具更新本地 action 状态。

```bash
nudge agent status --file status.json --dry-run --json
nudge agent status --file status.json --config /path/to/private/config.toml --json
```

状态回写必须和创建 action 时使用同一套配置或状态目录。

### `nudge daemon`

本地队列 runtime，用于在后台处理 Apple 写入请求，不经过 LLM。

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

常见维护路径还包括 `nudge daemon recover`、`nudge daemon retry` 和 `nudge daemon launchd status`。

### `nudge skills`

验证和应用确定性的 Skill Spec 规则。

```bash
nudge skills validate skill.yaml --json
nudge skills import skill.yaml --json
nudge skills dry-run skill.yaml --context context.json --json
nudge skills apply skill.yaml --context context.json --json
```

`dry-run` 用于预览候选动作，不写 Apple 应用；`apply` 才会应用 personalization 和 adaptation 规则。

### `nudge health import`

解析 Apple Health export ZIP 或 HealthExport JSON。

```bash
nudge health import export.zip --json
nudge health import export.zip --from 2026-06-01 --to 2026-06-07 --json
nudge health import export.zip --config /path/to/private/config.toml --apply --json
nudge health import export.zip --apply --json
```

默认只解析并报告聚合数量，不写 SQLite。`--from` 包含起始日期，`--to` 不包含结束日期。ZIP 中的 workout route GPX 会计入 `ignored_route_files`，但不会导入路线轨迹。

### `nudge habits`

查看习惯 streak 或记录一次习惯完成。

```bash
nudge habits --config /path/to/private/config.toml
nudge habits --config /path/to/private/config.toml log reading
```

记录习惯会写入本地 SQLite；使用 private overlay 时应显式传入同一个配置。

### `nudge dogfood weekly`

生成只读周度 dogfood 报告，可选保存到当前 state dir。

```bash
nudge dogfood weekly --config /path/to/private/config.toml
nudge dogfood weekly --config /path/to/private/config.toml --save
nudge dogfood weekly --config /path/to/private/config.toml --json
```

`--save` 会把报告写入当前 state dir 的 `dogfood/YYYY-WW.md`；`--json` 和 `--export-json` 适合发布前自动化检查。

## Skills 端到端示例

下面的流程只使用公开仓库和临时目录，可以在没有 private overlay、没有真实 Apple 写入权限的环境里运行。`skills apply` 只应用 deterministic personalization / adaptation 规则并输出变换后的 Skill；`skills dry-run` 才生成候选 Calendar actions，仍不会写入 Apple apps。

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

在上面的 context 中，builtin Skill 会命中 `heavy_meeting_week`、`morning_focus` 和 `too_many_distractions`：会议多会减少每周 session 数，上午精力好会偏向早间时间，最近分心过多会把默认 session 时长降到 50 分钟。`profile.preferred_time` 仍可覆盖最终 dry-run action 的开始时间，所以候选 action 会从 `2026-06-01 08:30` 开始。

自定义 Skill 也可以完整走 validate → import → dry-run → delete。这里仍使用临时 `HOME`，只写入 `$tmpdir/home/.nudge/skills`，不会触碰真实用户目录。

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

## Runtime log 截断和密钥边界

Runtime log 写到当前 state dir 下的 `logs/nudge-runtime.jsonl`。如果使用 private overlay，应通过同一个 `--config`、`NUDGE_CONFIG` 或 `NUDGE_STATE_DIR` 读取对应日志；不要把该日志提交到公开仓库。

日志入口会先做清洗再写入：

- 字符串字段最多保留 2000 个字符。
- 数字和布尔值原样保留。
- 列表最多保留前 10 项，每项转换为字符串后最多 1000 个字符。
- 其他对象会转换为字符串后最多保留 2000 个字符。
- `log_error_report` 只记录结构化 code、message、detail 和 next steps，不写 raw provider output 或 raw AppleScript output。

这些截断规则用于降低日志体积和误存敏感输出的风险，但不是密钥管理边界。API key、OAuth token、账号密码、私钥、Health export、个人计划和机器绝对私有路径仍必须留在 private overlay、环境变量或未提交的本机配置中；公开仓库文档和示例不得包含真实密钥。

## Daemon 平台边界

Nudge 的 daemon 是 macOS-first 的本地 queue runtime。`nudge daemon enqueue`、`queue`、`status`、`recover`、`retry` 等 SQLite 队列命令可以用于排查和测试；真正执行 Apple 写入仍依赖 macOS Apple apps 和对应权限。

`nudge daemon launchd ...` 和 graphical control app 只支持 macOS。非 macOS 环境下，launchd status 会报告 unsupported platform；项目不默认实现 Linux / Windows 的 Apple 写入替代层。跨平台环境可以运行文档构建、测试、Skill dry-run 和 JSON 预览，但应把真实 Calendar / Reminders / Notes / Clock 执行留给 macOS 主机。

## 发布和站长验证

文档站使用 GitHub Pages 和 VitePress：

- GitHub Pages 应使用 GitHub Actions workflow 作为构建来源。
- 站点地址是 `https://zenine.github.io/nudge/`。
- sitemap 地址是 `https://zenine.github.io/nudge/sitemap.xml`。
- Google / Bing verification token 应写入 `docs/.vitepress/verification-meta.mts`，不要写入密钥或账号凭证。

更新站长验证 token 后，运行：

```bash
python3 scripts/check-i18n-drift.py
cd docs && npm run docs:build
scripts/verify.sh
```
