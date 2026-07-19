# Nudge 命令参考

本文面向公开仓库用户，概览 `nudge` 当前 CLI 的主要子命令、写入边界和 macOS/Apple 权限要求。内容基于 `nudge/cli.py` 与 `nudge/commands/*.py` 中的 Click 注册和帮助字符串整理。

## 安全约定

- **默认先 dry-run**：凡是会创建或修改 Apple Calendar、Reminders、Notes、Clock 或本地 SQLite 状态的命令，建议先使用 `--dry-run`、不带 `--apply`，或仅查看 `--json` 输出。
- **Apple 写入需要 macOS 权限**：真实写 Apple Calendar/Reminders/Notes/Clock 的命令需要在 macOS 上运行，并授权相应 App 的自动化/访问权限。可先运行 `nudge doctor` 检查。
- **本地 SQLite 是可写状态**：Nudge 会把计划、动作、状态、习惯、健康汇总、队列、幂等请求等写入本地 SQLite。涉及 `--apply`、`start`、`adapt --apply`、`log`、`agent status`、`daemon enqueue/run`、`db restore` 等命令前请确认目标状态目录。
- **MCP/agent 是本地调用入口**：`agent apply`、`mcp serve` 和 `daemon run` 可代表其他本地 agent 执行结构化动作。真实 Apple 写入应先 dry-run；`daemon enqueue` 以 `request_id` 作为队列幂等键（直连 agent/MCP 写入的 `request_id` 仅作 trace，不做 replay 去重）；启用 `[security.local_auth]` 后还需在请求 JSON/tool arguments 中提供 `auth_token`。
- **Apple Health 导入只信任自己的导出**：`health import` / `daily sync --health` 可解析 Apple Health 导出 ZIP 或 HealthExport JSON。请只导入自己可信来源的文件。
- **裸自然语言等价于 `do`**：`nudge "自然语言"` 会被 CLI 自动转成 `nudge do "自然语言"`。从 stdin 输入且未指定子命令时，也会走 `do`。

## Quick table

