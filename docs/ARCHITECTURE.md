# Nudge — Architecture v2

> v2 日期：2026-04-25  
> 对齐文档：[PRD v2](PRD.md)  
> 架构定位：Local-first，本地 CLI 优先，服务 Mac + iPhone 用户的执行闭环。

See also: [PRD](PRD.md) | [Design](DESIGN.md) | [Roadmap](ROADMAP.md) | [Business](BUSINESS.md) | [CLI](CLI.md) | [Skill Spec](SKILL_SPEC.md) | [Prompt Playbook](PROMPT_PLAYBOOK.md) | [Apple Adapter Survey](APPLE_ADAPTER_SURVEY.md) | [TODO](TODO.md)

---

## 0. v2 架构决策

v2 架构不再把 Cloud、Bot、App、Marketplace 当成当前系统中心。当前系统中心是：**本地 CLI + Apple 应用 + SQLite 状态 + LLM + 确定性 Skill Engine**。

### 架构原则

1. **Local-first**：默认在用户 Mac 上运行，不依赖云端服务。
2. **Mac + iPhone 优先**：Mac 写入 Apple Calendar / Reminders / Notes，通过 iCloud 同步到 iPhone。
3. **文档确认先于计划写入**：长期计划、周计划、Skill 或复盘调整要批量写入 Apple Calendar / Reminders / Clock / Notes 前，必须先生成或更新人类可读文本计划 / 变更说明，并经用户确认；这是产品级安全边界，不是某个个人计划的例外流程。
4. **副作用明确**：写 Calendar / Reminders / Notes / Clock 必须能 dry-run、可诊断、可解释失败。
5. **LLM 不拥有执行权**：LLM 只生成候选 action；代码负责校验、写入、记录。
6. **SQLite 是反馈真相**：Calendar 负责排期，Reminders 可提供打勾信号，完成/延期/阻塞等状态最终必须回到本地 action log。
7. **远程不直连 Mac**：跨设备同步通过 Cloud Relay 和设备出站连接完成，不把用户 Mac 暴露成公网 HTTP / 任意 RPC 服务。
8. **iCloud 不是授权**：Apple ID / iCloud 只负责 Apple 数据同步，每台 Mac / iPhone 都必须单独授予 Nudge 本机权限。
9. **iOS 不是常驻服务器**：iOS App 可做随身反馈、通知和部分 EventKit 执行，但不能假设 24 小时后台常驻。
10. **Skill 不执行任意代码**：Skill 走 YAML/JSON schema、JSONLogic 子集和 patch 白名单。
11. **Phase 2 可抽取**：本地模块边界要清晰，未来能抽成 Cloud Relay / API，但现在不提前造云平台。
12. **计划生成必须客观+主观**：每次生成下一轮 1-2 周执行计划，必须先合并客观信号（App/健康/Reminders/周报）和主观体验（主观难度、恢复、睡眠、情绪），再决定是否加量、降级或取消。

---

## 1. 当前本地架构

```text
┌──────────────────────────────────────────────────────────────┐
│ User / Other Projects / Agent                                │
│   nudge "..."                                                │
│   /path/to/nudge/bin/nudge "..."               │
└───────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ CLI Layer                                                     │
│ nudge/cli.py + nudge/commands/*                               │
│ do · doctor · briefing · review · schedule · habits · skills  │
└───────────────┬───────────────────────┬──────────────────────┘
                │                       │
                ▼                       ▼
┌─────────────────────────────┐  ┌─────────────────────────────┐
│ Brain / LLM                  │  │ Skill Engine                 │
│ nudge/brain.py               │  │ nudge/skills/*               │
│ nudge/llm.py                 │  │ schema · jsonlogic · patch   │
│ Qwen / Anthropic / OpenAI    │  │ deterministic apply          │
└───────────────┬─────────────┘  └──────────────┬──────────────┘
                │                               │
                └───────────────┬───────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────┐
│ Execution Layer                                               │
│ nudge/apple/* · nudge/health.py · nudge/state.py               │
│ AppleScript → Calendar / Reminders / Notes create/list / Mail fallback│
│ Swift/EventKit → Calendar scoped reads + Reminders reads/mut. │
│ Apple Health export ZIP → daily aggregates + workout metadata  │
│ SQLite → configured state dir, default install-base .nudge     │
└───────────────┬───────────────────────────────┬──────────────┘
                │                               │
                ▼                               ▼
        Apple Calendar / Reminders / Notes       Local SQLite state
                │
                ▼
        iCloud sync → iPhone
```

