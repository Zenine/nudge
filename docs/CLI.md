# Nudge CLI 接口文档

本文档面向其他项目、脚本和本机自动化流程，说明如何调用 Nudge CLI，把自然语言计划解析后写入 Apple 日历、提醒事项、备忘录等 macOS 应用。

## 安装与入口

在 Nudge 仓库中执行：

```bash
cd /path/to/nudge
scripts/install_cli.sh
```

如果是第一次给小白配置，也可以先跑一条更省事的方式：

```bash
scripts/bootstrap_mac.sh
```

这个脚本会自动创建项目内 `.venv`、把依赖安装到隔离环境，并安装 `~/.local/bin/nudge` 指向固定路径 wrapper。普通用户不需要手动激活虚拟环境；`bin/nudge` 会优先使用项目内 `.venv/bin/python`，缺失时才回退系统 `python3`。

如果希望直接配置自动化（默认每天早 7 点、晚 21:30 执行 briefing）：

```bash
scripts/bootstrap_launchd.sh
```

该脚本会安装：

- morning/evening 两个 `briefing` 任务
- `com.nudge.agent` 长驻任务（`nudge daemon run`）

查看/卸载：

```bash
scripts/bootstrap_launchd.sh status
scripts/bootstrap_launchd.sh uninstall
```

如果只需要管理 `com.nudge.agent` 这个无头 daemon（不改早晚 briefing 定时任务），也可以直接使用 CLI：

```bash
nudge daemon launchd install
nudge daemon launchd status --json
nudge daemon launchd stop
nudge daemon launchd start
nudge daemon launchd restart
nudge daemon health --json
nudge daemon health --notify
nudge daemon app install --login-item
nudge daemon app open
```

安装脚本会把固定路径 wrapper 链接到 `~/.local/bin/nudge`。当前推荐两种入口：

```bash
# 全局命令，适合人在任意项目目录手动调用
nudge "明天下午3点开会"

# 固定路径，适合其他项目、Agent、launchd、cron 或脚本稳定调用
/path/to/nudge/bin/nudge "明天下午3点开会"

# 机器可读 JSON，适合其他项目用 subprocess 解析 stdout
/path/to/nudge/bin/nudge do --json "明天下午3点开会"

# 结构化 Agent 中转接口：不调用 LLM，直接执行其他 agent 提交的 Apple actions
/path/to/nudge/bin/nudge agent apply --file request.json --json
```

固定路径 wrapper 支持被 symlink 到其他位置后继续解析到真实仓库根目录。

## 调用约定

- 默认自然语言输入等价于 `do` 子命令：`nudge "明天下午3点开会"` 等价于 `nudge do "明天下午3点开会"`。
- 默认自然语言入口会执行写入：日历事件写入 Apple Calendar，提醒事项写入 Apple Reminders。结构化 `agent apply` / MCP 入口还支持写入 Apple Notes 和 Clock。
- 预览模式使用 `--dry-run`，只解析和展示 action，不写入 Apple 应用：

```bash
nudge --dry-run "明天下午3点开会"
nudge --json --dry-run "明天下午3点开会"
```

- 从文件读取：

```bash
nudge --file message.txt
```

- 从管道读取：

```bash
cat message.txt | nudge
```

- 使用自定义配置文件：

```bash
nudge --config /path/to/config.toml "下周二下午2点项目会"
```

## 常用接口

### 创建日历/提醒事项/闹钟/备忘录

```bash
nudge "明天下午3点开会"
nudge "下周二下午2点项目会，周三上午10点团队同步"
nudge "明天早上7点闹钟提醒我晨起称重"
```

Calendar / Reminders 默认通过 `nudge.apple.adapters` 选择 `native` backend，写入 Apple Calendar / Apple Reminders。Apple Notes 通过 `native` AppleScript backend 写入指定文件夹，默认文件夹为 `Nudge`，只用于结构化 agent/MCP 中转，不从 Notes 读取正文；正文会先转换成人类可读的简单 Notes HTML。真实 Notes 写入的验收标准是手机或 Mac 备忘录中不再可见 raw Markdown 控制符，例如 `#`、`- [ ]`、三反引号或 `|---|` 表格分隔线。`alarm` 默认使用 `shortcuts` backend，通过 macOS Shortcuts bridge 调用 Clock：本机需要先创建名为 `Nudge Create Alarm` 的快捷指令，读取输入 JSON 的 `time` / `label`，并执行 Clock → Create Alarm。若快捷指令不存在，Nudge 会返回 `CLOCK_SHORTCUT_MISSING`，不会把闹钟伪装成已创建。

家庭组自然语言规则：如果用户说“家庭组 / 全家 / 家人 / 所有人”这类目标，Nudge 会先按 `[family.routing.rules]` 的关键词规则决定接收人；未命中时可用 LLM 兜底；仍不确定时使用 `[family.routing].default`，当前默认是 `all`，也可配置为具体 member key 列表。启用 `llm_fallback=true` 时，会把最小化后的家庭事项内容、成员 key/display_name/role、路由规则摘要发送给配置的 LLM provider；隐私优先可设 `llm_fallback=false`，未命中关键词时只走 default。用户明确说“提醒妈妈 / 提醒爸爸 / 提醒孩子”时，只创建该成员对应的提醒，不进入家庭组路由。当前阶段不承诺 Apple Reminders 原生 assignment；Apple 公开 EventKit / Reminders 自动化接口没有稳定的 assignee / “分配提醒事项”字段，Nudge 不依赖 iOS 私有指派能力。默认用成员化标题表达归属，例如 `妈妈：科学实验上课`；如果不希望标题显示归属，可配置 `[family.routing.display] title_prefix=false`，并可配合 `body_assignee_note=true` 在提醒备注中写入 `负责人：姓名`。`default = "all"` 会为每个家庭成员各创建一条 reminder；写入同一个 iCloud 共享列表时，到点通知仍取决于每位成员是否加入该列表以及各自设备的 Reminders 通知设置。对于单负责人事项，共享列表中的其他成员仍可能看到或收到提醒，Nudge 只能通过标题/备注表达归属，不能用公开 API 强制“只通知某人”。如果模型把家庭组目标解析成 calendar event，Nudge 不写 Calendar，而是按路由结果改写为对应成员在开始前 30 分钟和开始时各一条 Apple Reminders reminder；`--json --dry-run` / JSON 输出会在 `actions[].routing` 包含 routing metadata，说明命中的是关键词规则、LLM 兜底还是 default fallback。普通人类可读 dry-run 不承诺显示完整 metadata。Apple Reminders 共享列表本身不会把一条提醒的到点通知自动共享给所有成员，因此 Nudge 不把“写入共享列表”当作“所有人都被通知”的充分条件。