| 命令 | 用途 | Apple 写入 | 本地状态写入 | macOS/Apple 权限 |
| --- | --- | --- | --- | --- |
| `nudge do` / `nudge "..."` | 将自然语言解析为日历/提醒/备忘录/闹钟动作 | 是，除非 `--dry-run` | 通常会记录动作状态 | 真实写入需要对应 Apple App 权限；解析需要 LLM 配置 |
| `nudge log` | 标记动作 done/skipped/partial/deferred/blocked 或解析反馈 | 可能会同步完成 Apple Reminders | 是，除非 `--dry-run` | 同步提醒完成时需要 Reminders 权限 |
| `nudge check-in` | `log` 别名 | 同 `log` | 同 `log` | 同 `log` |
| `nudge feedback` | 查看待反馈项、批量应用 JSON，或在 TTY 中完成结构化反馈访谈 | 否 | `apply` 和 `interview` 写 SQLite；访谈在最终统一确认后原子写入 | `interview` 的可选 GPT 追问需要 LLM 配置；不调用 Apple adapter |
| `nudge skills` | 管理、验证、预览、启动和适配 Skill | `start`、`adapt --apply` 会写 Apple；dry-run/validate/show/list 不写 | `start`、`adapt --apply`、create/update/delete 会写本地状态或本地 skill 存储 | Apple 写入路径需要 Calendar/Reminders 权限 |
| `nudge trainer` | 健身计划入口，默认走 strength Skill runtime | `plan` 真实执行会写 Apple；`--dry-run` 不写 | 计划与完成记录写 SQLite | Apple 写入需要权限；旧 LLM 模式需要 LLM 配置 |
| `nudge doctor` | 检查配置、LLM key、Apple App 访问 | 否 | 否 | 在 macOS 上检查 Calendar/Reminders/Mail/Notes/Clock 访问 |
| `nudge docs` | 文档审计 | 否 | 否 | 不需要 Apple 权限 |
| `nudge daily` | 每日 Health + Reminders 同步和待处理汇总 | 不创建 Apple 项；会读取 Reminders | `sync --apply` 写 SQLite | Reminders 同步需要 Reminders 权限；Health 导入需要本地导出文件 |
| `nudge review` | 生成 daily/weekly 复盘，可请求适配建议 | `--apply` 可能写 Calendar；`--dry-run` 不写 | 读取 SQLite，适配应用时可能写状态 | 适配写入需要 Calendar 权限；`--adapt` 需要 LLM 配置 |
| `nudge health` | 导入/查看 Apple Health 汇总 | 否 | `import --apply` 写 SQLite | 不直接需要 Apple 权限；需要本地 Health 导出文件 |
| `nudge habits` | 查看 streak 或记录今日习惯 | 否 | `habits log <name>` 写 SQLite | 不需要 Apple 权限 |
| `nudge schedule` | 查找本周日历空档 | 否 | 否 | 读取 Calendar，需要 Calendar 权限 |
| `nudge reminders` | 将 Apple Reminders 状态同步回 Nudge | `backfill-ids --apply` 会更新 Reminders；`sync-completed --apply` 不创建新提醒但会写本地状态 | `--apply` 写 SQLite | 读取/更新 Reminders 需要 Reminders 权限 |
| `nudge agent` | 本地 agent 结构化 Apple 动作入口 | `apply` 真实执行会写 Apple；`--dry-run` 不写 | `apply`/`status` 真实执行写 SQLite（actions/tracking） | Apple 写入需要对应权限 |
| `nudge mcp` | 本地 MCP stdio server | 工具调用 `apply_apple_actions` 真实执行会写 Apple | 状态回写工具可写 SQLite | 由 MCP client 触发；Apple 写入需要权限 |
| `nudge daemon` | 本地队列运行时、launchd 和健康辅助 app | `run` 处理 `agent.apply` 队列时可能写 Apple | 队列、恢复、重试、运行状态写 SQLite；launchd/app 子命令写本机用户级文件 | launchd/app 仅 macOS；Apple 写入取决于队列内容 |
| `nudge db` | SQLite 备份、导出、恢复 | 否 | `restore --yes` 替换当前 SQLite；backup/export 写输出文件 | 不需要 Apple 权限 |
| `nudge briefing` | 生成 morning/evening briefing | 否；`--notify` 发本地通知 | 读 SQLite | `morning` 会读取 Calendar/Reminders/Mail，macOS 上可能需要对应读取权限；`evening` 会读取 Calendar，macOS 上可能需要 Calendar 读取权限；`--notify` 额外需要通知/terminal-notifier 权限 |
| `nudge chat` | 交互式对话，响应中可包含动作 JSON | 可能在确认后执行动作 | 可能通过执行动作写 SQLite | 执行动作时需要对应 Apple 权限；需要 LLM 配置 |
| `nudge dogfood` | 生成 Nudge 自身周报 | 不写 Apple | `weekly --save` 写本地报告文件；`--export-json` 写指定文件 | `weekly` 会运行 doctor 式只读检查，可能读取 Calendar/Reminders/Notes/Mail/Clock 状态；macOS 上可能触发或需要 Apple App 读取权限 |
| `nudge failures` | 查看 overdue/blocked/unexplained 动作 | 否；`--notify` 发本地通知 | 否 | `--notify` 需要 macOS 通知能力 |

## 分节说明

### `nudge do` / `nudge "自然语言"`

用途：解析一段自然语言或文件内容，并创建 Calendar 事件、Reminders 提醒、Notes 备忘录或 Clock 闹钟。

常用形式：

```bash
nudge --dry-run "明天下午 3 点项目同步"
nudge do --dry-run --json "明天提醒我复盘"
nudge do --file plan.txt
```

要点：

- `nudge "自然语言"` 等价于 `nudge do "自然语言"`。
- `--dry-run` 只预览，不创建 Apple 项。
- `--json` 输出稳定 JSON，便于脚本调用。
- 真实执行会根据解析结果写 Apple App，并通常在本地 SQLite 记录动作状态。

### `nudge log`

用途：快速更新一个 pending action 的状态，支持 `done`、`skipped`、`partial`、`deferred`、`blocked`、`parse`。

示例：

```bash
nudge log done --metric effort=8
nudge log skipped --reason no_time --next-action reschedule "会议冲突"
nudge log parse "今天训练完成，强度 8"
```

要点：