### 当前 runtime 依赖

| 依赖 | 用途 |
|------|------|
| Python 3.12+ | CLI 和本地逻辑 |
| click | CLI 子命令 |
| openai / anthropic | LLM provider SDK |
| PyYAML | Skill YAML 读取 |
| sqlite3 | 本地状态，Python 内置 |
| osascript / AppleScript | Calendar、Reminders、Notes 创建/列表、Mail、通知集成；EventKit 不可读时作为 Calendar/Reminders fallback |
| Swift / EventKit | Calendar 配置日历范围读取；Reminders 今日到期读取、完成、删除，规避 AppleScript 在大列表上按 date/name 过滤 timeout |
| shortcuts CLI | 通过本机 `Nudge Create Alarm` 快捷指令桥接 Apple Clock alarm；Clock 本身不依赖 AppleScript 字典 |

---

## 2. 模块边界

| 模块 | 文件 | 职责 | 不负责 |
|------|------|------|--------|
| CLI router | `nudge/cli.py` | Click 根命令、默认自然语言转 `do` | 业务逻辑 |
| Commands | `nudge/commands/*` | 子命令编排、用户输出、错误转 ClickException | 低层 AppleScript、LLM SDK 细节 |
| Agent Relay | `nudge/commands/agent.py` | 其他本机 agent / MCP wrapper 提交结构化 Apple actions 的中转站；不调用 LLM，复用 adapter、dry-run、JSON contract 和 SQLite tracking | 直接操作 AppleScript/EventKit、远端工具鉴权 |
| MCP Server | `nudge/commands/mcp.py` | 通过 stdio JSON-RPC 暴露写入 tool `apply_apple_actions`、只读诊断 tool `doctor_status` 和窄读取 tool `list_nudge_notes` | 普通 stdout 日志、任意 Calendar/Reminders 读取、任意 Notes folder 或正文读取 |
| Brain | `nudge/brain.py` | prompt、JSON 解析、briefing/review/adapt/check-in parse 逻辑 | 写入 Calendar / Reminders |
| LLM | `nudge/llm.py` | provider 抽象、API 调用、模型档位 | prompt 业务策略 |
| Config | `nudge/config.py` | config.toml、secrets.yaml、默认值 | 业务执行 |
| Adapt | `nudge/adapt.py` | 把 LLM 调整建议转换为 safe/unsafe 执行计划，并在确认后更新带 `external_id` 的 Calendar action | 生成建议、绕过用户确认 |
| Apple | `nudge/apple/*` | AppleScript 读写封装；Calendar 配置日历读取和 Reminders due-today / complete / delete 通过 Swift/EventKit 原生查询和 mutation；Notes 写指定 folder，并可只列 `Nudge` folder 标题；Clock alarm 通过 Shortcuts bridge | CLI 展示、状态记录 |
| Health import | `nudge/health.py` / `nudge/commands/health.py` | 解析 Apple Health 导出 ZIP，生成每日聚合和 workout 元数据；默认 dry-run，`--apply` 后写 SQLite | HealthKit 实时授权、iPhone 后台同步、原始样本或 GPX 路线存储 |
| Errors | `nudge/errors.py` | 把 LLM / AppleScript / EventKit 原始错误分类成可操作 CLI 文案 | 低层重试策略、写入副作用 |
| State | `nudge/state.py` | SQLite plans/actions/habits/evaluations/chat_history，以及 `health_imports` / `health_daily_summary` / `health_workouts` 聚合表 | LLM / AppleScript |
| Skills | `nudge/skills/*` | Skill v0.1 验证、内置样例发现和确定性规则执行 | LLM、真实日历写入 |
| Scripts | `scripts/*` | 安装和验证入口 | 产品逻辑 |

### 关键边界