当前支持的 Apple backend 配置：

```toml
[apple.calendar]
backend = "native"

[apple.reminders]
backend = "native"

[apple.notes]
backend = "native"

[apple.clock]
backend = "shortcuts"
shortcut_name = "Nudge Create Alarm"
```

`ical` / `rem` / `ekctl` / MCP 仍是调研候选；如果现在写进 config，`nudge doctor` 会 FAIL，`nudge do --json` 会返回 `APPLE_BACKEND_UNSUPPORTED`，避免半接入造成真实数据风险。

### 预览解析结果

```bash
nudge --dry-run "明天下午3点开会"
nudge do --json --dry-run "明天下午3点开会"
```

### 机器可读 JSON 接口

其他项目推荐使用 `--json`，这样 stdout 只包含一段稳定 JSON；人类诊断和权限错误仍输出到 stderr。`nudge --json "..."` 会和默认自然语言入口一样自动路由到 `do` 子命令。

```bash
nudge do --json "明天下午3点开会"
nudge --json --dry-run "明天下午3点开会"
/path/to/nudge/bin/nudge do --json "明天下午3点开会"
```

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
- `actions[]`：每个 action 的 `index`、`type`、`status`、`summary`、`scheduled_at`、`target`，真实 Calendar / Clock 写入成功时还包含 `external_id`。
- `failures[]`：失败 action 的 `index`、`summary`、`error_code`、`error`。
- `errors[]`：全局或写入错误，包含 `code`、`message`、`detail`、`raw_error`。
- 部分写入失败时，JSON 仍可解析，`ok=false`，进程返回非 0。
- 输入文件、配置读取和 action 值校验失败也保持同一 stdout JSON 契约：本地输入/配置错误返回 `CLI_INPUT_ERROR`；LLM 产出的不可执行 action（例如时间格式错误、结束时间不晚于开始时间）返回 `LLM_ACTION_SCHEMA_INVALID`，不会进入 Apple 写入。

### Agent Apple 中转接口

`agent apply` 是给其他本机 agent / MCP wrapper / 自动化脚本使用的低层入口。它不调用 LLM，不解析自然语言；调用方提交结构化 JSON，Nudge 负责 macOS 权限、adapter 选择、dry-run、真实写入、SQLite tracking、错误归一化和 `external_id` 返回。

```bash
nudge agent apply --file request.json --json
cat request.json | nudge agent apply --json
nudge agent apply --dry-run --file request.json --json
```

请求格式：

```json
{
  "request_id": "planner-2026-04-26-001",
  "source": "planner-agent",
  "plan_driven": true,
  "text_plan_confirmed": true,
  "text_plan_ref": "docs/confirmed-plan.md",
  "dry_run": false,
  "require_confirmation": true,
  "dry_run_token": "nudge.agent.confirm.v1:...",
  "actions": [
    {
      "type": "calendar_event.create",
      "summary": "项目会",
      "start": "2026-04-26 14:00",
      "end": "2026-04-26 15:00",
      "target": {"calendar": "Personal"},
      "notes": "由 planner-agent 生成"
    },
    {
      "type": "reminder.create",
      "name": "买菜",
      "due_date": "2026-04-26 18:00",
      "target": {"list": "Tasks"}
    },
    {
      "type": "alarm.create",
      "time": "07:00",
      "label": "晨起称重"
    },
    {
      "type": "note.create",
      "title": "本周执行计划",
      "body": "饮食、训练、测量和睡眠清单",
      "target": {"folder": "Nudge"}
    }
  ]
}
```

当前支持的 action type：

- `calendar_event.create`：必填 `summary`、`start`、`end`；可选 `target.calendar` / `calendar_name`、`location`、`notes`。
- `reminder.create`：必填 `name`、`due_date`；可选 `target.list` / `list_name`、`body`、`priority`、`remind_date`。`name` 应是短标题，不要重复写入日期或时间；如果标题末尾和 `due_date` 重复，Nudge 会在写入和 JSON 摘要中自动清理。
- `alarm.create`：必填 `time`、`label`；使用 `[apple.clock].shortcut_name` 指定的 Shortcuts bridge。
- `note.create`：必填 `title`、`body`；可选 `target.folder` / `folder_name`，默认写入 Apple Notes 的 `Nudge` 文件夹；JSON 结果中的 target kind 为 `Notes folder`。Notes 内容面向人阅读，写入前会把 Markdown-ish 标题、列表、checkbox、强调、代码围栏和 Markdown 表格转换成简单 HTML，避免 Apple 备忘录里出现源码式 Markdown。调用方不要把完整 `.md` 文件源码当作最终 Notes 正文；长计划应先整理成给人看的说明和小节。当前只创建新 note，不读取、搜索、更新或删除已有 note。

返回格式沿用 `nudge.cli.v1`。写入成功的 Calendar / Clock action 会返回 `external_id`；Reminders 和 Notes 当前 native backend 还没有稳定 ID，因此保持 `external_id = null`。部分失败时仍输出可解析 JSON，并返回非 0。单次 `actions` 最多 10 个；超限会返回 `AGENT_BATCH_TOO_LARGE`，且不会进入 Apple 写入路径。请求结构错误或 action 值不可执行时返回 `AGENT_REQUEST_INVALID`，例如缺少必填字段、时间格式不是 `YYYY-MM-DD HH:MM`、结束时间不晚于开始时间；未实现 Apple backend 返回 `APPLE_BACKEND_UNSUPPORTED`。

计划驱动确认机制：长期计划、周计划、Skill 或复盘调整等批量计划生成的请求必须设置 `plan_driven=true`，并在进入 action dry-run 前完成文本确认。此类请求必须同时传 `text_plan_confirmed=true` 和非空 `text_plan_ref`（例如已确认的 repo 文档路径或稳定 note 标题）；缺少任一字段会返回 `AGENT_TEXT_PLAN_CONFIRMATION_REQUIRED`，Nudge 不会生成 `dry_run_token`，也不会写入 Apple 应用。非计划型单条临时写入可保持 `plan_driven=false`。