- 默认按 `--id`、`--match` 或最新 pending item 匹配动作。
- `--dry-run` 只预览解析和匹配，不更新 SQLite。
- `--metric key=value` 可重复传入，用于记录数值指标。
- 对提醒类动作，`log done` 可能 best-effort 同步 Apple Reminders 完成状态。

### `nudge check-in`

用途：`nudge log` 的别名，参数和行为一致。

```bash
nudge check-in partial --reason low_energy --next-action reduce
```

### `nudge feedback`

用途：查看当天待反馈项、应用结构化 JSON，或在交互式终端中一次处理一批逾期反馈。

```bash
nudge feedback today
nudge feedback apply --dry-run --file feedback.json
nudge feedback interview
nudge feedback interview --scope all-overdue --limit 20
```

要点：

- `interview` 默认选择本周已逾期超过 24 小时的 pending/created action，单批默认 20 条、最多 50 条。
- 固定核心题覆盖结果、原因、下一步与文字说明；每条可有至多 3 个 GPT 可选追问。调用超时、失败或响应不合法时自动降级为核心题。
- 高风险分类同时检查标题与 `reminder_list` 等本地上下文；家庭列表、家庭课程、付款、证件和出行事项不预选，并在发送前显示 provider、model 和字段，用户可整组关闭 GPT 追问。
- 所有答案先保存在内存；最终确认页按风险组显示原时间、核心答案、GPT 问答、附加文字、Reminder 提示和睡眠派生原因，统一确认后才以单个 SQLite 事务写入。取消、冲突或写入错误不会留下半批状态。
- 10 秒 GPT 调用同时关闭 Nudge 外层和 provider SDK 内建重试；失败后立即降级为核心题。
- 命令只写 Nudge SQLite，不直接调用 Apple Calendar、Reminders 或 Notes adapter。

### `nudge skills`

用途：验证、预览、启动和适配确定性的 Skill Spec。

子命令：

- `skills list`：列出内置和自定义 Skills。只读。
- `skills show <skill>`：展示内置、自定义或文件中的 Skill。只读。
- `skills validate <skill>`：验证 Skill YAML/JSON 或 Skill id。只读。
- `skills apply <skill> --context context.json`：应用个性化/适配规则，输出结果；不写 Apple。
- `skills dry-run <skill> --context context.json --weeks N`：预览候选动作；不写 Apple。
- `skills status`：查看活跃 Skill 实例和进度；只读 SQLite。
- `skills start <skill>`：创建实例并写入首批动作；`--dry-run` 不创建实例、不写 Apple。
- `skills adapt <plan-id>`：根据真实追踪历史预览下一阶段；只有 `--apply` 才写入后续动作并推进 cursor。
- `skills create/update/delete`：写入或删除本地自定义 Skill 存储，不写 Apple。

示例：

```bash
nudge skills list
nudge skills dry-run strength-basics-12w --context context.json --weeks 1
nudge skills start strength-basics-12w --dry-run
nudge skills adapt <plan-id> --apply
```

### `nudge trainer`

用途：健身计划入口。`trainer plan` 默认使用内置 strength Skill runtime；旧版 LLM 周训练计划可通过 `--legacy-llm` 显式启用。

子命令：

- `trainer plan`：创建训练计划；`--dry-run` 只预览，`--yes` 跳过确认。
- `trainer log <message>`：记录训练完成反馈。
- `trainer status`：查看当前训练计划进度。

示例：

```bash
nudge trainer plan --dry-run
nudge trainer plan --yes --weeks 1
nudge trainer log "跑了 5 公里，感觉不错"
nudge trainer status
```

### `nudge doctor`

用途：只读诊断本地配置、LLM key 和 macOS App 访问。

```bash
nudge doctor
nudge doctor --json
```

要点：不写 Apple、不写 SQLite；在 macOS 上会检查 Calendar、Reminders、Mail、Notes、Clock 等访问能力。

### `nudge docs`

用途：维护项目文档。目前提供只读审计。

```bash
nudge docs audit
nudge docs audit --json
nudge docs audit --root . --stale-days 60
```

要点：`docs audit` 报告 stale、broken 或低价值文档，不修改文件。

### `nudge daily`