- `nudge/commands/do.py` 可以调用 Brain、Apple、State，但不直接拼 AppleScript。
- `nudge/commands/agent.py` 是结构化中转入口，只接受 JSON action envelope；`nudge/commands/mcp.py` 包装它，而不是绕过 Nudge 的 adapter / 错误 / tracking 层。
- `nudge mcp serve` 的 stdout 是 MCP JSON-RPC 通道，不能写普通日志；所有工具结果必须放在 `content` / `structuredContent` 中。MCP 安全边界见 [MCP Security](MCP_SECURITY.md)。
- `nudge/skills/*` 不能调用 LLM、shell、网络或 Apple 应用。
- `nudge doctor` 只能只读检查，不写 Calendar / Reminders / Notes。
- `scripts/verify.sh` 是提交前验证入口，pre-commit 优先调用它。

---

## 3. 核心数据流

### 3.1 Natural language → Calendar action

```text
User text
  │
  ▼
CLI `do`
  │ load config + aliases
  ▼
Brain.parse_actions()
  │ LLM returns JSON actions
  ▼
format_action()
  │ dry-run? stop here
  ▼
Apple Calendar / Reminders / Notes writer
  │
  ├─ success → State.log_action(SQLite)
  └─ failure → user-visible error
```

Shadow paths：

| 路径 | 行为 |
|------|------|
| Empty input | CLI 提示提供 message / file / pipe |
| LLM key missing | `LLMError`，提示 provider key / secrets.yaml |
| LLM JSON invalid | Brain 层捕获并给出解析失败 |
| Calendar 权限失败 | Apple 层返回 `(False, message)`，CLI 输出错误 |
| 部分 action 成功 | 成功的 action 写入 state，失败项显示错误 |

### 3.2 Agent request → Apple app relay

```text
Other local agent / MCP client
  │ writes structured JSON request
  ▼
CLI `agent apply` 或 MCP `tools/call apply_apple_actions`
  │ validate request_id/source/actions
  │ plan-driven requests require text_plan_confirmed + text_plan_ref before dry-run
  │ no LLM, no natural-language parse
  ▼
Apple adapter selector
  │ native Calendar / native Reminders / native Notes / Shortcuts Clock
  ▼
Apple apps
  │ Calendar / Reminders / Notes / Clock writes
  ▼
Stable JSON response
  │ external_id, failures, errors
  ▼
SQLite action log for successful writes
```

`agent apply` 借鉴 `ical` / `rem` 的 JSON-first、ID-first 接口思路，但不复制第三方源码。当前支持 `calendar_event.create`、`reminder.create`、`alarm.create`、`note.create`；MCP tool `apply_apple_actions` 只做薄包装，把 tool args 转成同一份 request JSON。这样 Nudge 继续作为本机 Apple 操作中转站，统一处理权限、dry-run、部分失败、`external_id` 和错误分类。计划驱动请求必须显式携带 `plan_driven=true`、`text_plan_confirmed=true` 和非空 `text_plan_ref`，否则 engine 会在 dry-run 前返回 `AGENT_TEXT_PLAN_CONFIRMATION_REQUIRED`；确认 token 同时绑定这些字段，避免 dry-run 后替换文本计划引用。Notes 写入只创建新 note 到指定 folder，默认 `Nudge`；写入前会把 Markdown-ish 正文转换成人类可读的简单 Notes HTML，因为 Apple 备忘录不是 Markdown 渲染器。渲染器必须覆盖标题、列表、checkbox、强调、代码围栏和 Markdown 表格；测试必须断言 raw `#`、`- [ ]`、三反引号和 `|---|` 不会作为最终 Notes 正文残留。MCP 只读能力限制为 `doctor_status` 和 `list_nudge_notes`：前者只返回 PASS/WARN/FAIL、message 和修复建议，不返回个人条目内容；后者只列固定 `Nudge` folder 的标题和标题派生摘要，不读取正文、不搜索、不更新、不删除。

### 3.3 Doctor read-only diagnosis

```text
nudge doctor
  │
  ├─ load config
  ├─ create LLM provider and check API key
  ├─ list Calendar names
  ├─ list Reminders lists
  ├─ list Notes folders without reading note bodies
  └─ read Mail unread count
       │
       ▼
PASS / WARN / FAIL + 修复指引
```