action 写入确认机制：如果请求设置 `require_confirmation=true`，第一次必须用 `dry_run=true` 预览；响应会返回 `dry_run_token`。真实写入时必须带回同一 token，并保持 `request_id`、`source`、`plan_driven`、`text_plan_confirmed`、`text_plan_ref`、`actions`、target、时间和内容不变。缺少 token 返回 `AGENT_CONFIRMATION_REQUIRED`；token 与当前请求不匹配返回 `AGENT_CONFIRMATION_INVALID`，且不会写入 Apple 应用。这个 token 使用本机状态目录下的 `agent_confirm_secret` 作为 HMAC secret 生成；状态目录可由 `NUDGE_STATE_DIR` 或 `config.toml [state].dir` 覆盖，默认是安装底座下的 `.nudge/`；secret 首次使用时以 `0600` 权限创建；它用于绑定 dry-run 摘要和真实写入，不是身份认证凭证。

后续 MCP server 不应直接调用 AppleScript/EventKit，而应把 MCP tool 请求转换成上述 JSON，复用 `agent apply` 的同一套安全执行路径。

### 本地 daemon 队列运行时（P0 基座）

`nudge daemon` 用于本机长期运行时，不调用 LLM，直接消费 `command_queue` 并持久化执行审计。

人工回放和排障细节见：[Daemon Runbook](DAEMON_RUNBOOK.md)。

