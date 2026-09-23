# Nudge 命令参考

本文是 `nudge` CLI 的完整参考：既面向直接在终端使用 Nudge 的人，也面向需要从其他项目、脚本、Agent 或 launchd 稳定调用 Nudge 的集成方。内容基于 `nudge/cli.py` 与 `nudge/commands/*.py` 中的 Click 注册和帮助字符串整理。

文中的 `<repo>` 是一个占位符，表示你本机 Nudge 仓库（或安装底座）的根目录；`<repo>/bin/nudge` 是固定路径 wrapper，适合被其他项目硬编码调用。请按自己的实际路径替换，本文不使用任何具体机器上的绝对路径。

相关文档：[配置说明](configuration.md)、[LLM 配置](llm.md)、[Skill Spec](skill-spec.md)、[Daemon Runbook](daemon-runbook.md)、[MCP 安全策略](mcp-security.md)、[非 macOS 环境说明](non-macos.md)、[架构说明](architecture.md)。

## 安装与入口

### 快速安装

在 Nudge 仓库根目录执行：

```bash
cd <repo>
scripts/install_cli.sh
```

如果希望一条命令完成初次环境准备，可以用引导脚本：

```bash
scripts/bootstrap_mac.sh
```

该脚本会创建项目内 `.venv`、把依赖安装到隔离环境，并安装 `~/.local/bin/nudge` 指向固定路径 wrapper。使用者不需要手动激活虚拟环境；`bin/nudge` 会优先使用项目内 `.venv/bin/python`，缺失时才回退系统 `python3`。在 Apple Silicon Mac 上，脚本会优先选择 Homebrew 的 `python3`，并拒绝用 Rosetta / x86_64 Python 创建 `.venv`；检测到已有 `.venv` 是 Intel 环境时会备份后重建。

固定路径 wrapper 支持被 symlink 到其他位置后继续解析到真实仓库根目录。

### 自动化定时任务（launchd）

如果希望直接配置本机自动化（默认每天早 7 点执行 morning briefing、7:15 执行 daily sync、晚 21:30 执行 evening briefing）：

```bash
scripts/bootstrap_launchd.sh
scripts/bootstrap_launchd.sh status
scripts/bootstrap_launchd.sh uninstall
```

该脚本会安装：

- morning / evening 两个 `briefing` 任务；
- `com.nudge.daily-sync` 每日维护任务（`nudge daily sync --apply --json`，包含 docs audit）；
- `com.nudge.agent` 长驻任务（`nudge daemon run`）。

daily sync 时间可用 `NUDGE_DAILY_SYNC_HOUR` / `NUDGE_DAILY_SYNC_MINUTE` 调整；它只通过 `daily sync` 写入本地 Nudge 状态，不直接移动、删除或重写文档。