`nudge doctor` 是 Phase 1.7 的关键救援工具。Calendar / LLM 失败为 FAIL；Reminders / Mail 由于 macOS 权限或数据访问 timeout 可以是 WARN，但必须给出具体修复路径。

### 3.4 Calendar context reads

briefing、chat、schedule、trainer 需要读取 Calendar 作为上下文。由于 Apple Calendar 里可能有节假日、订阅、Siri 建议等大量系统日历，默认扫描所有日历会明显变慢甚至 timeout。当前策略是：

- `nudge doctor` 用一次性 `name of calendars` 查询检查可见列表。
- 日常上下文只查询 `config.toml` 中配置的日历：`default_calendar`、`[calendars]` 和家庭成员 `calendar`。
- 配置日历读取优先走 Swift/EventKit `predicateForEvents`；这需要 macOS Calendar **Full Access**。如果当前进程只有 write-only EventKit 权限，helper 会返回明确错误，Python 层回退到已收窄的 AppleScript 单日历查询。
- 需要参与排期的 Calendar 必须显式写入配置；不配置的订阅日历不会拖慢 Nudge。

### 3.5 Apple Health export → SQLite 汇总

```text
iPhone Health export ZIP
  │
  ▼
CLI `health import`
  │ find HealthData XML
  │ stream parse Record / Workout
  │ dry-run? stop after counts
  ▼
SQLite health_imports / health_daily_summary / health_workouts
  │
  ▼
CLI `health daily` / 后续 review 输入
```

此路径用于把 Apple 健康导出 ZIP 中的近期结果拉回本地复盘。Nudge 只保存每日聚合和训练元数据：步数、距离、热量、运动分钟、睡眠、心率、HRV、体重、体脂、VO2Max 和 workout source/type/duration/distance/energy。Keep 数据如果已经写入 Apple 健康，会通过 `sourceName` 进入 workout 和 `source_counts`。Nudge 不保存原始样本或 GPX 路线，`apple_health_export/workout-routes/*.gpx` 只计数后忽略。

`health import` 默认 dry-run；只有显式 `--apply` 才写入 SQLite。日期窗口使用 `[--from, --to)`，便于按 1-2 周执行窗口导入最近数据，而不是把多年健康记录默认变成 Nudge 的日常工作集。直接 HealthKit / iOS Companion 自动同步仍属于后续 App 阶段能力。

### 3.6 Skill validate/apply/dry-run

```text
Skill YAML/JSON + context JSON
  │
  ▼
load_skill_file()
  │ yaml.safe_load / json.loads
  ▼
validate_skill()
  │ schema_version · required sections · JSONLogic · patch op · path safety
  ▼
personalize_skill()
  │ evaluate personalization.when
  │ apply patches
  ▼
apply_adaptations()
  │ evaluate adaptation.trigger
  │ apply patches
  ▼
dry_run_skill() 可选
  │ 从 plan_template.phases[].sessions[] 生成候选 Calendar action 预览
  ▼
Output personalized skill/template JSON 或 dry-run action JSON
```

此路径不调用 LLM，不读真实 Calendar，不写 Apple 应用，不读取 Skill 文件和 context 文件之外的数据。v0.1 dry-run 只做确定性预览，真实空闲时间排期仍属于后续增强。

### 3.6 Generate → Schedule → Track → Evaluate → Adapt

```text
Generate
  LLM / Skill 生成 action
    ↓
  1) 计划输入审查：客观指标 + 主观反馈评估
    ↓
Schedule
  Apple Calendar / Reminders 写入
    ↓
Track
  SQLite action log + check-in/log
  nudge log parse 可用 LLM 提取 status/note/metrics，但只更新 SQLite
  nudge reminders sync-completed 可把 Reminders completed 拉回为 done 候选
  Calendar 过去/移动/删除只作为待确认信号
    ↓
Evaluate
  review weekly 统计完成率和模式
  nudge dogfood weekly 汇总本周使用和 doctor 状态
    ↓
Adapt
  review weekly --adapt 生成建议
    ↓
User confirms
  safe action 更新 Calendar / SQLite
```

生成输入审查规则（统一要求）：