用途：每日维护工作流，目前核心是 `daily sync`。

```bash
nudge daily sync --json
nudge daily sync --apply --date 2026-07-04
nudge daily sync --health export.zip --health-from 2026-07-01 --health-to 2026-07-05
```

要点：

- 汇总 Health 导入、Reminders 完成同步和待处理/过期动作。
- 默认预览；`--apply` 才写 SQLite。
- `--no-health` 可跳过 Health 导入。
- 读取 Reminders 需要 Reminders 权限；解析 Health 需要本地导出文件。

### `nudge review`

用途：生成 daily 或 weekly 复盘报告，并可生成适配建议。

```bash
nudge review daily
nudge review weekly --adapt --dry-run
nudge review weekly --adapt --apply
```

要点：

- `--adapt` 生成 AI adaptation suggestions。
- `--dry-run` 预览适配计划，不写 Calendar。
- `--apply` 在确认后应用安全适配计划，可能写 Calendar 和本地状态。

### `nudge health`

用途：导入和查看本地 Apple Health 汇总。

子命令：

- `health import <path>`：解析 Apple Health export ZIP 或 HealthExport JSON。默认 dry-run；`--apply` 写 SQLite。
- `health daily`：查看已导入的健康摘要和 workout metadata。只读。

示例：

```bash
nudge health import export.zip --from 2026-07-01 --to 2026-07-05
nudge health import export.zip --apply --json
nudge health daily --from 2026-07-01 --json
```

### `nudge habits`

用途：查看习惯 streak，或记录某个习惯今天完成。

```bash
nudge habits
nudge habits log reading
```

要点：查看 streak 只读；`habits log <habit_name>` 写本地 SQLite，不写 Apple。

### `nudge schedule`

用途：读取日历并查找本周空闲时段；可显式选择候选 slot 后创建 Calendar 事件。

```bash
nudge schedule "找2小时深度工作时间"
nudge schedule "深度工作" --duration 120 --json
nudge schedule "深度工作" --duration 120 --book --slot 1 --title "Deep Work" --dry-run --json
nudge schedule "深度工作" --duration 120 --book --slot 1 --title "Deep Work" --yes
```

要点：

- 默认只读 Calendar，并按请求中的 `2小时` / `90分钟` / `1.5h` 等时长过滤空档；也可用 `--duration <minutes>` 明确指定。
- `--book` 必须配 `--slot N`，避免 Nudge 自动替你挑时间。
- `--dry-run` 只展示将创建的 Calendar event，不写 Apple。
- 真实 `--book --yes` 会写 Calendar，并把 action 记录到本地 SQLite。
- 读取和写入 Calendar 都需要 macOS Calendar 权限。

### `nudge reminders`

用途：把 Apple Reminders 的状态同步回 Nudge。

子命令：

- `reminders sync-completed`：同步一个或多个 Apple Reminders 列表。新 action 会记录目标列表，并在同步和 ID backfill 前先按已知列表归属过滤；旧 action 没有列表字段时仍会进入明确匹配流程以保持兼容。所有 action 都必须在当前列表找到明确完成匹配后才会写回，不能仅凭“该列表里不存在”推断完成，因此移动列表不会造成误完成。睡眠派生完成会使用每条 action 自己记录的目标列表。`--apply` 写 SQLite，并可能静默后续睡眠提醒。
- `reminders backfill-ids`：为旧 Apple Reminders 附加稳定 Nudge ID。`--apply` 会写 Apple Reminders 和 SQLite。

示例：

```bash
nudge reminders sync-completed --date 2026-07-04 --json
nudge reminders sync-completed --list Tasks --list Health --list GPT --json
nudge reminders sync-completed --apply
nudge reminders backfill-ids --from 2026-07-01 --to 2026-07-05 --apply
```

未传 `--list` 时，优先读取 `[reminders].sync_lists`；未配置该数组时回退到 `[general].default_reminder_list`。`daily sync` 使用同一规则。

### `nudge agent`

用途：给其他本地 agent/自动化工具提供结构化 Apple action relay。

子命令：

- `agent apply`：从 stdin 或 `--file` 读取结构化请求并执行 Apple actions。`--dry-run` 预览且不创建 Apple 项。
- `agent status`：从 stdin 或 `--file` 读取 action-status 回写请求。`--dry-run` 不写 SQLite。