如果只需要管理 `com.nudge.agent` 这个无头 daemon（不改早晚 briefing 定时任务），用 CLI 即可，见 [`nudge daemon`](#nudge-daemon)。

### 推荐调用形式

```bash
# 全局命令，适合人在任意项目目录手动调用
nudge "明天下午3点开会"

# 固定路径，适合其他项目、Agent、launchd、cron 或脚本稳定调用
<repo>/bin/nudge "明天下午3点开会"

# 机器可读 JSON，适合其他项目用 subprocess 解析 stdout
<repo>/bin/nudge do --json "明天下午3点开会"

# 结构化 Agent 中转接口：不调用 LLM，直接执行其他 agent 提交的 Apple actions
<repo>/bin/nudge agent apply --file request.json --json
```

## 调用约定

- 默认自然语言输入等价于 `do` 子命令：`nudge "明天下午3点开会"` 等价于 `nudge do "明天下午3点开会"`。从 stdin 输入且未指定子命令时同样走 `do`。
- 默认自然语言入口会执行写入：日历事件写入 Apple Calendar，提醒事项写入 Apple Reminders。结构化 `agent apply` / MCP 入口还支持写入 Apple Notes 和 Clock。
- 预览模式使用 `--dry-run`，只解析和展示 action，不写入 Apple 应用。
- `--json` 让 stdout 只包含一段稳定 JSON；人类诊断和权限错误仍输出到 stderr。

```bash
nudge --dry-run "明天下午3点开会"
nudge --json --dry-run "明天下午3点开会"
nudge --file message.txt
cat message.txt | nudge
nudge --config path/to/config.toml "下周二下午2点项目会"
```

## 安全约定

- **默认先 dry-run**：凡是会创建或修改 Apple Calendar、Reminders、Notes、Clock 或本地 SQLite 状态的命令，建议先使用 `--dry-run`、不带 `--apply`，或仅查看 `--json` 输出。
- **Apple 写入需要 macOS 权限**：真实写 Apple Calendar/Reminders/Notes/Clock 的命令需要在 macOS 上运行，并授权相应 App 的自动化/访问权限。可先运行 `nudge doctor` 检查。
- **本地 SQLite 是可写状态**：Nudge 会把计划、动作、状态、习惯、健康汇总、队列、幂等请求等写入本地 SQLite。涉及 `--apply`、`start`、`adapt --apply`、`log`、`agent status`、`daemon enqueue/run`、`db restore` 等命令前请确认目标状态目录。
- **MCP/agent 是本地调用入口**：`agent apply`、`mcp serve` 和 `daemon run` 可代表其他本地 agent 执行结构化动作。真实 Apple 写入应先 dry-run；`daemon enqueue` 以 `request_id` 作为队列幂等键（直连 agent/MCP 写入的 `request_id` 仅作 trace，不做 replay 去重）；启用 `[security.local_auth]` 后还需在请求 JSON/tool arguments 中提供 `auth_token`。
- **Apple Health 导入只信任自己的导出**：`health import` / `daily sync --health` 可解析 Apple Health 导出 ZIP 或 HealthExport JSON。请只导入自己可信来源的文件。
- **裸自然语言等价于 `do`**：`nudge "自然语言"` 会被 CLI 自动转成 `nudge do "自然语言"`。
- **私有配置优先用 `NUDGE_CONFIG` 统一入口**：显式 `--config/-c` 会覆盖环境变量；但部分命令没有 `--config`，或会在根命令阶段先初始化 LLM。若使用私有 `[llm]`、`secrets_path` 或 `[state].dir`，建议在当前 shell 设置 `NUDGE_CONFIG` 后再运行。
- **计划驱动写入必须文档确认先行**：凡是根据长期计划、周计划、Skill 或复盘结果批量生成 Calendar / Reminders / Clock / Notes action，必须先更新或生成对应的人类可读文本计划 / 变更说明，明确日期范围、特殊日历、目标、降级规则和 App 分层；用户确认文本后才进入结构化 action dry-run，dry-run 再确认后才能真实写入。不能先写 Reminders / Calendar，再事后回补计划说明。
- **长期计划采用滚动窗口**：6 个月目标、阶段目标和安全边界保留在文档 / YAML 中，Apple 应用默认只写未来 1 周；约束稳定时可扩展到 2 周。不要把整月、整阶段或 6 个月计划一次性批量写入 Apple 应用。

## 命令总览

| 命令 | 用途 | Apple 写入 | 本地状态写入 | macOS/Apple 权限 |
| --- | --- | --- | --- | --- |
| `nudge do` / `nudge "..."` | 将自然语言解析为日历/提醒/备忘录/闹钟动作 | 是，除非 `--dry-run` | 通常会记录动作状态 | 真实写入需要对应 Apple App 权限；解析需要 LLM 配置 |
| `nudge log` | 标记动作 done/skipped/partial/deferred/blocked 或解析反馈 | 可能会同步完成 Apple Reminders | 是，除非 `--dry-run` | 同步提醒完成时需要 Reminders 权限 |
| `nudge check-in` | `log` 别名 | 同 `log` | 同 `log` | 同 `log` |
| `nudge feedback` | 查看待反馈项、批量应用 JSON、结构化反馈访谈、每周主观打分 | 否 | `apply`、`interview`、`weekly-score` 写 SQLite | `interview` 的可选 GPT 追问需要 LLM 配置；不调用 Apple adapter |
| `nudge profile` | 构建和查看本地长期画像 | 否 | `build` 写 SQLite `evaluations` | 不需要 Apple 权限；不调用 LLM |
| `nudge skills` | 管理、验证、预览、启动、适配和排期 Skill | `start`、`adapt --apply`、`schedule` 会写 Apple；dry-run/validate/show/list 不写 | `start`、`adapt --apply`、`schedule`、create/update/delete 会写本地状态或本地 skill 存储 | Apple 写入路径需要 Calendar/Reminders 权限 |
| `nudge trainer` | 健身计划入口，默认走 strength Skill runtime | `plan` 真实执行会写 Apple；`--dry-run` 不写 | 计划与完成记录写 SQLite | Apple 写入需要权限；旧 LLM 模式需要 LLM 配置 |
| `nudge doctor` | 检查配置、LLM key、Apple App 访问 | 否 | 否 | 在 macOS 上检查 Calendar/Reminders/Mail/Notes/Clock 访问 |
| `nudge docs` | 文档审计 | 否 | 否 | 不需要 Apple 权限 |
| `nudge daily` | 每日 Health + Reminders 同步和待处理汇总 | 不创建 Apple 项；会读取 Reminders | `sync --apply` 写 SQLite | Reminders 同步需要 Reminders 权限；Health 导入需要本地导出文件 |
| `nudge review` | 生成 daily/weekly 复盘，可请求适配建议 | `--apply` 可能写 Calendar；`--dry-run` 不写 | 读取 SQLite，`--adapt` 会写 `evaluations`，适配应用时可能写状态 | 适配写入需要 Calendar 权限；`--adapt` 需要 LLM 配置 |
| `nudge health` | 导入/查看 Apple Health 汇总 | 否 | `import --apply` 写 SQLite | 不直接需要 Apple 权限；需要本地 Health 导出文件 |
| `nudge habits` | 查看 streak 或记录今日习惯 | 否 | `habits log <name>` 写 SQLite | 不需要 Apple 权限 |
| `nudge schedule` | 查找本周日历空档，可选预订 | `--book --yes` 写 Calendar | `--book` 真实执行写 SQLite | 读取和写入 Calendar 都需要 Calendar 权限 |
| `nudge reminders` | 同步完成状态、只读对账缺失提醒，或回填旧 action 的外部 ID / 列表归属 | `reconcile-missing` 和 `backfill-lists` 永不写 Apple；`backfill-ids --apply` 会更新 Reminders；`sync-completed --apply` 的睡眠终止级联可能 best-effort 完成后续 Apple 睡眠提醒 | `reconcile-missing` 不写 SQLite；各子命令的 `--apply` 可写 SQLite；`backfill-lists` 只更新 `reminder_list` | 所有路径需读取 Reminders；`backfill-ids --apply` 及 `sync-completed --apply` 的睡眠终止级联需要 Reminders 更新权限 |
| `nudge agent` | 本地 agent 结构化 Apple 动作入口 | `apply` 真实执行会写 Apple；`--dry-run` 不写 | `apply`/`status` 真实执行写 SQLite（actions/tracking） | Apple 写入需要对应权限 |
| `nudge mcp` | 本地 MCP stdio server | 工具调用 `apply_apple_actions` 真实执行会写 Apple | 状态回写工具可写 SQLite | 由 MCP client 触发；Apple 写入需要权限 |
| `nudge daemon` | 本地队列运行时、launchd 和健康辅助 app | `run` 处理 `agent.apply` 队列时可能写 Apple | 队列、恢复、重试、运行状态写 SQLite；launchd/app 子命令写本机用户级文件 | launchd/app 仅 macOS；Apple 写入取决于队列内容 |
| `nudge db` | SQLite 备份、导出、恢复 | 否 | `restore --yes` 替换当前 SQLite；backup/export 写输出文件 | 不需要 Apple 权限 |
| `nudge briefing` | 生成 morning/evening briefing | 否；`--notify` 发本地通知 | 读 SQLite | `morning` 会读取 Calendar/Reminders/Mail；`evening` 会读取 Calendar；`--notify` 额外需要通知/terminal-notifier 权限 |
| `nudge chat` | 交互式对话，响应中可包含动作 JSON | 可能在确认后执行动作 | 可能通过执行动作写 SQLite | 执行动作时需要对应 Apple 权限；需要 LLM 配置 |
| `nudge dogfood` | 生成 Nudge 自身周报 | 不写 Apple | `weekly --save` 写本地报告文件；`--export-json` 写指定文件 | `weekly` 会运行 doctor 式只读检查，可能读取 Calendar/Reminders/Notes/Mail/Clock 状态 |
| `nudge failures` | 查看 overdue/blocked/unexplained/临近到期动作 | 否；`--notify` 发本地通知 | 否 | `--notify` 需要 macOS 通知能力 |

## 命令详解

### nudge do / nudge "自然语言"

用途：解析一段自然语言或文件内容，并创建 Calendar 事件、Reminders 提醒、Notes 备忘录或 Clock 闹钟。

```bash
nudge "明天下午3点开会"
nudge "下周二下午2点项目会，周三上午10点团队同步"
nudge "明天早上7点闹钟提醒我晨起称重"
nudge --dry-run "明天下午 3 点项目同步"
nudge do --dry-run --json "明天提醒我复盘"
nudge do --file plan.txt
```

要点：

- `nudge "自然语言"` 等价于 `nudge do "自然语言"`。
- `--dry-run` 只预览，不创建 Apple 项。
- `--json` 输出稳定 JSON，便于脚本调用。
- 真实执行会根据解析结果写 Apple App，并通常在本地 SQLite 记录动作状态。

#### do 的 JSON 契约

返回 JSON 顶层字段稳定包含：

```json
{
  "schema_version": "nudge.cli.v1",
  "ok": true,
  "dry_run": false,
  "total": 1,
  "succeeded": 1,
  "actions": [],
  "failures": [],
  "errors": []
}
```

- `schema_version`：当前固定为 `nudge.cli.v1`，用于外部脚本判断契约版本。
- `actions[]`：每个 action 的 `index`、`type`、`status`、`summary`、`scheduled_at`、`target`，真实 Calendar / Reminders / Clock 写入成功时还包含 `external_id`。Reminders 的 `external_id` 是 Nudge 生成的 `nudge://reminder/...`，会同时写入 Apple Reminder 的 URL 和备注标记，供后续精确完成 / 回收使用。
- `failures[]`：失败 action 的 `index`、`summary`、`error_code`、`error`。
- `errors[]`：全局或写入错误，包含 `code`、`message`、`detail`、`raw_error`。
- 部分写入失败时，JSON 仍可解析，`ok=false`，进程返回非 0。
- 输入文件、配置读取和 action 值校验失败也保持同一 stdout JSON 契约：本地输入/配置错误返回 `CLI_INPUT_ERROR`；LLM 产出的不可执行 action（例如时间格式错误、结束时间不晚于开始时间）返回 `LLM_ACTION_SCHEMA_INVALID`，不会进入 Apple 写入。

#### Apple backend 配置

Calendar / Reminders 默认通过 `nudge.apple.adapters` 选择 `native` backend。Apple Notes 通过 `native` AppleScript backend 写入指定文件夹，默认文件夹为 `Nudge`，只用于结构化 agent/MCP 中转，不从 Notes 读取正文；正文会先转换成人类可读的简单 Notes HTML。真实 Notes 写入的验收标准是手机或 Mac 备忘录中不再可见 raw Markdown 控制符，例如 `#`、`- [ ]`、三反引号或 `|---|` 表格分隔线。

`alarm` 可使用 `shortcuts` backend，通过 macOS Shortcuts bridge 调用 Clock：本机需要先创建名为 `Nudge Create Alarm` 的快捷指令。若快捷指令不存在，Nudge 会返回 `CLOCK_SHORTCUT_MISSING`，不会把闹钟伪装成已创建。不需要真实 Clock 闹钟的部署可设置 `[apple.clock] backend = "disabled"`，此时 doctor 通过，但 `alarm.create` 会明确失败。

```toml
[apple.calendar]
backend = "native"

[apple.reminders]
backend = "native"

[apple.notes]
backend = "native"

[apple.clock]
backend = "disabled"
# 如需真实 Clock 闹钟，改为：
# backend = "shortcuts"
# shortcut_name = "Nudge Create Alarm"
```

`ical` / `rem` / `ekctl` / MCP 仍是调研候选（见 [Apple adapter 调研](apple-adapter-survey.md)）；如果现在写进 config，`nudge doctor` 会 FAIL，`nudge do --json` 会返回 `APPLE_BACKEND_UNSUPPORTED`，避免半接入造成真实数据风险。

#### 家庭组路由

如果用户说“家庭组 / 全家 / 家人 / 所有人”这类目标，Nudge 会先按 `[family.routing.rules]` 的关键词规则决定接收人；未命中时可用 LLM 兜底；仍不确定时使用 `[family.routing].default`，默认是 `all`，也可配置为具体 member key 列表。启用 `llm_fallback=true` 时，会把最小化后的家庭事项内容、成员 key/display_name/role、路由规则摘要发送给配置的 LLM provider；隐私优先可设 `llm_fallback=false`，未命中关键词时只走 default。

用户明确指定单个成员（例如“提醒妈妈”“提醒孩子”）时，只创建该成员对应的提醒，不进入家庭组路由。

当前阶段不承诺 Apple Reminders 原生 assignment：Apple 公开 EventKit / Reminders 自动化接口没有稳定的 assignee 字段，Nudge 不依赖 iOS 私有指派能力。默认用成员化标题表达归属（例如 `妈妈：某项事务`）；如果不希望标题显示归属，可配置 `[family.routing.display] title_prefix=false`，并可配合 `body_assignee_note=true` 在提醒备注中写入负责人。`default = "all"` 会为每个家庭成员各创建一条 reminder；写入同一个 iCloud 共享列表时，到点通知仍取决于每位成员是否加入该列表以及各自设备的 Reminders 通知设置。共享列表本身不会把一条提醒的到点通知自动共享给所有成员，因此 Nudge 不把“写入共享列表”当作“所有人都被通知”的充分条件。

如果模型把家庭组目标解析成 calendar event，Nudge 不写 Calendar，而是按路由结果改写为对应成员的 Apple Reminders reminder。规则配置 `notification_policy = "prestart_only"` 时只保留开始前 30 分钟提醒；未配置时保留开始前 30 分钟和开始时各一条提醒。建议只在课程类等窄关键词规则上启用该策略，接送类等宽泛关键词规则不启用，避免误伤普通事件。`notification_policy` 当前只允许 `prestart_only`，未知值会在配置解析时明确报错。

`--json --dry-run` / JSON 输出会在 `actions[].routing` 包含 routing metadata，说明命中的是关键词规则、LLM 兜底还是 default fallback。普通人类可读 dry-run 不承诺显示完整 metadata。

### nudge log

用途：在 10 秒内把一个 pending action 标记为 `done`、`skipped`、`partial`、`deferred`、`blocked`，或用 `parse` 让 LLM 解析自然语言反馈，并让周报完成率马上反映这次记录。

```bash
nudge log done
nudge log done --metric effort=8
nudge log partial "只做了一半，明天继续"
nudge log deferred "今晚没时间" --reason no_time --next-action reschedule
nudge log blocked "等对方回复" --reason waiting_on_other --next-action keep
nudge log skipped --reason no_time --next-action reschedule "会议冲突"
nudge log parse "今天训练完成，强度 8"
nudge log parse "读书只读了一半，明天继续" --dry-run --json
nudge log done --id <action_id>
nudge log done --match "提交周报"
```

选择与写入规则：

- 不传 `--id` / `--match` 时，默认更新最近一个 `created` 或 `pending` action。
- 传 `--id` 可以更新指定 action，即使它已经是 `blocked` / `deferred`，用于补充 reason / next_action 或继续记录阻塞状态。
- `--match` 按 action summary 包含文本匹配；匹配到多个时会要求改用 `--id`。
- `--metric key=value` 可重复传入，用于记录数值指标。
- `--dry-run` 只预览解析和匹配，不更新 SQLite。
- 备注会用 `nudge.feedback.v1` 写入 action feedback，并标记 `source_type=subjective`；`--reason` 支持 `too_hard` / `no_time` / `conflict` / `low_energy` / `forgot` / `unclear` / `not_important` / `waiting_on_other`，`--next-action` 支持 `keep` / `reduce` / `split` / `reschedule` / `cancel`。
- `partial` 在 `review weekly` 中按 0.5 个完成计入完成率；`skipped` / `deferred` / `blocked` 计 0，但会进入未完成原因汇总。完成“关机流程 / 睡觉 / 上床 / 入睡”等睡眠终止型 reminder 后，同日晚于它的睡眠 reminder 会自动变成 `skipped_after_sleep`，不计失败、不要求补反馈。
- `done` 命中 reminder action 时，会读取默认 Reminders list，优先按 action 的 `external_id` 匹配 Apple Reminder 的 URL / 备注 `Nudge-ID` 后标记完成；旧数据没有 `external_id` 或 ID 匹配失败时，才回退到标题 + `scheduled_at` 精确匹配。JSON 输出会包含 `apple_reminder` 字段。该同步是 best-effort，失败时本地状态仍会写入，但输出会显示同步失败信息。为避免误清重复课程 / 每日任务，精确匹配不到唯一提醒时不会按标题批量完成。
- `parse` 会调用 LLM，把自然语言反馈解析成状态、备注、reason、next_action 和 metrics；代码层仍会校验取值。解析结果为 `done` 且命中 reminder action 时同样会尝试同步 Apple Reminders。
- `parse --dry-run --json` 只展示将更新的 action 和解析结果，不写 SQLite；脚本可读取 `ok`、`dry_run`、`parsed`、`action`、`feedback`。

若需要按 Apple Reminders 的真实 `completionDate` 批量回收，或静音睡后自动作废提醒，请使用 `nudge reminders sync-completed --apply`。

### nudge check-in

用途：`nudge log` 的别名，参数和行为一致。

```bash
nudge check-in done
nudge check-in partial --reason low_energy --next-action reduce
nudge check-in parse "今天没做力量训练，临时开会"
```

### nudge feedback

`feedback` 用于把晚报 / 今日计划里的 `created`、`pending` action 快速拉回本地 SQLite 状态，减少逐条敲 `nudge log ... --id ...` 的摩擦；另外提供每周主观打分入口。所有子命令都不读取或写入 Apple 应用。

#### feedback today 与 apply

```bash
nudge feedback today
nudge feedback today --json
cat feedback.json | nudge feedback apply --json
nudge feedback apply --dry-run --json --file feedback.json
```

`feedback today --json` 会输出今天仍待反馈的 action，以及可复制的 quick commands。`feedback apply` 接收：

```json
{
  "updates": [
    {"id": "action-id-1", "status": "done", "note": "已完成"},
    {
      "id": "action-id-2",
      "status": "partial",
      "reason": "low_energy",
      "next_action": "keep",
      "note": "只做了拉伸"
    }
  ]
}
```

安全口径：

- `apply --dry-run` 只校验并预览，不写 SQLite。
- `apply` 会先校验整批 action id、status、reason 和 next_action；任一 action 不存在或字段非法时整批失败，不做部分写入。
- 单批最多 50 条，避免误把大范围历史 action 一次性改写。
- feedback 使用 `nudge.feedback.v1`，`channel=cli.feedback.apply`，`source_type=subjective`，会被 `review weekly` / `dogfood weekly` 纳入反馈来源统计。

#### feedback interview

`feedback interview` 是 TTY-only 交互入口，用于一次处理一批逾期反馈。

```bash
nudge feedback interview
nudge feedback interview --scope today
nudge feedback interview --scope all-overdue --limit 20
nudge feedback interview --scope all-overdue --limit 50
```

- 默认 `scope=week-overdue`，选择本周且逾期超过 24 小时的 `created` / `pending` action；`today` 选择今天全天，`all-overdue` 选择全部逾期超过 24 小时的 action。
- 单批默认 20 条、最大 50 条；启动时显示本批、总候选和剩余数量。所有回答只保存在进程内存，整批答完后统一确认一次。
- 固定核心题覆盖结果、原因、下一步与文字说明，结果取值为 `done` / `partial` / `skipped` / `deferred` / `blocked` / `unconfirmed`；`unconfirmed` 只更新 latest-only feedback，不改变 action 状态。
- 每条 action 最多有 3 个可跳过的 GPT 追问：每个 action 最多调用一次 fast 模型，timeout 为 10 秒；Nudge 外层重试和 provider SDK 内建重试均为 0。provider 异常、timeout、坏 JSON 或坏 Schema 会显示 `FEEDBACK_INTERVIEW_LLM_DEGRADED`，并自动退回固定核心题。
- 高风险分组（医疗、用药、家庭课程、付款、证件、出行和字段无效事项）同时检查标题和 `reminder_list` 等本地上下文，家庭列表默认按高风险处理。该组不预选状态，调用 GPT 前会显示 provider、模型和发送字段，并可整组选择 `core_only`。
- 最终确认页按普通 / 高风险重新分组，显示原计划时间、核心答案、GPT 问答与附加文字、降级 / `unconfirmed` 状态、Apple Reminder 提示，以及睡眠终止 action 引发的 `skipped_after_sleep` 派生变更和原因；主反馈和派生项使用一个 SQLite 事务提交，任一快照冲突或写入失败都会整批回滚，不留下半批状态。
- 命令只更新 Nudge SQLite，不调用 Calendar、Reminders、Notes 或 Clock adapter；Apple Reminder 如仍存在，需要另行同步或人工处理。
- 空候选和 GPT 降级返回 0；用户取消返回 130；Schema、并发冲突或 SQLite 写入失败返回 1。

#### feedback weekly-score

```bash
nudge feedback weekly-score --difficulty 6 --recovery 7 --sleep 5 --mood 8 --note "任务能完成，但晚上偏累"
nudge feedback weekly-score --difficulty 6 --recovery 7 --sleep 5 --mood 8 --json
```

`feedback weekly-score` 会把本周主观打分写入本地 SQLite `evaluations` 表，period 为 `weekly_subjective`。四个分数均为 1-10：`difficulty` 表示执行难度（越高越难），`recovery` 表示恢复状态，`sleep` 表示主观睡眠，`mood` 表示情绪 / 抗压。`review weekly` 会显示本周最新主观打分；`review weekly --adapt` 会把它和 Health 摘要一起作为上下文传入调整建议。

### nudge profile

用途：构建和查看本地长期画像 / 记忆。

```bash
nudge profile build
nudge profile build --days 90 --json
nudge profile show --json
```

`profile build` 会只读汇总本地 SQLite action 和 feedback，沉淀近 N 天（默认 90 天）完成偏好、容易失败的时间段、常见阻塞原因和过难 / 低价值事项，保存为 `evaluations.period = profile_memory`。它不读取 Apple Calendar / Reminders，不调用 LLM，也不写 Apple 应用。`profile show` 读取最新保存的画像。`review weekly --adapt` 会把最新 profile constraints 与 Health 摘要、主观打分一起传入调整建议上下文，用作下一轮计划约束。

### nudge skills

用途：验证、预览、启动、适配和排期确定性的 Skill Spec。除 `skills schedule`、`skills start` 和 `skills adapt --apply` 外，其余子命令不调用 LLM、不写入 Apple 应用。Skill 规范见 [Skill Spec](skill-spec.md)。

#### skills 子命令一览

- `skills list`：列出内置和自定义 Skills。只读。`--json` 会返回 `source` 字段（`builtin` / `custom`）。
- `skills show <skill>`：展示内置、自定义或文件中的 Skill。只读。
- `skills validate <skill>`：验证 Skill YAML/JSON 或 Skill id。只读。会检查 Skill v0.1 必填字段、JSONLogic 安全子集、patch op 白名单和危险 path。
- `skills apply <skill> --context context.json`：读取 context JSON，依次执行 `personalization` 和 `adaptation` 中命中的确定性规则，输出变更后的 Skill/template；不写 Apple。
- `skills dry-run <skill> --context context.json --weeks N`：预览候选动作；不写 Apple。
- `skills schedule <skill> --context context.json --text-plan <path>`：把候选动作真正写入 Apple Calendar。
- `skills status`：查看活跃 Skill 实例和进度；只读 SQLite。
- `skills start <skill>`：创建实例并写入首批动作；`--dry-run` 不创建实例、不写 Apple。
- `skills adapt <plan-id>`：根据真实追踪历史预览下一阶段；只有 `--apply` 才写入后续动作并推进 cursor。
- `skills create/update/delete`：写入或删除本地自定义 Skill 存储，不写 Apple。

```bash
nudge skills list
nudge skills list --json
nudge skills show strength-basics-12w
nudge skills validate path/to/skill.yaml
nudge skills validate strength-basics-12w
nudge skills apply path/to/skill.yaml --context context.json --json
nudge skills dry-run strength-basics-12w --context context.json --weeks 1 --json
nudge skills status
nudge skills start strength-basics-12w --dry-run
nudge skills adapt <plan-id> --apply
nudge skills schedule strength-basics-12w --context context.json --text-plan path/to/plan.md
nudge skills schedule strength-basics-12w --context context.json --text-plan path/to/plan.md --weeks 4 --yes --json
```

内置 Skill 样例当前有 3 个：`strength-basics-12w`（训练）、`deep-learning-sprint-4w`（学习）、`deep-work-weekly-rhythm`（工作效率）。这些样例随包发布，可直接用 ID 传给 `show` / `validate` / `apply` / `dry-run` / `list`，也可以把自己的 YAML 文件路径传给这些子命令。

#### skills dry-run 与 schedule

`dry-run` 会在 `apply` 的基础上，从个性化后的 `plan_template.phases[].sessions[]` 生成候选 Calendar action 预览。它不调用 LLM，不读取 Calendar，不写 Apple 应用；默认只预览第 1 周，可用 `--weeks` 调整预览周数。日期不会早于 `context.profile.start_date`；优先使用 `context.profile.preferred_days` / `preferred_time`，否则使用 `plan_template.defaults.preferred_days` / `preferred_time`。

`schedule` 把 `dry-run` 的候选动作真正写入 Apple Calendar，让 Skill 动作进入执行闭环。它先跑同一套确定性 dry-run，把 `calendar_event` 预览转成 `calendar_event.create` agent 动作，再复用 `agent apply` 引擎：每批动作先 `dry_run=true` 预览并取回 `dry_run_token`，确认后带同一 token 真实写入。因为是计划驱动写入，`--text-plan <path>` 必填，指向已确认的人类可读计划文本（对应 `text_plan_ref`，命令会同时置 `plan_driven=true` / `text_plan_confirmed=true`）；缺少它走不到写入。超过单批 10 个动作的上限时会自动分批，每批各自 dry-run 取 token 再写入。默认交互式预览并询问确认；`--yes` 跳过确认直接写入，`--json` 输出机器可读结果（`--json` 但不带 `--yes` 时只做 dry-run 预览、不写入）。可用 `--calendar` 指定目标日历，`--config` 指定配置。

示例 context：

```json
{
  "assessment": {
    "current_frequency": "never",
    "injuries": ["lower_back"]
  },
  "history": {
    "effort_avg_7d": 9
  }
}
```

`skills apply` 返回 JSON 示例：

```json
{
  "schema_version": "nudge.cli.v1",
  "ok": true,
  "personalization_applied": ["beginner_frequency"],
  "adaptation_applied": ["too_hard_deload"],
  "skill": {
    "schema_version": "0.1",
    "kind": "skill"
  }
}
```

`skills dry-run` 返回 JSON 示例：

```json
{
  "schema_version": "nudge.cli.v1",
  "ok": true,
  "dry_run": true,
  "personalization_applied": ["beginner_frequency"],
  "adaptation_applied": [],
  "actions": [
    {
      "type": "calendar_event",
      "source": "skill_dry_run",
      "summary": "12 周力量基础：上肢 A",
      "start": "2026-04-27 07:30",
      "end": "2026-04-27 08:15"
    }
  ]
}
```

#### 自定义 Skill 存储

```bash
nudge skills create path/to/custom.yaml [--json]
nudge skills update <skill-id> path/to/custom.yaml [--bump-version] [--json]
nudge skills delete <skill-id> [--json]
```

`create/update/delete` 管理的是本机自定义 Skill（状态目录下的 `skills/<id>.yaml`）：

- `create`：把自定义 YAML 写入本机仓库；会写入 `updated_at`，必要时自动补齐 metadata 版本（`--bump-version` 会把 `x.y.z` 末位 +1）。
- `update`：更新现有自定义 Skill；更新前会创建历史快照到 `skills/.history/<skill-id>/`，便于回溯版本；同样支持 `--bump-version`。
- `delete`：删除自定义 Skill 文件，内置 Skill 不允许删除。

`create/update/delete` 会返回 `schema_version: "nudge.cli.v1"`；`skills ... --json`、`do --json`、`log parse --json` 和 `dogfood weekly --json` 的机器可读输出也都带顶层 `schema_version`。

### nudge trainer

用途：健身计划入口。`trainer plan` 默认使用内置 strength Skill runtime；旧版 LLM 周训练计划可通过 `--legacy-llm` 显式启用。

子命令：

- `trainer plan`：创建训练计划；`--dry-run` 只预览，`--yes` 跳过确认。
- `trainer log <message>`：记录训练完成反馈。
- `trainer status`：查看当前训练计划进度。

```bash
nudge trainer plan --dry-run
nudge trainer plan --yes --weeks 1
nudge trainer log "跑了 5 公里，感觉不错"
nudge trainer status
```

### nudge doctor

用途：只读诊断本地配置、LLM key 和 macOS App 访问。不写 Apple、不写 SQLite。

```bash
nudge doctor
nudge doctor --json
nudge doctor --config ./config.toml
```

它会检查 `config.toml`、LLM API key、Apple Calendar、Reminders、Notes、Mail 的 AppleScript 访问、Clock Shortcuts bridge，以及配置中引用的日历/提醒列表是否存在。Calendar / Reminders / Notes / Clock 检查会先显示当前 adapter，例如 `backend=native` / `backend=shortcuts` / `backend=disabled`；尚未实现的 backend 会直接 FAIL。

- Calendar 列表诊断使用一次性 `name of calendars` 查询，避免日历较多时逐个读取超时；日常 Calendar 上下文读取优先走 Swift/EventKit，只有 Full Access 才能读，write-only 会自动回退 AppleScript。
- Reminders 会先用 AppleScript 检查列表名，再用 Swift/EventKit 的 due-today 查询确认能读取提醒事项数据；完成和删除提醒事项也优先走 Swift/EventKit，避免 AppleScript 在较大列表上卡住。
- Notes 诊断只列可见 folder 名称数量，不读取 note 正文；默认写入文件夹为 `Nudge`，缺权限时提示到“系统设置 → 隐私与安全性 → 自动化”授权。
- Clock 使用 `shortcuts` backend 时会确认本机是否有 `Nudge Create Alarm` 快捷指令；缺失时为 `WARN`，因为 Calendar / Reminders 仍可作为提醒替代。使用 `disabled` backend 时表示部署明确不写闹钟，doctor 显示 PASS。
- `FAIL` 会返回非 0；Reminders/Notes/Mail/Clock 数据读取或桥接问题会显示 `WARN` 和修复指引，但不阻塞核心 Calendar/LLM 诊断。

`--json` 会输出同一份只读诊断的稳定机器可读结构：

```json
{
  "schema_version": "nudge.cli.v1",
  "ok": true,
  "summary": {"PASS": 7, "WARN": 0, "FAIL": 0},
  "checks": [
    {"status": "PASS", "name": "Config", "message": "config.toml loaded", "hint": ""}
  ],
  "errors": []
}
```

其中 `ok=false` 仅表示存在 `FAIL`；`WARN` 仍会出现在 `summary` / `checks`，但不会让命令失败。JSON 不输出 API key、OAuth token 或 Notes 正文。

### nudge docs

用途：维护项目文档。目前提供只读审计。

```bash
nudge docs audit
nudge docs audit --json
nudge docs audit --root . --stale-days 60
```

`nudge docs audit` 不移动、不删除、不重写文件。它会报告 `DOCS_BROKEN_LINK`、`DOCS_BROKEN_ANCHOR`、`DOCS_BROKEN_IMAGE`、`DOCS_JUNK_FILE`、`DOCS_STALE_PLAN`、`DOCS_ARCHIVE_CANDIDATE`、`DOCS_TODO_HISTORY`、`DOCS_DUPLICATE_HEADING`、`DOCS_INDEX_MISMATCH` 和 `DOCS_LONG_ENTRYPOINT` 等问题；`--json` 输出同样带 `schema_version: "nudge.cli.v1"`。严重问题会让命令返回非 0，适合脚本或 daily sync 读取。

### nudge daily

用途：每日维护工作流入口，把「拉最新健康数据」「同步 Apple Reminders 完成状态」「列出剩余需人工处理的过期/阻塞项」「检查文档维护债」合成一个命令。默认 dry-run；确认输出后加 `--apply` 才会写 SQLite。

```bash
nudge daily sync --json
nudge daily sync --apply --json
nudge daily sync --apply --date 2026-07-04
nudge daily sync --date 2026-04-30 --lookback-days 7 --apply --json
nudge daily sync --date 2026-04-30 --no-health --apply --json
nudge daily sync --health export.zip --health-from 2026-07-01 --health-to 2026-07-05
```

- Reminders 部分会自动跑今天、昨天，并在 `--lookback-days` 窗口内补跑仍处于 `created` / `pending` 的 Nudge reminder 日期，避免漏掉更早的未同步完成项；也可以用 `--from YYYY-MM-DD` 强制从某天到 `--date` 全部补跑。它内部复用 `nudge reminders sync-completed` 的匹配规则，保留 Apple Reminders `completionDate`，并继续支持睡后作废逻辑。若某些提醒只从未完成列表消失、但缺少可靠 `completionDate`，这些项会从单日结果的 `human_needed` 提升到 `daily sync` 顶层 `human_needed`，方便直接看到需要人工确认的 `nudge log ... --id ...` 命令。
- Health 部分默认自动选择本机 HealthExport 目录下最新的 `health-*.json` 或 ZIP，并导入 `[--date - lookback-days, --date + 1)` 窗口；也可用 `--health PATH` 指定文件，或用 `--no-health` 跳过。
- Calendar event 过期不会被自动标记完成，因为「过去了」不等于「做完了」；命令会在 `remaining_failures` 和 `human_needed` 中返回可复制的跟进命令。
- Docs 部分会复用 `nudge docs audit` 做只读检查，并在 JSON 的 `docs.report` 中返回结果。`docs.attention_required` 会在发现 error 或 warning 时变为 `true`；顶层 `ok` 仍只表示 Reminders / Health 同步本身是否失败。若 `--apply` 时发现文档 error / warning 且当天尚无打开的文档维护 action，命令只会创建一条本地 `maintenance` action；不会移动、删除或重写任何文档，也不会直接写 Apple Reminders。

### nudge review

用途：生成 daily 或 weekly 复盘报告，并可生成适配建议。

```bash
nudge review daily
nudge review weekly
nudge review weekly --adapt
nudge review weekly --adapt --dry-run
nudge review weekly --adapt --apply
```

周报会读取 SQLite action 状态，并在本地存在 Health daily summary / workout 时追加近 7 天健康摘要；如果本周已运行 `feedback weekly-score`，也会显示最新主观打分。`review weekly --adapt` 会把健康摘要、主观打分和最新 profile constraints 一起放入调整建议 prompt；如果缺少主观反馈，prompt 会要求避免激进加量，此时终端会显示“降级模式：保守”提示。

每次 `--adapt` 运行还会在本地 `evaluations` 写入一条 `weekly_adapt` 记录（`metrics` 含 `mode`=`conservative`/`normal`、`subjective_missing`、`objective_missing` 等机器可读字段，`insights` 存降级原因，`adaptations` 存本次建议快照），便于 dogfood 追踪降级发生的时机与原因；该写入在 `--apply` 确认之前完成，无论是否 apply 都会记录。

完成率口径：`done` 计 1 个完成，`partial` 计 0.5 个完成，`skipped`、`deferred`、`blocked` 和仍待反馈的 action 计 0。睡眠终止型 reminder 完成后，同日晚于它的睡眠 reminder 会自动标记为 `skipped_after_sleep`；这类状态表示“已睡后作废”，不进入待反馈、不进入未完成原因，也不计入完成率失败分母。周报会列出待反馈 action，并汇总 `skipped` / `partial` / `deferred` / `blocked` 的 reason、next_action 和备注。

适配写入边界：

- `--adapt` 默认只展示 AI 建议，不写 Calendar。
- `--dry-run` 会把建议转换成可执行预览：`move` / `reduce` / `split` / `delete` 等 safe 项会显示将改哪个 action、改到什么时间；缺少 `external_id` 的老 action 会标记为 unsafe，不会自动改日历。
- `--apply` 会在用户确认后只执行 safe 项，并把旧 SQLite action 标记为 `adapted` / `deleted`，再写入新的历史记录。当前自动 apply 只处理有 `external_id` 且 `type=calendar_event` 的 Calendar action；Reminder / alarm / note action 即使带有 `external_id` 也会标记为 unsafe，避免把 Reminder ID 误送进 Calendar 更新 / 删除接口。

推荐的每周闭环 workflow：先运行 `nudge daily sync --json` 拉回 Reminders / Health / docs 信号；晚上用 `nudge feedback today` 或晚报里的批量模板补完成状态；周末运行 `nudge feedback weekly-score ...` 写主观评分；再运行 `nudge profile build --json` 刷新本地画像；最后用 `nudge review weekly --adapt --dry-run` 生成下一轮调整，确认后再 `--apply`。

对“是否保持/加量/降级”的决策，必须同时包含两类输入：一类来自可验证源（Health 聚合、Reminders/Calendar 周期信号、`review` / `dogfood` 周报、复查状态），一类来自主观反馈（执行难度、恢复、睡眠、情绪）。若任一来源不足，默认走降级策略，不直接加量。

### nudge health

用途：导入和查看本地 Apple Health 汇总。

- `health import <path>`：解析 Apple Health export ZIP 或 HealthExport JSON。默认 dry-run；`--apply` 写 SQLite。
- `health daily`：查看已导入的健康摘要和 workout metadata。只读。

```bash
nudge health import export.zip --from 2026-07-01 --to 2026-07-05
nudge health import export.zip --apply --json
nudge health import "$HOME/Library/Mobile Documents/iCloud~HealthExport/Documents/Health/health-2026-04-27_141005.json" --from 2026-04-01 --to 2026-04-28 --json
nudge health daily --from 2026-07-01 --json
```

- 默认只做 dry-run：解析 `HealthData` XML 或健康摘要 JSON，返回日期范围、每日汇总数量、训练数量和 ignored GPX routes 数量，不写 SQLite。确认结果后加 `--apply`，才会写入本地状态库的 `health_imports`、`health_daily_summary` 和 `health_workouts` 表。
- 导入范围使用 `[--from, --to)`：`--from` 是包含日期，`--to` 是不包含日期，适合按 1-2 周滚动窗口拉回最近执行结果。当前会汇总步数、步行/跑步距离、活动/基础热量、运动分钟、站立分钟、睡眠、平均/静息心率、HRV、步行心率、体重、体脂、VO2Max，以及 Workout 元数据。第三方 App 的训练数据如果已经进入 Apple 健康导出，会按 `sourceName` 进入 workout 和 `source_counts`。
- 同一天可从 Apple 原生 ZIP 和第三方 HealthExport JSON 多次导入；SQLite 的每日汇总会保留已有非空指标，不会让后续稀疏增量导出的空值覆盖已有值。累计类指标在合并时保留较大的每日值，避免短窗口增量把更完整的日汇总降级；每次导入记录仍会保留在 `health_imports` 中。
- 隐私边界：Nudge 不导入 `apple_health_export/workout-routes/*.gpx`，不保存 GPS 路线点，不保存原始逐条 HealthKit samples，只保存每日聚合和训练元数据。睡眠按结束日期归入当天，便于把前一晚睡眠用于当天复盘。
- 如果在 Finder 的 iCloud 文件里看到新文件，但本地目录里迟迟没有，通常是同步未完成下载：在 Finder 中选中文件夹并确认“总是下载到此 Mac”，或在 iCloud Drive 里触发一次打开/保存后再重试。
- 如果窗口时间段内 `daily/workouts` 都为 0，或 1-2 周窗口只有很少天有样本，CLI 会给出提示：建议改用 Apple 健康 App 的 `Export All Health Data`（ZIP）再导入一次。
- `health daily --json` 只读取本地 SQLite，不访问 iPhone、不访问 HealthKit，也不写 Apple 应用。导入后的 daily summary / workout 会被 evening briefing、`review weekly` 和 `review weekly --adapt` 作为只读客观上下文消费；没有本地数据时这些入口会静默省略健康段落。

### nudge habits

用途：查看习惯 streak，或记录某个习惯今天完成。

```bash
nudge habits
nudge habits log reading
```

要点：查看 streak 只读；`habits log <habit_name>` 写本地 SQLite，不写 Apple。

### nudge schedule

用途：读取日历并查找本周空闲时段；可显式选择候选 slot 后创建 Calendar 事件。

```bash
nudge schedule "找2小时深度工作时间"
nudge schedule "深度工作" --duration 120 --json
nudge schedule "深度工作" --duration 120 --book --slot 1 --title "Deep Work" --dry-run --json
nudge schedule "深度工作" --duration 120 --book --slot 1 --title "Deep Work" --yes
```

- 默认只读 Calendar，并按请求中的 `2小时` / `90分钟` / `1.5h` 等时长过滤空档；也可用 `--duration <minutes>` 明确指定。
- `--book` 必须配 `--slot N`，避免 Nudge 自动替你挑时间。
- `--dry-run` 只展示将创建的 Calendar event，不写 Apple。
- 真实 `--book --yes` 会写 Calendar，并把 action 记录到本地 SQLite。
- 只基于配置日历计算忙闲时段；如果某个 Calendar 应参与排期，请先加入 `config.toml`。在 Calendar Full Access 可用时，底层读取使用 EventKit `predicateForEvents`；否则保持 AppleScript fallback。

### nudge reminders

用途：把 Apple Reminders 的状态同步回 Nudge，或回填旧 action 的关联信息。

```bash
nudge reminders sync-completed
nudge reminders sync-completed --date 2026-07-04 --json
nudge reminders sync-completed --list Tasks --list Health --list GPT --json
nudge reminders sync-completed --apply
nudge reminders reconcile-missing --from 2026-09-01 --to 2026-10-01 --json
nudge reminders reconcile-missing --from 2026-09-01 --to 2026-10-01 --list 家庭 --match 课程 --json
nudge reminders backfill-ids --from 2026-07-01 --to 2026-07-05 --json
nudge reminders backfill-ids --from 2026-07-01 --to 2026-07-05 --apply
nudge reminders backfill-lists --json
nudge reminders backfill-lists --list Tasks --list Health --from 2026-07-01 --to 2026-08-01 --json
nudge reminders backfill-lists --apply
```

`reminders sync-completed`、`reminders backfill-lists` 和 `daily sync` 未传 `--list` 时，优先读取 `[reminders].sync_lists`；未配置该数组时回退到 `[general].default_reminder_list`。显式 `--list` 会完全覆盖配置范围，并按给定顺序去重。

#### reminders sync-completed

同步一个或多个 Apple Reminders 列表的完成状态。新 action 会记录目标列表，并在同步和 ID backfill 前先按已知列表归属过滤；旧 action 没有列表字段时仍会进入明确匹配流程以保持兼容。所有 action 都必须在当前列表找到明确完成匹配后才会写回，不能仅凭“该列表里不存在”推断完成，因此移动列表不会造成误完成。

实现细节：优先通过 EventKit 读取指定日期、指定 Reminder list 中已完成 Apple Reminders 的 `completionDate`，再和 SQLite 里同一天仍是 `created` / `pending` 的 Nudge reminder 对比。只有标题 / 规范化标题、due time、`due_at` 原定日期分钟和 Apple `completionDate` 窗口都唯一匹配的条目才进入自动候选；`completed_at` 使用用户在 Apple Reminders 中实际点击完成的时间，`synced_at` 仅记录 Nudge 同步发生时间。已经从 Apple 未完成列表中消失、但没有可靠 `completionDate` 的 reminder 不会自动 `--apply`，而会进入 JSON 的 `human_needed`，附带可复制的 `nudge log done/skipped/partial --id ...` 跟进命令。

默认只是 dry-run，不写 SQLite；确认 `candidates` 正确后加 `--apply`，命令会把这些 action 标记为 `done`，并用 `nudge.feedback.v1` 在 feedback 中记录 `source_type=objective`、`channel=reminders.sync_completed`、日期和 Reminder list。

睡眠终止级联：若匹配到 Apple `completionDate` 的“关机流程 / 睡觉 / 上床 / 入睡”等睡眠终止型 reminder，`completionDate` 会同时作为 `event_type=sleep_start` 的 `event_at` 写入 SQLite；后续同日晚于这个真实上床时间的睡眠 reminder 会自动标记为 `skipped_after_sleep`。这是本命令唯一的 Apple Reminders 写回例外：`--apply` 时会 best-effort 把同日晚于它的 Apple 睡眠提醒也标记完成，以免后续提醒继续响。写回时会把同一 list 的后续睡眠提醒合并为一次 EventKit batch mutation；每条仍按标题候选 + 原 `scheduled_at` due date 精确匹配，只有唯一命中才会修改，不会按标题批量完成同名提醒。Calendar 移动、删除或过期仍只作为待确认信号。

如果 completed-reminders 查询失败，`--json` 输出会在 `warnings` 中提示；相关 action 会进入 `human_needed`，不会再用“已从未完成列表消失”直接自动判定完成。JSON 顶层的 `auto_apply_policy` 固定说明当前策略为 `requires_apple_completion_date`。

#### reminders reconcile-missing

只读一致性对账入口，用于找出本地 SQLite 中仍为 `created` / `pending`、但 Apple Reminders 指定列表里既没有未完成项、也没有可匹配 `completionDate` 的 reminder action。它按 `--from` / `--to` 日期范围逐日查询 EventKit，输出 `still_open`、`completed`、`missing` 和 `query_errors` 四类；可用 `--match` 限定标题关键词。

该命令没有 `--apply`，不写 Apple Reminders，也不改 SQLite；高风险事项只能先用它生成候选，再由人工决定恢复 Apple Reminder、标记 `skipped`，或保留历史。

#### reminders backfill-ids

为旧版 Nudge 创建、但 SQLite 中缺少 `external_id` 的 reminder action 回填稳定关联 ID。默认 dry-run：按 action 的 `summary` / 规范化标题和 `scheduled_at` 分钟级 due time 查询指定 Apple Reminders list；EventKit 可返回完整 due time 时，还会校验 `due_at` 的日期与分钟，避免把不同日期但同一时间的提醒误关联。只有唯一命中时才列入 `candidates`。

`--apply` 会为候选生成 `nudge://reminder/...`，写入 Apple Reminder 的 URL 和备注 `Nudge-ID`，并更新 SQLite `actions.external_id`。0 命中会进入 `missing`，多命中会进入 `ambiguous`，都不会自动写入。可用 `--include-completed` 同时检查已完成 Apple Reminders；为覆盖夜间 / 次日才点击完成的提醒，该模式会查询目标日和目标日次日的 completed reminders。为避免误关联，建议先指定较窄的 `--from` / `--to` 并查看 JSON。

#### reminders backfill-lists

检查升级前缺少列表归属的 reminder action，默认只读预览；`--apply` 只回填本地 SQLite 的 `reminder_list`，不会修改、完成或移动任何 Apple Reminder。

- 未传 `--list` 时读取 `[reminders].sync_lists`；重复传入 `--list` 会完全覆盖配置范围。只选择状态为 `created` / `pending` 且 `reminder_list IS NULL` 的 reminder action。
- 对每个候选日期读取所选所有列表中的已完成和未完成 Reminder。到期时间必须与 action 的 `YYYY-MM-DD HH:MM` 严格匹配到分钟；标题必须精确相同，或只能去除尾部重复的日期/时间后缀后相同。
- 匹配在所有列表之间执行全局一对一判定。`missing`、`ambiguous`、`invalid` 只报告、不自动修复；任一列表或日期查询失败都会禁止整批 apply。
- dry-run 严格不初始化或迁移 SQLite。数据库带有非空 WAL 或 rollback journal、尚未包含当前 `reminder_list` 字段，或读取期间发生变化时会安全失败，不会就地修复状态库。
- `--apply` 在 TTY 中使用默认答案为“否”的整批确认；非 TTY 或 `--json` 模式必须显式加 `--yes`。确认后会再次查询 Apple 并核对候选未变化，再自动创建权限为 `0600` 且通过完整性检查的数据库完整备份，最后用单个 SQLite 事务只更新 `reminder_list`。
- Apple 数据在整个流程中保持零修改；若二次核验、备份、快照或并发状态出现冲突，整批回滚，不留下部分更新。

#### backfill-lists 的安全前置步骤

旧 schema、非空 WAL 或 rollback journal 时：

1. 停止 `nudge daemon run`、相关 LaunchAgent 和其它可能写状态库的 Nudge 进程，并等待正在执行的命令退出；不要手工删除 `.db-wal`、`.db-shm` 或 `.db-journal`。
2. 对目标状态库运行现有的只读状态入口 `nudge skills status --json`。该命令不访问 Apple，但会通过 Nudge 的标准状态初始化/迁移流程打开 SQLite，使旧 `actions` 表补齐当前字段并让 SQLite 正常处理 WAL 或 rollback journal。
3. 使用自定义配置时，两步必须传入同一个 `--config`，且不要在两步之间改变 `NUDGE_STATE_DIR`，否则可能升级和检查不同的数据库：

```bash
# 默认配置
nudge skills status --json
nudge reminders backfill-lists --json

# 自定义配置
nudge skills status --config ./config.custom.toml --json
nudge reminders backfill-lists --config ./config.custom.toml --json
```

如果完成上述步骤后仍报告非空 WAL、rollback journal 或旧 schema，请保持停止写入，不要强行 apply 或删除 SQLite sidecar 文件；先确认没有其它进程持有状态库，再重新运行同一配置的 `skills status` 和 dry-run。

### nudge agent

用途：给其他本地 agent / MCP wrapper / 自动化脚本提供结构化 Apple action relay。它不调用 LLM，不解析自然语言；调用方提交结构化 JSON，Nudge 负责 macOS 权限、adapter 选择、dry-run、真实写入、SQLite tracking、错误归一化和 `external_id` 返回。

- `agent apply`：从 stdin 或 `--file` 读取结构化请求并执行 Apple actions。`--dry-run` 预览且不创建 Apple 项。
- `agent status`：从 stdin 或 `--file` 读取 action-status 回写请求。`--dry-run` 不写 SQLite。

```bash
nudge agent apply --dry-run --file request.json --json
nudge agent apply --file approved-request.json --json
cat request.json | nudge agent apply --json
nudge agent status --file status.json --json
```

`agent apply` 直连路径不做 `request_id` replay 去重（`request_id` 仅作调用方 trace），避免重复写 Apple 靠 dry-run 预览 + 只提交已批准 payload；需要幂等入队时改用 `daemon enqueue`（以 `request_id` 为队列幂等键）。

#### agent apply 请求格式

```json
{
  "request_id": "planner-2026-06-17-001",
  "source": "planner-agent",
  "plan_driven": true,
  "text_plan_confirmed": true,
  "text_plan_ref": "path/to/plan.md",
  "dry_run": false,
  "require_confirmation": true,
  "dry_run_token": "nudge.agent.confirm.v1:...",
  "actions": [
    {
      "type": "calendar_event.create",
      "summary": "项目会",
      "start": "2026-04-26 14:00",
      "end": "2026-04-26 15:00",
      "target": {"calendar": "个人"},
      "notes": "由 planner-agent 生成"
    },
    {
      "type": "reminder.create",
      "name": "买菜",
      "due_date": "2026-04-26 18:00",
      "target": {"list": "日常"}
    },
    {
      "type": "alarm.create",
      "time": "07:00",
      "label": "晨起称重"
    },
    {
      "type": "note.create",
      "title": "本周执行计划",
      "body": "本周要点清单",
      "target": {"folder": "Nudge"}
    }
  ]
}
```

当前支持的 action type：

- `calendar_event.create`：必填 `summary`、`start`、`end`；可选 `target.calendar` / `calendar_name`、`location`、`notes`。
- `reminder.create`：必填 `name`、`due_date`；可选 `target.list` / `list_name`、`body`、`priority`、`notify`、`remind_date`。默认 `notify=true`；未显式传 `remind_date` 时使用 `due_date` 作为通知时间。只有用户明确要求“仅截止时间、不通知”时才传 `notify=false`，此时保留 due date 但不创建提醒通知。dry-run JSON 的 `actions[]` 会返回有效 `notify` 和 `remind_at`。`name` 应是短标题，不要重复写入日期或时间；如果标题末尾和 `due_date` 重复，Nudge 会在写入和 JSON 摘要中自动清理。
- `alarm.create`：必填 `time`、`label`；使用 `[apple.clock].shortcut_name` 指定的 Shortcuts bridge。
- `note.create`：必填 `title`、`body`；可选 `target.folder` / `folder_name`，默认写入 Apple Notes 的 `Nudge` 文件夹；JSON 结果中的 target kind 为 `Notes folder`。写入前会把 Markdown-ish 标题、列表、checkbox、强调、代码围栏和表格转换成简单 HTML，避免备忘录里出现源码式 Markdown。调用方不要把完整 `.md` 文件源码当作最终 Notes 正文。当前只创建新 note，不读取、搜索、更新或删除已有 note。

返回格式沿用 `nudge.cli.v1`。写入成功的 Calendar / Reminders / Clock action 会返回 `external_id`；Notes 当前 native backend 还没有稳定 ID，因此保持 `external_id = null`。部分失败时仍输出可解析 JSON，并返回非 0。单次 `actions` 最多 10 个；超限会返回 `AGENT_BATCH_TOO_LARGE`，且不会进入 Apple 写入路径。请求结构错误或 action 值不可执行时返回 `AGENT_REQUEST_INVALID`（例如缺少必填字段、时间格式不是 `YYYY-MM-DD HH:MM`、结束时间不晚于开始时间）；未实现 Apple backend 返回 `APPLE_BACKEND_UNSUPPORTED`。

#### agent apply 确认机制

计划驱动确认：长期计划、周计划、Skill 或复盘调整等批量计划生成的请求必须设置 `plan_driven=true`，并在进入 action dry-run 前完成文本确认。此类请求必须同时传 `text_plan_confirmed=true` 和非空 `text_plan_ref`（例如已确认的计划文档路径或稳定 note 标题）；缺少任一字段会返回 `AGENT_TEXT_PLAN_CONFIRMATION_REQUIRED`，Nudge 不会生成 `dry_run_token`，也不会写入 Apple 应用。非计划型单条临时写入可保持 `plan_driven=false`。

action 写入确认：如果请求设置 `require_confirmation=true`，第一次必须用 `dry_run=true` 预览；响应会返回 `dry_run_token`。真实写入时必须带回同一 token，并保持 `request_id`、`source`、`plan_driven`、`text_plan_confirmed`、`text_plan_ref`、`actions`、target、时间和内容不变。缺少 token 返回 `AGENT_CONFIRMATION_REQUIRED`；token 与当前请求不匹配返回 `AGENT_CONFIRMATION_INVALID`，且不会写入 Apple 应用。该 token 使用本机状态目录下的 `agent_confirm_secret` 作为 HMAC secret 生成；secret 首次使用时以 `0600` 权限创建；它用于绑定 dry-run 摘要和真实写入，不是身份认证凭证。

启用 `[security.local_auth]` 后，请求 JSON 中还必须提供 `auth_token`。

#### agent status

`agent status` 用于把自动化执行结果回写到本地 SQLite，不改写 Apple 应用内容。它只更新 `actions` 表中的 `status` 和 `feedback`，适合在 MCP / 提醒 / IM / iOS 反馈通道里复用同一套状态字段。新写入的 feedback 使用 `nudge.feedback.v1`，会包含 `channel`、`source_type`、`source`、`note`、`reason`、`next_action` 和可选 `metrics`；旧 feedback 不迁移，但 `review` / `dogfood` 会兼容解析。

```bash
nudge agent status --file status.json
cat status.json | nudge agent status
nudge agent status --dry-run --file status.json
```

```json
{
  "action_id": "4f3a9c12ab",
  "status": "done",
  "source": "mcp",
  "note": "已完成 30min 训练",
  "reason": "low_energy",
  "next_action": "keep",
  "feedback": {
    "duration_min": 30,
    "mode": "home"
  }
}
```

- `action_id`（必填）：Nudge 内部 action id。
- `status`（必填）：`done` / `skipped` / `partial` / `deferred` / `blocked`。
- `source`：调用方标识，如 `mcp`、`client`、`iphone-shortcut`。
- `note`：简短反馈文本。
- `reason`：`too_hard` / `no_time` / `conflict` / `low_energy` / `forgot` / `unclear` / `not_important` / `waiting_on_other` 之一。
- `next_action`：`keep` / `reduce` / `split` / `reschedule` / `cancel` 之一。
- `feedback`：对象形式的附加字段，会与上述标准字段合并；标准字段会统一补上 `schema_version: "nudge.feedback.v1"`、`channel` 和 `source_type`。

返回 payload 也为 `schema_version = "nudge.cli.v1"`，`payload.action` 会包含本次更新前状态到 `updated` 新状态的差分；`--dry-run` 时 `updated` 为 `null`，`dry_run` 为 `true`。

### nudge mcp

用途：以本地 MCP stdio server 形式暴露 Nudge 工具。

```bash
nudge mcp serve
nudge mcp serve --config config.toml
<repo>/bin/nudge mcp serve
```

`mcp serve` 通过 stdio 暴露四个 MCP tool：

- `apply_apple_actions`：写入型工具，是 `agent apply` 的薄包装。MCP client 发送 `tools/call`，Nudge MCP server 把 tool arguments 当作同一份 agent request 执行；schema 对 `actions` 标记 `maxItems=10`，并暴露 `plan_driven`、`text_plan_confirmed`、`text_plan_ref` 文本计划确认字段。超限返回 `AGENT_BATCH_TOO_LARGE`。
- `report_action_status`：状态回写工具，写入本地 SQLite action `status`、`feedback`，不调用 Apple apps。
- `doctor_status`：只读诊断工具，返回 `nudge doctor --json` 同类 PASS/WARN/FAIL、message 和 hint；只允许 `include_pass` 参数，不允许 `config_path` 或任意文件路径。
- `list_nudge_notes`：只读 Apple Notes 的固定 `Nudge` folder，只返回 note 标题、标题派生摘要和日期字段；不读取正文，不允许传任意 folder。

Capability 分组：

- 写 Apple apps：`apply_apple_actions`。计划驱动请求必须先确认文本计划并传 `plan_driven=true`、`text_plan_confirmed=true`、`text_plan_ref`；随后展示 action dry-run 人工确认 UI，先 `dry_run=true` 预览，再用匹配 `dry_run_token` 写入。
- 写本地状态：`report_action_status`。
- 只读诊断 / 窄范围读取：`doctor_status`、`list_nudge_notes`。

`tools/list` 会给这些 tool 返回 MCP `annotations`（`readOnlyHint`、`destructiveHint`、`idempotentHint`、`openWorldHint`），方便客户端 UI 分组；annotations 只是提示，不是授权边界，不能替代 Nudge 服务端的 schema、dry-run token 和本地执行校验。

四个 tool 都返回 MCP `CallToolResult`，其中 `content[0].text` 是完整 Nudge JSON 字符串，`structuredContent` 是同一份结构化 payload，`isError=true` 表示请求结构错误、doctor 存在 FAIL，或部分/全部写入失败。

给 MCP client 的本机 server 配置示例：

```json
{
  "mcpServers": {
    "nudge": {
      "command": "<repo>/bin/nudge",
      "args": ["mcp", "serve"]
    }
  }
}
```

MCP client 接入 checklist：固定使用 `<repo>/bin/nudge`；不要用 `curl | sh`、`npx` 或 shell wrapper 启动 server；不要把 `apply_apple_actions` 放入“自动允许”组；每批最多 10 个 action；失败时只重试失败项；不要通过 prompt 或中间层新增任意 shell、AppleScript、文件读取或 Notes 正文读取能力。

MCP stdio 的 stdout 是 JSON-RPC 通道，不能写普通日志；Nudge MCP server 也不会在 stdout 输出非 JSON-RPC 文本。当前不暴露 Calendar / Reminders 的任意条目读取工具。启用 `[security.local_auth]` 后，`apply_apple_actions` 和 `report_action_status` 的 arguments 还必须包含 `auth_token`。安全策略详见 [MCP 安全策略](mcp-security.md)。

### nudge daemon

用途：本机长期运行时，不调用 LLM，直接消费 `command_queue` 并持久化执行审计；也包含 launchd 和图形健康辅助 app 管理。人工回放和排障细节见 [Daemon Runbook](daemon-runbook.md)。

#### daemon 队列与状态

```bash
# 把结构化请求落库
nudge daemon enqueue --type agent.apply --file request.json --json
nudge daemon enqueue --type agent.status --file status.json --json

# 查看队列
nudge daemon queue
nudge daemon queue --status queued --json
nudge daemon queue --status dead_letter --json

# 查看状态
nudge daemon status
nudge daemon status --json

# 健康巡检：检查 launchd、队列、stale running 和 dead_letter
nudge daemon health
nudge daemon health --json
nudge daemon health --notify

# 常驻运行（由 launchd 加载）
nudge daemon run

# 只执行一次（本地验证）
nudge daemon run --once
nudge daemon run --once --verbose
```

`daemon` 执行会调用：

- `agent.apply`：创建 Calendar / Reminder / Alarm / Note 执行路径；
- `agent.status`：本地状态回写。

每次执行会在 `daemon_runs` 写入审计字段：`request_id` / `command_id` / `request_type` / `status` / `queue_wait_ms` / `processing_ms` / `total_ms` / `error_text` / `output_json`。`command_queue` 同步记录每次 `status`、重试次数、耗时和最后错误。队列状态包括：

- `queued`：等待 daemon 消费。
- `running`：已被 daemon claim，正在执行。
- `succeeded` / `failed`：一次执行已结束。
- `dead_letter`：running 卡死恢复时已达到最大尝试次数，需要人工确认后重放。

#### daemon 故障恢复

```bash
# 回收 daemon 崩溃、睡眠/唤醒或重启后卡在 running 的命令
nudge daemon recover --stale-minutes 30 --max-attempts 3
nudge daemon recover --json

# 人工确认后把 failed / dead_letter 命令重新放回队列
nudge daemon retry --request-id <request_id>
nudge daemon retry --request-id <request_id> --json
```

- `nudge daemon run` 启动时默认按 `NUDGE_DAEMON_STALE_MINUTES=30` 和 `NUDGE_DAEMON_MAX_ATTEMPTS=3` 先执行一次 stale-running 回收，避免 Mac 睡眠/唤醒或 launchd 重启后遗留 `running` 命令。
- `nudge daemon recover` 可手动执行同一套回收逻辑；未达到最大尝试次数的 stale `running` 命令会回到 `queued`，达到上限会进入 `dead_letter`。
- `nudge daemon retry --request-id ...` 只处理 `failed` / `dead_letter`，会把该命令重置为 `queued`，清空本次错误和 attempts，适合人工确认不会重复写入后重放。
- `daemon enqueue` 默认用 `NUDGE_DAEMON_MAX_QUEUE_DEPTH=1000` 限制 `queued + running` 活跃深度，队列已满时拒绝新增命令，避免异常循环无限堆积。
- `nudge daemon health` 合并 `launchd` 是否安装/加载、队列深度、stale `running` 和 `dead_letter`，输出可读文本或稳定 JSON；发现 `dead_letter` 时 `status=fail`、`ok=false`，但命令本身只报告状态，不直接修改队列。`--notify` 会在存在异常时发送一条 macOS 本机通知，健康状态下静默不打扰。
- `daemon health --json` 会包含 `alert_policy`，把 `LAUNCHD_NOT_LOADED`、`STALE_RUNNING_COMMANDS`、`DEAD_LETTER_COMMANDS` 等告警映射到 `briefing+notification`、`recover`、`manual_replay` 等处理策略；`DEAD_LETTER_COMMANDS` 的升级策略是 `manual_review_required`，必须先按 [Daemon Runbook](daemon-runbook.md) 检查幂等再 retry。
- `briefing morning/evening` 会读取同一份 daemon health 摘要；有异常时在 briefing 末尾追加「Nudge daemon 告警」和具体处理命令。如果 briefing 带 `--notify`，daemon 告警会单独发一条通知，避免淹没在早晚报正文里。

#### daemon launchd 与健康辅助 app

```bash
# 只安装/管理 daemon LaunchAgent，不影响 morning/evening briefing 定时任务
nudge daemon launchd install
nudge daemon launchd status
nudge daemon launchd status --json
nudge daemon launchd stop
nudge daemon launchd start
nudge daemon launchd restart
nudge daemon launchd uninstall

# 安装/打开图形化 daemon 健康入口
nudge daemon app install --login-item
nudge daemon app status
nudge daemon app open
nudge daemon app uninstall
```

- `launchd` 系列是 `com.nudge.agent` 的无头自启动入口；`stop` 只卸载运行中的 LaunchAgent，不删除 plist，`uninstall` 才会移除 plist。
- `nudge daemon app install --login-item` 会在用户的 `Applications` 目录生成 `Nudge Daemon Health.app`，提供可点击的图形化入口：显示当前 macOS 版本、Mac 型号和 CPU 架构，一键查看 `daemon health`、打开 `com.nudge.agent` 日志路径、重启 daemon，并可加入 macOS Login Item。
- launchd/app 子命令是 macOS 专用，并会写用户级 plist/app 文件；是否写 Apple 取决于队列请求本身。

### nudge db

用途：维护本地 SQLite 数据库。

```bash
nudge db backup
nudge db backup --output backup.db --json
nudge db export
nudge db export --output dump.sql --json
nudge db restore backup.db --yes
nudge db restore dump.sql --yes --json
```

Nudge 本地状态目录由三层决定：`NUDGE_STATE_DIR` 环境变量优先；其次读取 `config.toml` 的 `[state].dir` 或 `[state].directory`；都没有配置时默认使用安装底座目录下的 `.nudge/`。相对路径按安装底座解析：

```toml
[state]
dir = ".nudge"
```

- `db backup` 使用 SQLite online backup API 创建一致的 `.db` 备份，**不会在备份前初始化或迁移源库**；源库不存在时失败，不创建空库。源库存在非空 WAL / rollback journal 或备份期间发生变化时安全失败，不会静默遗漏未检查点数据。先确认没有其它进程持有状态库，再通过合适的状态命令处理日志并重试；不要手工删除 sidecar 文件。不传 `--output` 时写入状态目录的 `backups/nudge-YYYYmmdd-HHMMSS-<随机值>.db`。
- `db export` 输出 portable SQL dump；不传 `--output` 时写入状态目录的 `exports/nudge-YYYYmmdd-HHMMSS.sql`。
- `db restore` 支持从 `.db` 或 `.sql` 恢复，必须显式带 `--yes`，否则返回 `RESTORE_CONFIRMATION_REQUIRED`；真实替换前会先创建 `backups/nudge-before-restore-YYYYmmdd-HHMMSS.db`，并对来源和恢复后的库做 `PRAGMA integrity_check`。这是本地状态的高风险写操作。

### nudge briefing

用途：生成 morning/evening briefing。

```bash
nudge briefing morning
nudge briefing evening
nudge briefing evening --notify
```

briefing 读取 Calendar 上下文时只查询 `config.toml` 中配置的日历（`default_calendar`、`[calendars]` 和家庭成员日历），不会默认扫描所有系统/订阅日历。配置日历读取会优先使用 Swift/EventKit；如果当前终端/Agent 对 Calendar 只有 write-only 权限而非 Full Access，会自动回退到已收窄的 AppleScript 单日历查询。

`briefing morning` 会读取 Calendar、Reminders、Mail；`briefing evening` 会读取 Calendar；macOS 上可能需要对应读取权限。`--notify` 会发送 macOS 本地通知，额外需要通知/terminal-notifier 权限。

evening briefing 会在正文后追加三类本地 follow-up：

- 「待反馈 action」：仍是 `created` / `pending` 的动作。该段落会同时给出单条 `nudge log ... --id ...` 命令和可复制的 `nudge feedback apply --json` 批量回执模板；只需把未完成项的 `status` 改成 `partial` / `skipped` / `deferred` / `blocked` 并补 reason / next_action，即可一次性写回本地 SQLite。
- 「失败/阻塞待跟进」：复用 `nudge failures` 的口径，把超时待反馈、blocked、deferred、缺少 reason / next_action 的 action 显示出来。
- 「健康数据」：只读取本地 daily summary / workout 元数据，展示近 7 天睡眠、步数、活跃能量和运动次数；没有导入数据时不显示。

两个 briefing 都会读取 daemon health 摘要，异常时追加「Nudge daemon 告警」。

### nudge chat

用途：启动多轮交互式对话。

```bash
nudge chat
```

要点：需要 LLM 配置；对话响应可能包含可执行动作 JSON，执行动作时仍遵守 Apple 写入权限和确认边界。

### nudge dogfood

用途：查看 Nudge 自身本地使用周报。

```bash
nudge dogfood weekly
nudge dogfood weekly --note "本周主要验证真实使用闭环"
nudge dogfood weekly --save
nudge dogfood weekly --json
nudge dogfood weekly --export-json dogfood.json
```

`dogfood weekly` 是面向 Nudge 自己的只读聚合周报：它读取本地 SQLite action 和 `nudge doctor` 只读诊断结果，汇总本周使用次数、完成率、真实 Calendar 写入数、Adapt 采纳数、待反馈 action、未完成原因、已睡后作废 reminder 数量，以及 Calendar / Reminders / Mail 等权限或错误状态。`skipped_after_sleep` 不计入完成率失败分母。该命令不调用 LLM，不写 Apple Calendar / Reminders；但 doctor 式只读检查在 macOS 上可能触发或需要 Apple App 读取权限。

关键指标还包含「失败可解释」摘要：`overdue`（超时待反馈）、`blocked`、`missing_reason`、`missing_next_action`，用于确认失败是否有归因和下一步。周报还会输出「反馈来源」摘要，并在 JSON 中提供 `feedback_sources`，用于区分 `subjective`（人工 log/check-in）、`objective`（Reminders 同步）、`agent`（agent/MCP 回写）和 `unknown`（旧数据或自由文本）。

`--save` 会把 Markdown 周报保存到状态目录的 `dogfood/YYYY-WW.md`，其中 `YYYY-WW` 使用 ISO 周编号。`--json` 输出带 `schema_version: "nudge.cli.v1"` 的机器可读周报；`--export-json` 把同一 JSON payload 写入指定文件；`--note` 可追加一段主观记录。

### nudge failures

用途：只读查看 overdue、blocked、unexplained 和临近到期的 action。不调用 LLM、不读取 Apple 应用、不写 SQLite。

```bash
nudge failures
nudge failures --overdue-hours 24 --limit 10
nudge failures --overdue-hours 48 --limit 20 --json
nudge failures --notify
nudge failures --due-soon-minutes 60 --notify
nudge failures --json
```

报告分类：

- `pending_overdue`：`created` / `pending` 且计划时间早于 `--overdue-hours` 的 action；
- `blocked_open` / `deferred_open`：仍处于 blocked / deferred 的 action；
- `missing_reason`：`skipped` / `partial` / `deferred` / `blocked` 但 feedback 中没有 `reason`；
- `missing_next_action`：未完成类状态但 feedback 中没有 `next_action`；
- `due_soon`（可选，仅在传 `--due-soon-minutes N` 时出现）：`created` / `pending` 且计划时间在「现在到现在 + N 分钟」窗口内的**临近未做** action，用于主动「该提醒了」跟进，而不是等它逾期。它不计入 `total_open_issues`（不是失败），但 `--notify` 会因它触发通知；默认不带该选项时报告与旧行为完全一致。

文本输出会按优先级列出待跟进项，并附带建议命令，例如：

```bash
nudge log done --id <action_id> --reason unclear --next-action keep "补充执行结果"
nudge log blocked --id <action_id> --reason waiting_on_other --next-action keep "补充阻塞原因"
```

`--notify` 会在存在待跟进问题时发送一条 macOS 本机通知；没有问题时静默跳过。`--json` 输出同样带 `schema_version: "nudge.cli.v1"`，脚本可读取 `report.summary`、各类明细和可选的 `notification` 结果。

可以用 launchd `StartInterval` 每 30 分钟跑一次 `nudge failures --notify --due-soon-minutes 60` 做本机主动跟进，配置细节见 [Daemon Runbook](daemon-runbook.md)。

## Clock Shortcuts bridge

macOS Clock 没有稳定 AppleScript alarm 字典；Nudge 通过 Shortcuts CLI 调用本机快捷指令：

```bash
shortcuts run "Nudge Create Alarm" --input-path payload.json
```

`payload.json` 形如：

```json
{
  "time": "07:00",
  "label": "晨起称重",
  "enabled": true
}
```

推荐配置步骤：

1. 在 Shortcuts.app 新建快捷指令，名称固定为 `Nudge Create Alarm`。
2. 读取 Shortcut Input 的 JSON / Dictionary。
3. 从输入中取 `time` 和 `label`。
4. 调用 Clock → Create Alarm，并启用 alarm。
5. 手动用上面的 `shortcuts run` 命令验证一次。

## 其他项目调用示例

### Shell 调用

```bash
#!/usr/bin/env bash
set -euo pipefail

<repo>/bin/nudge "明天下午3点开会"
<repo>/bin/nudge do --json "明天下午3点开会"
<repo>/bin/nudge --dry-run "周五上午提醒我提交周报"
<repo>/bin/nudge log done --match "提交周报"
<repo>/bin/nudge dogfood weekly --save
<repo>/bin/nudge skills list
<repo>/bin/nudge skills validate path/to/skill.yaml
```

### Python 调用

```python
import json
import subprocess

result = subprocess.run(
    ["<repo>/bin/nudge", "do", "--json", "明天下午3点开会"],
    capture_output=True,
    text=True,
    timeout=60,
)

if result.returncode != 0:
    raise RuntimeError(result.stderr)

payload = json.loads(result.stdout)
print(payload["actions"])
```

### Node.js 调用

```javascript
import { spawnSync } from "node:child_process";

const result = spawnSync(
  "<repo>/bin/nudge",
  ["do", "--json", "明天下午3点开会"],
  { encoding: "utf8" }
);

if (result.status !== 0) {
  throw new Error(result.stderr);
}

console.log(JSON.parse(result.stdout).actions);
```

## 返回码与错误处理

- `exit code 0`：命令成功。对于写入命令，表示解析和写入流程全部完成。
- 非 0：命令失败或部分失败。调用方应读取 `stderr`，常见原因包括 LLM API key 缺失、LLM 返回非法 JSON、AppleScript/EventKit 权限不足、目标 Calendar/List 不存在、Apple 应用 timeout。
- `feedback interview` 另有约定：空候选和 GPT 降级返回 0；用户取消返回 130；Schema、并发冲突或 SQLite 写入失败返回 1。

`nudge do` 的写入语义更严格：

- 全部 action 写入成功：返回 0，并把成功 action 记录到 SQLite。
- 部分 action 写入失败：返回非 0，输出 `部分 action 写入失败`，只记录成功项。
- 全部 action 写入失败：返回非 0，不写入本地成功记录。

如果看到 `部分 action 写入失败`，不要直接整条重试；已成功的 Calendar / Reminders 项可能已经存在，整条重试会造成重复创建。应根据输出里的失败项，只重试失败的那部分。

常见可操作错误：

- `LLM 返回了无效 JSON`：模型输出不满足 action JSON 契约；先用 `nudge --dry-run "..."` 复现，必要时收窄输入或切换更强模型。
- `目标 Calendar/List 不存在`：运行 `nudge doctor` 查看当前可见列表，再检查 `config.toml` 名称是否完全一致。
- `Calendar/Reminders 权限不足`：打开对应 Apple app，并到系统设置的隐私权限里允许当前终端/IDE/Python 访问。
- `Calendar/Reminders 操作超时`：先打开对应 app，确认没有权限弹窗或 iCloud 同步卡住，再运行 `nudge doctor`。

建议其他项目先用 `--dry-run` 做预览或测试，再去掉 `--dry-run` 执行真实写入。

## macOS 权限

首次写入或读取 Apple Calendar、Reminders、Mail、Notifications 时，macOS 可能弹出权限请求。请在系统设置中允许对应终端或 Python 进程访问：

- 系统设置 → 隐私与安全性 → 日历
- 系统设置 → 隐私与安全性 → 提醒事项
- 系统设置 → 隐私与安全性 → 自动化
- 系统设置 → 通知

如果其他项目通过固定路径调用 Nudge，权限通常归属于发起命令的终端、IDE、Agent 或 Python 解释器。

Calendar 的 EventKit 读取需要 **Full Access**，不是 macOS 14+ 的 write-only 权限。若未授予 Full Access，Nudge 仍会通过 AppleScript fallback 尝试读取配置日历，但速度会比 EventKit 慢。

非 macOS 环境下可用的命令范围见 [非 macOS 环境说明](non-macos.md)。

## 配置和密钥

Nudge 默认读取当前工作目录 / 安装底座中的本机 `config.toml`；该文件已加入 `.gitignore`，应由 `config.example.toml` 复制生成，不提交到仓库。完整字段说明见 [配置说明](configuration.md)，LLM provider 细节见 [LLM 配置](llm.md)。

```toml
[llm]
provider = "qwen"

[llm.models]
fast = "qwen-plus"
default = "qwen-plus"
strong = "qwen-plus"
```

密钥解析顺序：

1. provider 专用环境变量，例如 `DASHSCOPE_API_KEY` / `QWEN_API_KEY`；
2. 本机私有 `secrets.yaml`（通过 `NUDGE_SECRETS_PATH` 或本机 `config.toml [llm].secrets_path` 指定）；
3. 通用环境变量 `LLM_API_KEY`；
4. `config.toml [llm].api_key`（兼容旧配置；doctor 会 WARN，不推荐使用）。

长期密钥不要写入仓库；本机私有 `secrets.yaml` 示例：

```yaml
dashscope_api_key: "your-key"
# 可选兼容键名：qwen_api_key、anthropic_api_key、openai_api_key、deepseek_api_key
```

读取路径可用环境变量覆盖：

```bash
export NUDGE_SECRETS_PATH="$HOME/.config/nudge/secrets.yaml"
# 兼容其他项目：也支持 EMAIL_SECRETS_PATH
```

其他 provider：`provider = "anthropic"` 读取 `ANTHROPIC_API_KEY` / `anthropic_api_key`；`provider = "openai"` 读取 `OPENAI_API_KEY` / `openai_api_key`；`provider = "deepseek"` 读取 `DEEPSEEK_API_KEY` / `deepseek_api_key`。

## 命令行 Help

CLI 自带 help，可用于确认当前版本真实支持的参数：

```bash
nudge --help
nudge do --help
nudge log --help
nudge feedback --help
nudge feedback interview --help
nudge feedback weekly-score --help
nudge profile --help
nudge skills --help
nudge skills schedule --help
nudge reminders --help
nudge reminders backfill-lists --help
nudge agent --help
nudge daemon --help
nudge daemon health --help
nudge doctor --help
nudge dogfood weekly --help
nudge briefing --help
nudge review --help
nudge failures --help
```