- 客观输入来源必须可追溯：Health 汇总（`nudge health daily`）、Reminders completed sync、Calendar 更新信号、`review weekly` / `dogfood weekly` 周报、复查异常状态。
- 主观反馈来源必须可记录：用户 check-in、反馈文本（`nudge log parse`）、以及每周总结里对执行难度、恢复、睡眠和情绪的评分。
- 决策输出必须给出两个闸门结果并与动作结论绑定：
  - 客观闸门是否允许加量：是 / 否
  - 主观闸门是否允许加量：是 / 否
  - 计划动作结论：`keep / split / reduce / reschedule / cancel / doctor`

当前已具备 Generate、Schedule、Track、Evaluate、Dogfood 报告和安全型 Adapt：`review weekly --adapt --dry-run` 会预览可执行调整，`--apply` 在确认后只更新带 `external_id` 的 Calendar action；`split` 会保留原 Calendar UID 作为第一段，并创建后续分段事件。缺少 `external_id` 的老 action 会显示为 unsafe，不按标题自动删除，避免误改真实日历。`nudge dogfood weekly` 是只读聚合层，读取 SQLite action 和 `nudge doctor` 结果，不调用 LLM，不写 Apple 应用；可用 `--json` 或 `--export-json` 输出机器可读周报。

### 3.7 Feedback return path

完成结果不是从 Calendar 推断出来的。Nudge 的反馈流是：

```text
Apple Calendar / Reminders / Clock / Notes / briefing
  │ 触达用户
  ▼
User feedback
  │ nudge log/check-in
  │ nudge reminders sync-completed
  │ future: IM feedback inbox
  ▼
State.actions
  │ status: done / partial / skipped / deferred / blocked / skipped_after_sleep
  │ feedback: source / note / raw_text / metrics / reason / next_action
  ▼
review weekly / dogfood weekly / adapt
```

边界规则：

- Calendar 只负责高层时间块、每日目标和关键安排；事件过去、被移动或被删除，都不能直接写成完成状态。
- Reminders 适合细颗粒任务；`nudge reminders sync-completed` 可以按日期读取 Nudge 创建的 reminder completed 状态，作为 `done` 候选写回 SQLite。完成“关机流程 / 睡觉 / 上床 / 入睡”等睡眠终止型 reminder 后，同日晚于该时间的睡眠 reminder 会自动变为 `skipped_after_sleep`，表示已睡后作废，不计失败；在 `sync-completed --apply` 路径下，Nudge 会同时尝试把这些后续 Apple Reminders 标记完成，避免睡后继续响。
- Clock / 通知只负责强触达，不保存完成结果。
- Mail / briefing 负责批量拉回未反馈项和复盘问题，不作为紧急提醒渠道。
- `report_action_status` 已接入 MCP / agent status 回写；它只写 Nudge 本地 action 状态与反馈，不读取 Calendar / Reminders / Mail 内容。`doctor_status` 只返回诊断状态和修复建议；Notes 除 `list_nudge_notes` 标题列表外不开放正文读取。

### 3.8 Apple Adapter 抽象边界

Apple 集成层现在有一层显式 adapter 抽象：`nudge.apple.adapters` 定义 `CalendarBackend` / `RemindersBackend` / `NotesBackend` / `ClockBackend` 协议、统一 `WriteResult`，并由 config selector 为一次命令解析出 backend。当前 runtime 仍保持默认行为：

- Calendar：`native`，项目内 EventKit 读快路径 + AppleScript 写入/fallback。
- Reminders：`native`，项目内 EventKit due-today / complete / delete 快路径 + AppleScript 列表/写入。
- Notes：`native`，AppleScript 创建 note 到指定 folder；`note.create` 会把 Markdown-ish 输入渲染成人类可读的简单 HTML，并处理标题、列表、checkbox、强调、代码围栏和 Markdown 表格；doctor 只列 folder 名称；MCP `list_nudge_notes` 只列固定 `Nudge` folder 的标题、标题派生摘要和日期，不读取 note 正文。
- Clock：`shortcuts`，本机 `Nudge Create Alarm` Shortcuts bridge。

已实现的配置入口：

```toml
[apple.calendar]
backend = "native"   # 当前唯一已实现

[apple.reminders]
backend = "native"   # 当前唯一已实现

[apple.notes]
backend = "native"   # 当前唯一已实现

[apple.clock]
backend = "shortcuts" # 当前唯一已实现
shortcut_name = "Nudge Create Alarm"
```