```bash
# 把结构化请求落库
nudge daemon enqueue --file request.json --type agent.apply --json

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

# 回收 daemon 崩溃、睡眠/唤醒或重启后卡在 running 的命令：
# attempts < max-attempts 的命令会回到 queued，达到上限的命令进入 dead_letter
nudge daemon recover --stale-minutes 30 --max-attempts 3
nudge daemon recover --json

# 人工确认后把 failed / dead_letter 命令重新放回队列
nudge daemon retry --request-id <request_id>
nudge daemon retry --request-id <request_id> --json

# 常驻运行（由 launchd 加载）
nudge daemon run

# 只执行一次（本地验证）
nudge daemon run --once

# 只安装/管理 daemon LaunchAgent，不影响 morning/evening briefing 定时任务
nudge daemon launchd install
nudge daemon launchd status
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

`daemon` 执行会调用：
- `agent.apply`：创建 Calendar/Reminder/Alarm/Note 执行路径
- `agent.status`：本地状态回写

每次执行会在 `daemon_runs` 写入审计字段：
`request_id` / `command_id` / `request_type` / `status` / `queue_wait_ms` / `processing_ms` / `total_ms` / `error_text` / `output_json`。
`command_queue` 同步记录每次 `status`、重试次数、耗时和最后错误，后续可用于重放与告警。队列状态包括：

- `queued`：等待 daemon 消费。
- `running`：已被 daemon claim，正在执行。
- `succeeded` / `failed`：一次执行已结束。
- `dead_letter`：running 卡死恢复时已达到最大尝试次数，需要人工确认后通过 `nudge daemon retry --request-id ...` 重放。

故障恢复规则：

- `nudge daemon run` 启动时默认按 `NUDGE_DAEMON_STALE_MINUTES=30` 和 `NUDGE_DAEMON_MAX_ATTEMPTS=3` 先执行一次 stale-running 回收，避免 Mac 睡眠/唤醒或 launchd 重启后遗留 `running` 命令。
- `nudge daemon recover` 可手动执行同一套回收逻辑；未达到最大尝试次数的 stale `running` 命令会回到 `queued`，达到上限会进入 `dead_letter`。
- `nudge daemon retry --request-id ...` 只处理 `failed` / `dead_letter`，会把该命令重置为 `queued`，清空本次错误和 attempts，适合人工确认不会重复写入后重放。
- `daemon enqueue` 默认用 `NUDGE_DAEMON_MAX_QUEUE_DEPTH=1000` 限制 `queued + running` 活跃深度，队列已满时拒绝新增命令，避免异常循环无限堆积。
- `nudge daemon launchd install/start/stop/restart/uninstall/status` 是 `com.nudge.agent` 的无头自启动入口；`stop` 只卸载运行中的 LaunchAgent，不删除 plist，`uninstall` 才会移除 plist。
- `nudge daemon health` 是巡检入口：合并 `launchd` 是否安装/加载、队列深度、stale `running` 和 `dead_letter`，输出可读文本或稳定 JSON；发现 `dead_letter` 时 `status=fail`、`ok=false`，但命令本身仍用于报告状态，不直接修改队列。
- `nudge daemon health --notify` 会在存在异常时发送一条 macOS 本机通知；健康状态下静默不打扰。
- `briefing morning/evening` 会读取同一份 daemon health 摘要；有异常时在 briefing 末尾追加「Nudge daemon 告警」和具体处理命令，例如 `nudge daemon recover`、`nudge daemon queue --status dead_letter --json`、`nudge daemon retry --request-id ...`。如果 briefing 带 `--notify`，daemon 告警会单独发一条「Nudge daemon 告警」通知，避免淹没在早晚报正文里。
- `nudge daemon app install --login-item` 会生成 `~/Applications/Nudge Daemon Health.app`，提供一个可点击的图形化入口：显示当前 macOS 版本、Mac 型号和 CPU 架构，一键查看 `daemon health`、打开 `com.nudge.agent` 日志路径、重启 daemon，并可加入 macOS Login Item。
- `daemon health --json` 会包含 `alert_policy`，把 `LAUNCHD_NOT_LOADED`、`STALE_RUNNING_COMMANDS`、`DEAD_LETTER_COMMANDS` 等告警映射到 `briefing+notification`、`recover`、`manual_replay` 等处理策略；`DEAD_LETTER_COMMANDS` 的升级策略是 `manual_review_required`，必须先按 [Daemon Runbook](DAEMON_RUNBOOK.md) 检查幂等再 retry。

### Agent 本地状态回写

`agent status` 用于把自动化执行结果回写到本地 SQLite，不改写 Apple 应用内容。它只更新 `actions` 表中的 `status` 和 `feedback`，适合在 MCP / 提醒 / IM / iOS 反馈通道里复用同一套状态字段。新写入的 feedback 使用 `nudge.feedback.v1`，会包含 `channel`、`source_type`、`source`、`note`、`reason`、`next_action` 和可选 `metrics`；旧 feedback 不迁移，但 review / dogfood 会兼容解析。

```bash
nudge agent status --file status.json
cat status.json | nudge agent status
nudge agent status --dry-run --file status.json
```

请求字段：

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

字段说明：

- `action_id`（必填）：`nudge` 内部 action id。
- `status`（必填）：`done` / `skipped` / `partial` / `deferred` / `blocked`
- `source`：调用方标识，如 `mcp`、`client`、`iphone-shortcut`。
- `note`：简短反馈文本。
- `reason`：以下枚举之一：`too_hard` / `no_time` / `conflict` / `low_energy` / `forgot` / `unclear` / `not_important` / `waiting_on_other`。
- `next_action`：以下枚举之一：`keep` / `reduce` / `split` / `reschedule` / `cancel`。
- `feedback`：对象形式的附加字段，会与上述标准字段合并进 `feedback`；保留为 metadata，但标准字段会统一补上 `schema_version: "nudge.feedback.v1"`、`channel` 和 `source_type`。

返回 payload 也为 `schema_version = "nudge.cli.v1"`，`payload.action` 会包含本次更新前状态到 `updated` 新状态的差分；`--dry-run` 时 `updated` 为 `null`，`dry_run` 为 `true`。

### MCP server wrapper

`mcp serve` 通过 stdio 暴露四个 MCP tool：

- `apply_apple_actions`：写入型工具，是 `agent apply` 的薄包装。MCP client 发送 `tools/call`，Nudge MCP server 把 tool arguments 当作同一份 agent request 执行；schema 对 `actions` 标记 `maxItems=10`，并暴露 `plan_driven`、`text_plan_confirmed`、`text_plan_ref` 文本计划确认字段。超限返回 `AGENT_BATCH_TOO_LARGE`。
- `report_action_status`：状态回写工具，写入本地 SQLite action `status`、`feedback`，不调用 Apple apps。
- `doctor_status`：只读诊断工具，返回 `nudge doctor --json` 同类 PASS/WARN/FAIL、message 和 hint；只允许 `include_pass` 参数，不允许 `config_path` 或任意文件路径。
- `list_nudge_notes`：只读 Apple Notes 的固定 `Nudge` folder，只返回 note 标题、标题派生摘要和日期字段；不读取正文，不允许传任意 folder。

Capability 分组：

- 写 Apple apps：`apply_apple_actions`。计划驱动请求必须先确认文本计划并传 `plan_driven=true`、`text_plan_confirmed=true`、`text_plan_ref`；随后展示 action dry-run 人工确认 UI，先 `dry_run=true` 预览，再用匹配 `dry_run_token` 写入。
- 写本地状态：`report_action_status`。只改 SQLite action 状态和 feedback，不读写 Apple apps。
- 只读诊断/窄范围读取：`doctor_status`、`list_nudge_notes`。前者只返回诊断状态，后者只列固定 `Nudge` folder 的标题和标题派生摘要。

`tools/list` 会给这些 tool 返回 MCP `annotations`（`readOnlyHint`、`destructiveHint`、`idempotentHint`、`openWorldHint`），方便客户端 UI 分组；annotations 只是提示，不是授权边界，不能替代 Nudge 服务端的 schema、dry-run token 和本地执行校验。

MCP client 接入 checklist：固定使用 `/path/to/nudge/bin/nudge`；不要用 `curl | sh`、`npx` 或 shell wrapper 启动 server；不要把 `apply_apple_actions` 放入“自动允许”组；每批最多 10 个 action；失败时只重试失败项；不要通过 prompt 或中间层新增任意 shell、AppleScript、文件读取或 Notes 正文读取能力。

四个 tool 都返回 MCP `CallToolResult`，其中：

- `content[0].text` 是完整 Nudge JSON 字符串。
- `structuredContent` 是同一份结构化 payload。
- `isError=true` 表示请求结构错误、doctor 存在 FAIL，或部分/全部写入失败。

启动方式：

```bash
nudge mcp serve
/path/to/nudge/bin/nudge mcp serve
```

给 MCP client 的本机 server 配置示例：

```json
{
  "mcpServers": {
    "nudge": {
      "command": "/path/to/nudge/bin/nudge",
      "args": ["mcp", "serve"]
    }
  }
}
```

MCP stdio 的 stdout 是 JSON-RPC 通道，不能写普通日志；Nudge MCP server 也不会在 stdout 输出非 JSON-RPC 文本。协议层参考官方 MCP 的 JSON-RPC、`initialize`、`tools/list`、`tools/call` 形态；当前不暴露 Calendar / Reminders 的任意条目读取工具；`doctor_status` 只返回诊断状态和修复建议，Notes 只开放 `list_nudge_notes` 这个固定 folder 的标题列表，避免把本机隐私数据默认送给远端 agent。写工具必须由 MCP client 展示确认 UI：计划驱动请求先确认文本计划，传 `plan_driven=true`、`text_plan_confirmed=true` 和 `text_plan_ref`；再 `dry_run=true` 预览，最后带匹配 `dry_run_token` 写入；批量任务应拆成每批最多 10 个 action。安全策略详见 [MCP Security](MCP_SECURITY.md)。

### 每日早报

```bash
nudge briefing morning
nudge briefing evening
```

briefing 读取 Calendar 上下文时只查询 `config.toml` 中配置的日历（`default_calendar`、`[calendars]` 和家庭成员日历），不会默认扫描所有系统/订阅日历。配置日历读取会优先使用 Swift/EventKit；如果当前终端/Agent 对 Calendar 只有 write-only 权限而非 Full Access，会自动回退到已收窄的 AppleScript 单日历查询。

evening briefing 会在正文后追加两类本地 follow-up：仍是 `created` / `pending` 的「待反馈 action」，以及「失败/阻塞待跟进」。后者复用 `nudge failures` 的口径，把超时待反馈、blocked、deferred、缺少 reason / next_action 的 action 显示出来，并给出可直接复制的 `nudge log ... --id ...` 命令。

### 周报和调整建议

```bash
nudge review weekly
nudge review weekly --adapt
nudge review weekly --adapt --dry-run
nudge review weekly --adapt --apply
```

周报会读取 SQLite action 状态。`done` 计 1 个完成，`partial` 计 0.5 个完成，`skipped`、`deferred`、`blocked` 和仍待反馈的 action 计 0。睡眠终止型 reminder（例如“22:30 关机流程 / 睡觉 / 上床 / 入睡”）完成后，同日晚于它的睡眠 reminder 会自动标记为 `skipped_after_sleep`；这类状态表示“已睡后作废”，不进入待反馈、不进入未完成原因，也不计入完成率失败分母。周报会列出待反馈 action，并汇总 `skipped` / `partial` / `deferred` / `blocked` 的 reason、next_action 和备注，方便复盘真正卡在哪里。

`--adapt` 默认只展示 AI 建议，不写 Calendar。`--dry-run` 会把建议转换成可执行预览：`move` / `reduce` / `split` / `delete` 等 safe 项会显示将改哪个 action、改到什么时间；缺少 `external_id` 的老 action 会标记为 unsafe，不会自动改日历。`--apply` 会在用户确认后只执行 safe 项，并把旧 SQLite action 标记为 `adapted` / `deleted`，再写入新的历史记录。当前自动 apply 只处理有 `external_id` 的 Calendar action；没有 `external_id` 的旧 action 需要手动处理或重新创建。

长期计划落地时采用滚动窗口：6 个月目标、阶段目标和安全边界保留在文档 / YAML 中，Apple Calendar / Reminders / Clock / Notes 默认只写未来 1 周；如果未来两周约束稳定，可以扩展到 2 周。每轮执行结束后先用 `review weekly`、`dogfood weekly`、Reminders completed sync 和人工 check-in 生成报告，再决定下一轮动作是否保持、降级、拆分、改期或取消；不要把整月、整阶段或 6 个月计划一次性批量写入 Apple 应用。

计划驱动的 Apple 写入必须遵守“文档确认先行”：凡是根据长期计划、周计划、Skill 或复盘结果批量生成 Calendar / Reminders / Clock / Notes action，必须先更新或生成对应的人类可读文本计划 / 变更说明，明确日期范围、特殊日历、目标、降级规则和 App 分层；用户确认文本后，才进入结构化 action dry-run；dry-run 再确认后才能真实写入 Apple 应用。不能先写 Reminders / Calendar，再事后回补计划说明。

对“是否保持/加量/降级”的决策，必须同时包含两类输入：一类来自可验证源（Health 聚合、Reminders/Calendar 周期信号、`review/dogfood` 周报、复查状态），一类来自主观反馈（执行难度、恢复、睡眠、情绪）。若任一来源不足，默认走降级策略，不直接加量。

### Dogfood 周报

```bash
nudge dogfood weekly
nudge dogfood weekly --note "本周主要验证真实使用闭环"
nudge dogfood weekly --save
nudge dogfood weekly --json
nudge dogfood weekly --export-json dogfood.json
```

`dogfood weekly` 是面向 Nudge 自己的只读聚合周报：它读取本地 SQLite action、`nudge doctor` 只读诊断结果，汇总本周使用次数、完成率、真实 Calendar 写入数、Adapt 采纳数、待反馈 action、未完成原因、已睡后作废 reminder 数量，以及 Calendar / Reminders / Mail 等权限或错误状态。`skipped_after_sleep` 不计入完成率失败分母。该命令不调用 LLM，不写 Apple Calendar / Reminders。

Dogfood 周报的关键指标还包含「失败可解释」摘要：`overdue`（超时待反馈）、`blocked`、`missing_reason`、`missing_next_action`。这些指标用于确认失败是否有归因和下一步，而不是让旧 pending / blocked 靠记忆沉没。周报还会输出「反馈来源」摘要，并在 JSON 中提供 `feedback_sources`，用于区分 `subjective`（人工 log/check-in）、`objective`（Reminders 同步）、`agent`（agent/MCP 回写）和 `unknown`（旧数据或自由文本）。

`--save` 会把 Markdown 周报保存到 Nudge 本地状态目录的 `dogfood/YYYY-WW.md`，其中 `YYYY-WW` 使用 ISO 周编号。状态目录优先级为：`NUDGE_STATE_DIR`、`config.toml` 的 `[state].dir`、安装底座下的 `.nudge/`。`--json` 会输出带 `schema_version: "nudge.cli.v1"` 的机器可读周报；`--export-json` 会把同一 JSON payload 写入指定文件。`--note` 可追加一段主观记录，方便第 4 周回看是否真的觉得“没有 Nudge 会更麻烦”。

### SQLite 数据库维护

```bash
nudge db backup
nudge db backup --output backup.db --json
nudge db export
nudge db export --output dump.sql --json
nudge db restore backup.db --yes
nudge db restore dump.sql --yes --json
```

Nudge 本地状态目录由三层决定：`NUDGE_STATE_DIR` 环境变量优先；其次读取 `config.toml` 的 `[state].dir` 或 `[state].directory`；如果都没有配置，则默认使用安装底座目录下的 `.nudge/`。相对路径按安装底座解析，例如：

```toml
[state]
dir = ".nudge"
```

`nudge db backup` 使用 SQLite online backup API 创建一致的 `.db` 备份；不传 `--output` 时会写入状态目录的 `backups/nudge-YYYYmmdd-HHMMSS.db`。`nudge db export` 输出 SQL dump；不传 `--output` 时会写入状态目录的 `exports/nudge-YYYYmmdd-HHMMSS.sql`。`nudge db restore` 支持从 `.db` 或 `.sql` 恢复，必须显式带 `--yes`，否则返回 `RESTORE_CONFIRMATION_REQUIRED`；真实替换前会先创建 `backups/nudge-before-restore-YYYYmmdd-HHMMSS.db`，并对来源和恢复后的库做 `PRAGMA integrity_check`。

### 失败/阻塞可见性

```bash
nudge failures
nudge failures --overdue-hours 24 --limit 10
nudge failures --notify
nudge failures --json
```

`nudge failures` 是只读检查命令，不调用 LLM、不读取 Apple 应用、不写 SQLite。它从本地 action 状态生成「失败/阻塞可见性」报告：

- `pending_overdue`：`created` / `pending` 且计划时间早于 `--overdue-hours` 的 action；
- `blocked_open` / `deferred_open`：仍处于 blocked / deferred 的 action；
- `missing_reason`：`skipped` / `partial` / `deferred` / `blocked` 但 feedback 中没有 `reason`；
- `missing_next_action`：未完成类状态但 feedback 中没有 `next_action`。

文本输出会按优先级列出待跟进项，并附带建议命令，例如：

```bash
nudge log done --id <action_id> --reason unclear --next-action keep "补充执行结果"
nudge log blocked --id <action_id> --reason waiting_on_other --next-action keep "补充阻塞原因"
```

`--notify` 会在存在待跟进问题时发送一条 macOS 本机通知；没有问题时静默跳过，避免打扰。`--json` 输出同样带 `schema_version: "nudge.cli.v1"`，脚本可读取 `report.summary`、各类明细和可选的 `notification` 结果。该命令只负责把失败显性化和本机提醒；IM 追问、自动重排和写回 Apple 应用仍属于后续主动跟进增强。

### 每日同步聚合命令

```bash
nudge daily sync --json
nudge daily sync --apply --json
nudge daily sync --date 2026-04-30 --lookback-days 7 --apply --json
nudge daily sync --date 2026-04-30 --no-health --apply --json
```

`nudge daily sync` 是每日工作流入口：它把「拉 HealthExport 最新健康数据」「同步 Apple Reminders 完成状态」「列出剩余需要人工处理的过期/阻塞项」合成一个命令。默认 dry-run；确认输出后加 `--apply` 才会写 SQLite。

Reminders 部分会自动跑今天、昨天，并在 `--lookback-days` 窗口内补跑仍处于 `created` / `pending` 的 Nudge reminder 日期，避免只跑昨天/今天时漏掉更早的未同步完成项。也可以用 `--from YYYY-MM-DD` 强制从某天到 `--date` 全部补跑。它内部复用 `nudge reminders sync-completed` 的匹配规则，因此能保留 Apple Reminders `completionDate`，并继续支持睡眠终止提醒后的睡后作废逻辑。

Health 部分默认自动选择 `~/Library/Mobile Documents/iCloud~HealthExport/Documents/Health/` 下最新的 `health-*.json` 或 ZIP，并导入 `[--date - lookback-days, --date + 1)` 窗口；也可用 `--health PATH` 指定文件，或用 `--no-health` 跳过。Calendar event 过期不会被自动标记完成，因为「过去了」不等于「做完了」；命令会在 `remaining_failures` 和 `human_needed` 中返回可复制的 `nudge log ... --id ...` 跟进命令。

### Reminders 完成状态同步

```bash
nudge reminders sync-completed
nudge reminders sync-completed --date 2026-04-27 --json
nudge reminders sync-completed --date 2026-04-27 --apply
```

`sync-completed` 会优先通过 EventKit 读取指定日期、指定 Reminder list 中已完成 Apple Reminders 的 `completionDate`，再和 SQLite 里同一天仍是 `created` / `pending` 的 Nudge reminder 对比。写回 SQLite 时，若匹配到 Apple `completionDate`，`completed_at` 使用用户在 Apple Reminders 中实际点击完成的时间；`synced_at` 仅记录 Nudge 同步发生时间。已经从 Apple 未完成列表中消失的 Nudge reminder 仍会作为完成候选列出；默认只是 dry-run，不写 SQLite。确认候选正确后加 `--apply`，命令会把这些 action 标记为 `done`，并用 `nudge.feedback.v1` 在 feedback 中记录 `source_type=objective`、`channel=reminders.sync_completed`、日期和 Reminder list。

若匹配到 Apple `completionDate` 的“关机流程 / 睡觉 / 上床 / 入睡”等睡眠终止型 reminder，`completionDate` 会同时作为 `event_type=sleep_start` 的 `event_at` 写入 SQLite；后续同日晚于这个真实上床时间的睡眠 reminder 会自动标记为 `skipped_after_sleep`，表示已睡后自动作废。该命令通常只把 Reminders completed 状态作为 `done` 候选写回本地状态库；唯一的 Apple Reminders 写回例外是睡后作废：当 `--apply` 发现睡眠终止型 reminder 已完成时，会尝试把同日晚于它的睡眠 reminder 也标记完成，以避免后续提醒继续响。Calendar 移动、删除或过期仍只作为待确认信号，不会自动改完成状态。

如果 completed-reminders 查询失败，`--json` 输出会在 `warnings` 中提示，并保持旧兼容候选同步：继续用“已从未完成列表消失”判断完成候选，避免因为 EventKit 权限或查询异常完全中断同步。

### Apple 健康导出导入

```bash
# iCloud 健康导出文件通常在：
# ~/Library/Mobile Documents/iCloud~HealthExport/Documents/Health/*.json
nudge health import "$HOME/Library/Mobile Documents/iCloud~HealthExport/Documents/Health/health-2026-04-27_141005.json" --from 2026-04-01 --to 2026-04-28 --json
nudge health import "$HOME/Library/Mobile Documents/iCloud~HealthExport/Documents/Health/health-2026-04-27_141005.json" --from 2026-04-01 --to 2026-04-28 --apply --json
nudge health import "$(ls -t ~/Library/Mobile\\ Documents/iCloud~HealthExport/Documents/Health/*.json | head -n 1)" --from 2026-04-21 --to 2026-04-28 --json
nudge health daily --from 2026-04-21 --to 2026-04-28 --json
```

`health import` 读取 iPhone Apple 健康导出的文件，支持 `.zip`（`export.zip`）和 HealthExport JSON（`.json`）。默认只做 dry-run：解析 `HealthData` XML 或健康摘要 JSON，返回日期范围、每日汇总数量、训练数量和 ignored GPX routes 数量，不写 SQLite。确认结果后加 `--apply`，才会写入本地状态库的 `health_imports`、`health_daily_summary` 和 `health_workouts` 表。

导入范围使用 `[--from, --to)`：`--from` 是包含日期，`--to` 是不包含日期，适合按 1-2 周滚动窗口拉回最近执行结果。当前会汇总步数、步行/跑步距离、活动/基础热量、运动分钟、站立分钟、睡眠、平均/静息心率、HRV、步行心率、体重、体脂、VO2Max，以及 Workout 元数据。Keep 的训练、热量和距离如果已经进入 Apple 健康导出，会按 `sourceName` 进入 workout 和 `source_counts`。

同一天可从 Apple 原生 ZIP 和第三方 HealthExport JSON 多次导入；SQLite 的每日汇总会保留已有非空指标，不会让后续稀疏增量导出的空体重覆盖已有体重。累计类指标在合并时保留较大的每日值，避免短窗口增量把更完整的日汇总降级；每次导入记录仍会保留在 `health_imports` 中。

隐私边界：Nudge 不导入 `apple_health_export/workout-routes/*.gpx`，不保存 GPS 路线点，不保存原始逐条 HealthKit samples，只保存每日聚合和训练元数据。睡眠按结束日期归入当天，便于把前一晚睡眠用于当天复盘。

如果你在 Finder 的 iCloud 文件里看到新文件，但本地 `HealthExport/Documents/Health` 里迟迟没看到，通常是同步未完成下载：在 Finder 中选中文件夹并确认“总是下载到此 Mac”，或在 iCloud Drive 里触发一次打开/保存后再重试同步。

执行后如果看到窗口时间段内 `daily/workouts` 都为 0，或 1-2 周窗口只有很少天有样本，CLI 会给出提示：这时建议改用 Apple 健康 App 的 `Export All Health Data`（ZIP）再导入一次，通常能补齐更完整的历史和训练明细。

`health daily --json` 输出同样带 `schema_version: "nudge.cli.v1"`。它只读取本地 SQLite，不访问 iPhone、不访问 HealthKit，也不写 Apple 应用。

### 快速 check-in / log

`log` 用于 10 秒内把最近一个待完成 action 标记为 done / skipped / partial / deferred / blocked，并让周报完成率马上反映这次记录。除 `done` 状态的 reminder action 会 best-effort 同步把 Apple Reminders 中同名提醒标记完成外，其他状态只更新本地 SQLite，不写 Apple Calendar / Reminders。若需要按 Apple Reminders 的真实 `completionDate` 批量回收，或静音睡后自动作废提醒，请继续使用 `nudge reminders sync-completed --apply`：

```bash
nudge log done
nudge log skipped
nudge log partial "只做了一半，明天继续"
nudge log deferred "今晚没时间" --reason no_time --next-action reschedule
nudge log blocked "等对方回复" --reason waiting_on_other --next-action keep
nudge log parse "阅读完成了，读了 30 分钟，体感 7 分"
nudge log parse "读书只读了一半，明天继续" --dry-run --json

nudge log done --id <action_id>
nudge log done --match "阅读"
nudge check-in done
nudge check-in parse "今天没做力量训练，临时开会"
```

选择规则：

- 不传 `--id` / `--match` 时，默认更新最近一个 `created` 或 `pending` action。
- 传 `--id` 时，可以更新指定 action 的状态和 feedback，即使它已经是 `blocked` / `deferred`，用于补充 reason / next_action 或继续记录阻塞状态。
- `--match` 按 action summary 包含文本匹配；匹配到多个时会要求改用 `--id`。
- 命令后的备注会用 `nudge.feedback.v1` 写入 action feedback，并标记为 `source_type=subjective`；`--reason` 支持 `too_hard` / `no_time` / `conflict` / `low_energy` / `forgot` / `unclear` / `not_important` / `waiting_on_other`，`--next-action` 支持 `keep` / `reduce` / `split` / `reschedule` / `cancel`。
- `partial` 在 `review weekly` 中按 0.5 个完成计入完成率；`skipped` / `deferred` / `blocked` 计 0，但会进入未完成原因汇总。完成“关机流程 / 睡觉 / 上床 / 入睡”等睡眠终止型 reminder 后，后续同日晚睡眠 reminder 会自动变成 `skipped_after_sleep`，不计失败、不要求补反馈。
- `done` 如果命中的是 reminder action，会读取默认 Reminders list，并尝试按标题 + `scheduled_at` 精确匹配 Apple Reminders 里的同一条提醒并标记完成；JSON 输出会包含 `apple_reminder` 字段。该同步是 best-effort，失败时本地状态仍会写入，但输出会显示 Apple Reminders 同步失败信息。为避免误清重复课程 / 每日任务 / 每周任务，精确匹配不到唯一提醒时不会回退为按标题批量完成。
- `parse` 会调用 LLM，把自然语言反馈解析成 `done` / `skipped` / `partial` / `deferred` / `blocked`、备注、reason、next_action 和 metrics；代码层仍会校验 status/reason/next_action。解析结果为 `done` 且命中 reminder action 时，同样会尝试同步完成 Apple Reminders。
- `parse --dry-run --json` 只展示将更新的 action 和解析结果，不写 SQLite；脚本可读取 `ok`、`dry_run`、`parsed`、`action`、`feedback`。

### 查找空闲时间

```bash
nudge schedule "找2小时深度工作时间"
```

schedule 同样只基于配置日历计算忙闲时段；如果某个 Calendar 应参与排期，请先加入 `config.toml`。在 Calendar Full Access 可用时，底层读取使用 EventKit `predicateForEvents`；否则保持 AppleScript fallback。

### 习惯打卡

```bash
nudge habits
nudge habits log reading
```

### 本机环境诊断

`doctor` 只做只读检查，不会写入日历或提醒事项：

```bash
nudge doctor
nudge doctor --json
nudge doctor --config ./config.toml
```

它会检查 `config.toml`、LLM API key、Apple Calendar、Reminders、Notes、Mail 的 AppleScript 访问、Clock Shortcuts bridge，以及配置中引用的日历/提醒列表是否存在。Calendar / Reminders / Notes / Clock 检查会先显示当前 adapter，例如 `backend=native` / `backend=shortcuts`；尚未实现的 backend 会直接 FAIL。Calendar 列表诊断使用一次性 `name of calendars` 查询，避免日历较多时逐个读取超时；日常 Calendar 上下文读取优先走 Swift/EventKit，只有 Full Access 才能读，write-only 会自动回退 AppleScript。Reminders 会先用 AppleScript 检查列表名，再用 Swift/EventKit 的 due-today 查询确认能读取提醒事项数据；完成和删除提醒事项也优先走 Swift/EventKit，避免 AppleScript `whose ... due date ...` / `whose name ...` 在较大列表上卡住。Notes 诊断只列可见 folder 名称数量，不读取 note 正文；默认写入文件夹为 `Nudge`，缺权限时提示到“系统设置 → 隐私与安全性 → 自动化”授权。Clock 检查只确认本机是否有 `Nudge Create Alarm` 快捷指令；缺失时为 `WARN`，因为 Calendar / Reminders 仍可作为提醒替代。`FAIL` 会返回非 0；Reminders/Notes/Mail/Clock 数据读取或桥接问题会显示 `WARN` 和修复指引，但不阻塞核心 Calendar/LLM 诊断。

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

### Clock Shortcuts bridge

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

Shortcut 推荐配置：

1. 在 Shortcuts.app 新建快捷指令，名称固定为 `Nudge Create Alarm`。
2. 读取 Shortcut Input 的 JSON / Dictionary。
3. 从输入中取 `time` 和 `label`。
4. 调用 Clock → Create Alarm，并启用 alarm。
5. 手动用上面的 `shortcuts run` 命令验证一次。

### Skill Spec 验证和确定性执行

`skills` 命令只做本地静态验证、内置样例查看和确定性规则执行，不调用 LLM，不写入 Apple Calendar / Reminders / Notes：

```bash
nudge skills list
nudge skills list --json
nudge skills show strength-basics-12w
nudge skills show strength-basics-12w --json

nudge skills validate path/to/skill.yaml
nudge skills validate path/to/skill.yaml --json
nudge skills validate strength-basics-12w

nudge skills apply path/to/skill.yaml --context context.json
nudge skills apply path/to/skill.yaml --context context.json --json
nudge skills apply strength-basics-12w --context context.json --json

nudge skills dry-run path/to/skill.yaml --context context.json
nudge skills dry-run path/to/skill.yaml --context context.json --weeks 1 --json
nudge skills dry-run strength-basics-12w --context context.json --weeks 1 --json

nudge skills create /path/to/custom.yaml [--json]
nudge skills update <skill-id> /path/to/custom.yaml [--bump-version] [--json]
nudge skills delete <skill-id> [--json]
```

内置 Skill 样例当前有 3 个：`strength-basics-12w`（训练）、`deep-learning-sprint-4w`（学习）、`deep-work-weekly-rhythm`（工作效率）。这些样例随包发布，可直接用 ID 传给 `show` / `validate` / `apply` / `dry-run` / `list`，也可以把自己的 YAML 文件路径传给 `show` / `validate` / `apply` / `dry-run`。

`create/update/delete` 管理的是本机自定义 Skill（`~/.nudge/skills/<id>.yaml`）：

- `create`：把自定义 YAML 写入本机仓库；会写入 `updated_at`，必要时自动补齐 metadata 版本（`--bump-version` 会把 `x.y.z` 末位 +1）。
- `update`：更新现有自定义 Skill；更新前会创建历史快照到 `~/.nudge/skills/.history/<skill-id>/`，便于回溯版本；同样支持 `--bump-version`。
- `delete`：删除自定义 Skill 文件，内置 Skill 不允许删除。
- `list --json` 会返回 `source` 字段（`builtin` / `custom`），方便调用方过滤内置和自定义 Skill。

`validate` 会检查 Skill v0.1 必填字段、JSONLogic 安全子集、patch op 白名单和危险 path。`apply` 会读取 context JSON，依次执行 `personalization` 和 `adaptation` 中命中的确定性规则，输出变更后的 Skill/template。`create/update/delete` 会返回 `schema_version: "nudge.cli.v1"`；同时 `skills ... --json`、`do --json`、`log parse --json` 和 `dogfood weekly --json` 的机器可读输出也都带顶层 `schema_version: "nudge.cli.v1"`。

`dry-run` 会在 `apply` 的基础上，从个性化后的 `plan_template.phases[].sessions[]` 生成候选 Calendar action 预览。它不调用 LLM，不读取 Calendar，不写 Apple Calendar / Reminders / Notes；默认只预览第 1 周，可用 `--weeks` 调整预览周数。日期不会早于 `context.profile.start_date`；优先使用 `context.profile.preferred_days` / `preferred_time`，否则使用 `plan_template.defaults.preferred_days` / `preferred_time`。

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

返回 JSON 示例：

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

dry-run JSON 示例：

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

Skill 规范见：[Skill Spec](SKILL_SPEC.md)。

## 其他项目调用示例

### Shell

```bash
#!/usr/bin/env bash
set -euo pipefail

/path/to/nudge/bin/nudge "明天下午3点开会"
/path/to/nudge/bin/nudge do --json "明天下午3点开会"
/path/to/nudge/bin/nudge --dry-run "周五上午提醒我提交周报"
/path/to/nudge/bin/nudge log done --match "提交周报"
/path/to/nudge/bin/nudge dogfood weekly --save
/path/to/nudge/bin/nudge skills list
/path/to/nudge/bin/nudge skills show strength-basics-12w
/path/to/nudge/bin/nudge skills validate path/to/skill.yaml
/path/to/nudge/bin/nudge skills validate strength-basics-12w
```

### Python

```python
import subprocess

result = subprocess.run(
    ["/path/to/nudge/bin/nudge", "do", "--json", "明天下午3点开会"],
    capture_output=True,
    text=True,
    timeout=60,
)

if result.returncode != 0:
    raise RuntimeError(result.stderr)

import json
payload = json.loads(result.stdout)
print(payload["actions"])
```

### Node.js

```javascript
import { spawnSync } from "node:child_process";

const result = spawnSync(
  "/path/to/nudge/bin/nudge",
  ["do", "--json", "明天下午3点开会"],
  { encoding: "utf8" }
);

if (result.status !== 0) {
  throw new Error(result.stderr);
}

console.log(JSON.parse(result.stdout).actions);
```

## 返回码

- `exit code 0`：命令成功。对于写入命令，表示解析和写入流程全部完成。
- 非 0：命令失败或部分失败。调用方应读取 `stderr`，常见原因包括 LLM API key 缺失、LLM 返回非法 JSON、AppleScript/EventKit 权限不足、目标 Calendar/List 不存在、Apple 应用 timeout。

`nudge do` 的写入语义更严格：

- 全部 action 写入成功：返回 0，并把成功 action 记录到 SQLite。
- 部分 action 写入失败：返回非 0，输出 `部分 action 写入失败`，只记录成功项。
- 全部 action 写入失败：返回非 0，不写入本地成功记录。

如果看到 `部分 action 写入失败`，不要直接整条重试；已成功的 Calendar / Reminders 项可能已经存在，整条重试会造成重复创建。应根据输出里的失败项，只重试失败的那部分。

常见可操作错误包括：

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

## 配置和密钥

Nudge 默认读取仓库内 `config.toml`。本机默认使用通义千问 / DashScope：

```toml
[llm]
provider = "qwen"

[llm.models]
fast = "qwen-plus"
default = "qwen-plus"
strong = "qwen-plus"
```

密钥解析顺序是：

1. `config.toml [llm].api_key`（不推荐提交到仓库）
2. provider 专用环境变量，例如 `DASHSCOPE_API_KEY` / `QWEN_API_KEY`
3. 本机备份 `secrets.yaml`
4. 通用环境变量 `LLM_API_KEY`

这台机器上的长期密钥不要写入仓库。按全局工程规则，密钥应放在 `~/.config/nudge/secrets.yaml`，例如：

```yaml
dashscope_api_key: "your-key"
# 可选兼容键名：qwen_api_key、anthropic_api_key、openai_api_key、deepseek_api_key
```

默认读取路径可用环境变量覆盖：

```bash
export NUDGE_SECRETS_PATH="$HOME/.config/nudge/secrets.yaml"
# 兼容其他项目：也支持 EMAIL_SECRETS_PATH
```

其他 provider：`provider = "anthropic"` 读取 `ANTHROPIC_API_KEY` / `anthropic_api_key`；`provider = "openai"` 读取 `OPENAI_API_KEY` / `openai_api_key`；`provider = "deepseek"` 读取 `DEEPSEEK_API_KEY` / `deepseek_api_key`。

## Help

CLI 自带 help：

```bash
nudge --help
nudge do --help
nudge do --json --help
nudge doctor --help
nudge dogfood --help
nudge dogfood weekly --help
nudge skills --help
nudge skills list --help
nudge skills show --help
nudge skills validate --help
nudge skills apply --help
nudge skills dry-run --help
nudge skills create --help
nudge skills update --help
nudge skills delete --help
nudge briefing --help
nudge review --help
```