示例：

```bash
nudge agent apply --dry-run --file request.json --json
nudge agent apply --file approved-request.json --json
nudge agent status --file status.json --json
```

要点：`agent apply` 直连路径不做 `request_id` replay 去重（`request_id` 仅作调用方 trace），避免重复写 Apple 靠 dry-run 预览 + 只提交已批准 payload；需要幂等入队时改用 `daemon enqueue`（以 `request_id` 为队列幂等键）。

### `nudge mcp`

用途：以本地 MCP stdio server 形式暴露 Nudge 工具。

```bash
nudge mcp serve
nudge mcp serve --config config.toml
```

要点：

- stdout 保留给 JSON-RPC 消息。
- 主要工具包括结构化 Apple 写入、状态回写、doctor diagnostics、Notes 安全列表读取。
- 真实 Apple 写入由 MCP client 触发；仍应先 dry-run，并使用稳定 `request_id`。启用 `[security.local_auth]` 后，`apply_apple_actions` 和 `report_action_status` 的 arguments 还必须包含 `auth_token`。

### `nudge daemon`

用途：本地队列运行时，在无 LLM 的 daemon loop 中处理结构化请求；也包含 launchd 和图形健康辅助 app 管理。

常用子命令：

- `daemon enqueue --type agent.apply|agent.status`：把请求放入本地队列，写 SQLite。
- `daemon run`：处理队列；队列内容是 `agent.apply` 时可能写 Apple。
- `daemon queue/status/health`：查看队列和健康状态。
- `daemon recover/retry`：恢复 stale running rows 或重试 failed/dead-letter 请求，写 SQLite。
- `daemon launchd install/start/stop/restart/uninstall/status`：管理 macOS LaunchAgent。
- `daemon app install/open/status/uninstall`：管理可点击的 macOS daemon health helper app。

示例：

```bash
nudge daemon enqueue --type agent.apply --file request.json --json
nudge daemon run --once --verbose
nudge daemon health --json
nudge daemon launchd status --json
```

要点：launchd/app 子命令是 macOS 专用，并会写用户级 plist/app 文件；是否写 Apple 取决于队列请求本身。

### `nudge db`

用途：维护本地 SQLite 数据库。

```bash
nudge db backup --output backup.db
nudge db export --output dump.sql
nudge db restore backup.db --yes
```

要点：

- `backup` 使用 SQLite online backup 复制 `.db`。
- `export` 写 portable SQL dump。
- `restore --yes` 会替换当前数据库，并在恢复前创建备份；这是本地状态高风险写操作。

### `nudge briefing`

用途：生成 morning/evening briefing。

```bash
nudge briefing morning
nudge briefing evening --notify
```

要点：读取本地状态并渲染摘要。`briefing morning` 会读取 Calendar、Reminders、Mail；macOS 上可能需要对应读取权限。`briefing evening` 会读取 Calendar；macOS 上可能需要 Calendar 读取权限。`--notify` 会发送 macOS 本地通知，额外需要通知/terminal-notifier 权限。

### `nudge chat`

用途：启动多轮交互式对话。

```bash
nudge chat
```

要点：需要 LLM 配置；对话响应可能包含可执行动作 JSON，执行动作时仍遵守 Apple 写入权限和确认边界。

### `nudge dogfood`

用途：查看 Nudge 自身本地使用周报。

```bash
nudge dogfood weekly
nudge dogfood weekly --save --note "本周重点验证 daily sync"
nudge dogfood weekly --export-json dogfood.json
```

要点：默认不写 Apple；`--save` 写本地周报 Markdown，`--export-json` 写指定 JSON 文件。`weekly` 会运行 doctor 式只读检查，可能读取 Calendar、Reminders、Notes、Mail、Clock 状态；macOS 上可能触发或需要 Apple App 读取权限。

### `nudge failures`

用途：只读查看 overdue、blocked、unexplained actions。

```bash
nudge failures
nudge failures --overdue-hours 48 --limit 20 --json
nudge failures --notify
```

要点：不修改 SQLite；`--notify` 在存在问题时发送 macOS 本地通知。