`nudge do` 和 `nudge chat` 通过 selector 调用 adapter，不再直接绑定低层 Apple 函数；`nudge doctor` 会显示当前 backend，例如 `backend=native` / `backend=shortcuts`。如果 config 选择 `ical` / `rem` / `ekctl` / MCP，当前版本会显式 FAIL / `APPLE_BACKEND_UNSUPPORTED`，不会静默退回或半接入。

外部开源工具 `ical`、`rem`、`ekctl` 和 MCP server 已进入调研范围，但不改变 Phase 1.7 默认 runtime。详见 [Apple Adapter Survey](APPLE_ADAPTER_SURVEY.md)。无论未来接入哪种 backend，都必须保留 Nudge 的 dry-run、稳定 JSON、`external_id` 追踪、部分失败非 0、统一错误分类和 `nudge doctor` 诊断语义。

### 3.9 CLI JSON contract

外部项目调用 CLI 时优先读取 stdout 的单段 JSON。当前稳定契约：

- `do --json` / 默认入口 `--json`：解析和写入结果，包含 `actions`、`failures`、`errors`。
- `agent apply --json`：其他 agent 提交结构化 Apple actions 的中转结果，包含 `request_id`、`source`、`actions`、`external_id`、`failures`、`errors`。
- `mcp serve`：stdio JSON-RPC MCP server，`tools/list` 暴露 `apply_apple_actions`、`report_action_status`、`doctor_status` 和 `list_nudge_notes`，`tools/call` 返回 MCP `content` + `structuredContent`。
- `log parse --json`：自然语言 check-in 解析和本地 SQLite 更新结果。
- `skills ... --json`：Skill 发现、验证、执行、dry-run 结果。
- `dogfood weekly --json` / `--export-json`：只读周报结构化结果。

这些输出统一带顶层 `schema_version = "nudge.cli.v1"`。破坏性字段变更必须升级该版本；新增字段可以保持同版本，并继续保证失败时 stdout 仍是可解析 JSON。

---

## 4. 错误与权限边界

### 4.1 macOS 权限

| 权限 | 当前入口 | 常见失败 | 处理 |
|------|----------|----------|------|
| Calendar | AppleScript + Swift/EventKit | 未授权、目标日历不存在、EventKit 只有 write-only 不是 full access | `nudge doctor` FAIL + 系统设置指引；上下文读取可回退到 AppleScript |
| Reminders | AppleScript + Swift/EventKit | 权限弹窗、EventKit full access 未授予、数据读取 timeout | WARN/FAIL + 用户在电脑前处理 |
| Notes | AppleScript | 自动化权限未授权、目标 folder 创建失败 | WARN/FAIL + 自动化权限指引；MCP/agent 只允许 create |
| Clock | Shortcuts CLI + Clock action | `Nudge Create Alarm` 快捷指令缺失、Shortcuts 卡住 | WARN + 创建 Shortcut 指引；可用 Calendar/Reminders 替代 |
| Mail | AppleScript 只读 | 自动化权限未授权 | WARN + 自动化权限指引 |
| Notifications | AppleScript | 通知权限被关 | 不阻塞核心路径 |

Reminders 权限曾是 P1 风险：AppleScript 可以列出列表但在 `due date` / `name` 过滤大列表时 timeout。当前 due-today 读取、完成和删除已优先走 Swift/EventKit，AppleScript 保留为 fallback；后续若继续扩展 Reminders 查询，应优先复用 EventKit。

### 4.2 错误输出原则

- 用户能修的错误，要给修复指引。
- 系统权限错误不要伪装成 LLM 或解析错误。
- `doctor` 中 WARN 不阻塞 Calendar 核心路径，但必须可见。
- 真实写入失败不能静默；必须显示 action 和失败原因。
- `nudge do` 部分写入失败必须返回非 0，只记录成功项，并提醒不要整条重试，避免重复创建。
- 测试中不真实写 Calendar / Reminders / Notes，使用 mock。

---

## 5. Skill Engine 架构

Skill Engine 当前由六个小模块组成：

| 模块 | 文件 | 职责 |
|------|------|------|
| Schema | `nudge/skills/schema.py` | 加载 YAML/JSON，校验 v0.1 必填字段、安全字段、rule 和 patch |
| JSONLogic | `nudge/skills/jsonlogic.py` | 执行安全 JSONLogic 子集 |
| Patch | `nudge/skills/patch.py` | 应用 `set/add/multiply/clamp/replace/remove/insert/tag/validate` |
| Engine | `nudge/skills/engine.py` | 编排 personalization 和 adaptation |
| Dry-run | `nudge/skills/dryrun.py` | 复用 engine 输出，生成无副作用的候选 Calendar action 预览 |
| Built-ins | `nudge/skills/builtins/*` | 打包训练、学习、工作效率 3 个内置 Skill 样例，并提供 `list/show` 发现能力 |

### 安全边界

Skill 不能：

- 执行 Python / JavaScript / shell。
- 读写文件系统。
- 访问网络。
- 读取密钥、环境变量、OAuth 文件。
- 调用 Apple 应用。
- 绕过用户确认修改日历。

Skill 可以：

- 声明 assessment。
- 声明 plan_template。
- 声明 tracking metrics。
- 用 JSONLogic 子集匹配 context。
- 用 patch 白名单修改模板。

---

## 6. Phase 2 扩展边界

v2 不是拒绝 Cloud，而是推迟到 Phase 1.7 验证后。

### 可抽取边界

| 本地模块 | Phase 2 可能抽取为 |
|----------|-------------------|
| `brain.py` | Brain API service |
| `state.py` | Server DB + sync API |
| `apple/*` | Calendar integration adapter |
| `commands/*` | Bot command handlers / API routes |
| `skills/*` | Skill validation service |

### Phase 2 Cloud Relay 架构草图

```text
IM / iOS / Web / Other Apps
    │
    │ HTTPS
    ▼
Cloud Relay
    │ account login
    │ device registry
    │ command queue
    │ conversation sync
    │ IM webhook
    │ offline buffering
    │
    ├─ optional Brain / LLM orchestration
    ├─ state sync API
    └─ durable command queue
          │
          │ outbound WebSocket / SSE / long-poll / periodic pull
          ▼
Mac Local Agent / iOS App
    │ local Apple permissions
    │ whitelist command executor
    ▼
Apple Calendar / Reminders / Notes / Clock
```

Cloud Relay 是中转站，不是远程 Apple 执行器。它可以保存命令 envelope、对话记录、执行结果和最小同步状态；不能保存 Apple ID 密码，不能直接操作用户本机 Apple apps，不能暴露任意 shell、AppleScript、文件读取或本机网络访问。

### Command protocol

Phase 2 远程协议使用白名单命令事件，而不是任意 RPC：

| Command | 执行位置 | 作用 |
|---------|----------|------|
| `apply_apple_actions` | Mac Local Agent / iOS App | 写入 Calendar / Reminders / Notes / Clock |
| `report_action_status` | Mac Local Agent / iOS App | 写入 Nudge 本地 action 状态和反馈 |
| `doctor_status` | Mac Local Agent | 返回 PASS/WARN/FAIL 和修复建议，不返回个人内容 |
| `sync_state` | Agent ↔ Relay | 同步 Nudge 自己的 action / feedback / review 摘要 |
| `conversation_message` | Relay / LLM / Agent | 同步对话和待处理输入 |

设备离线时，Cloud Relay 只排队。在线设备拉取命令、执行本机授权操作、回传 `succeeded` / `failed` / `needs_permission`。如果 Mac 关机，已提前写入 Apple Calendar / Reminders / Clock 的提醒继续由 Apple 系统负责；新命令等设备上线后执行。

### Local Agent runtime and offline semantics

Mac Local Agent 的目标是稳定执行本机授权操作，而不是保证所有智能逻辑实时在线。推荐运行形态是菜单栏 App / Login Item / LaunchAgent，加本地 CLI / MCP server：

- 开机登录自动启动；从睡眠唤醒后执行 catch-up。
- 本地执行队列由 `command_queue` / `daemon_runs` 持久化；`nudge daemon run` 启动时会回收 stale `running` 命令，未达到尝试上限的命令回到 `queued`，达到上限进入 `dead_letter`，人工确认后通过 `nudge daemon retry` 重放。
- `daemon enqueue` 对 `queued + running` 活跃深度有上限保护，避免异常循环导致本机队列无限堆积。
- `nudge daemon launchd ...` 是 `com.nudge.agent` 的无头自启动控制面；`nudge daemon health` 聚合 launchd、queue、stale running 和 dead_letter，作为菜单栏 / Login Item / 告警的底层健康信号。
- `nudge daemon app ...` 生成本机图形化健康入口，可加入 Login Item，用于显示当前 macOS 版本、Mac 型号、CPU 架构，一键查看 daemon health、打开日志和重启 daemon；它仍调用 CLI，不引入新的远程控制面。
- 关键提醒提前写入 Apple Calendar / Reminders / Clock，写入后由 Apple 系统和 iCloud 同步承担提醒。
- 新计划、IM 指令、LLM 解析、review/adapt、Reminders completed sync 在 agent 在线时处理；离线期间由 Cloud Relay 排队。
- 每个远程命令必须有 `command_id`，本地写入必须结合 `external_id` 和 `last_run_at` 幂等执行，避免重复创建 Calendar / Reminders。
- 权限缺失时返回 `needs_permission`，不在云端重试 Apple 写入，也不尝试绕过本机授权。

Apple ID / iCloud 是同步层，不是授权层。登录 Apple ID 可以让 Calendar / Reminders 同步到 iPhone，但不能让 Nudge 自动获得权限；每台 Mac / iPhone 都要在本机授权 Calendar、Reminders、Notifications、Automation / EventKit 等能力。

iOS App 是更好的随身入口，但不是 24 小时常驻 agent。iOS 可以做通知、check-in、今天计划、部分 EventKit 读写、App Intents / Shortcuts；后台刷新受系统限制，不能承担持续轮询、长时间监听 IM 或任意远程执行。

### 不提前实现的内容

- 多租户权限系统。
- 完整 admin dashboard。
- 多 Bot 同时接入。
- 外部设备直连用户 Mac。
- Cloud Relay 直接登录 Apple ID 或绕过本机授权。
- 假设 iOS App 可 24 小时后台常驻。
- 任意远程 RPC / shell / AppleScript / 文件读取。
- 复杂 billing。
- Skill Marketplace 审核与分成。

这些边界只在 Phase 2/3 真实触发时实现。

---

## 7. Apple 生态扩展

当前 macOS 使用 AppleScript。未来 iOS / macOS App 应改用原生框架：

| 能力 | 当前 | 未来 |
|------|------|------|
| Calendar / Reminders | Calendar 走 AppleScript；Reminders due-today / complete / delete 已走 EventKit，创建/列表仍走 AppleScript | EventKit |
| Siri / Shortcuts | 无 | App Intents |
| 通知 | macOS notification | APNs / UserNotifications |
| 健康数据 | Apple Health 导出 ZIP 通过 `nudge health import` 手动导入本地 SQLite；只保存每日聚合和 workout 元数据，不保存原始样本或 GPX 路线 | HealthKit / iOS Companion 自动授权读取 |

Apple App Intents 和 EventKit 会增强 Apple 自身 action 能力。Nudge 架构要把 Apple 当底层执行系统，而不是竞争对象。长期差异化在执行数据、Skill、review/adapt 和 coach loop。

iOS 端即使进入 Phase 3，也应按系统限制设计：用 EventKit / UserNotifications / App Intents 做明确授权的本机 action，用 APNs 或本地通知做触达，用用户打开 App 或系统唤起时完成 check-in / sync；不要假设普通 iOS App 能像服务器一样 24 小时常驻后台。

---

## 8. 架构验证

提交前验证入口：

```bash
scripts/verify.sh
```

当前验证覆盖：

- 完整 pytest。
- CLI help smoke。
- `nudge skills` help。
- 文档契约测试。

新增架构能力时必须同步：

- 测试。
- [CLI.md](CLI.md)（如果影响外部接口）。
- [SKILL_SPEC.md](SKILL_SPEC.md)（如果影响 Skill）。
- [TODO.md](TODO.md)。
- [CHANGELOG.md](../CHANGELOG.md)。
