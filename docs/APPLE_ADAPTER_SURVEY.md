# Nudge — Apple Adapter 调研文档

> 日期：2026-04-26  
> 结论：保留 Nudge 自己的计划解析、dry-run、状态追踪和错误层；底层 Apple 写入/读取层设计成可替换 adapter。Calendar / Reminders 后续可评估接入现有 EventKit CLI 或 MCP；Notes 先保留项目内人类可读写入型 AppleScript adapter；Clock 继续使用 Shortcuts bridge。

See also: [Architecture](ARCHITECTURE.md) | [CLI](CLI.md) | [TODO](../TODO.md) | [CHANGELOG](../CHANGELOG.md)

---

## 1. 调研背景

Nudge 当前定位是 **Mac + iPhone 本地执行教练**：在 Mac 本地解析计划，写入 Apple Calendar / Reminders / Notes / Clock，并通过 iCloud 同步到 iPhone。近期已经实现：

- Calendar：AppleScript 写入；配置日历读取优先 Swift/EventKit，AppleScript fallback。
- Reminders：AppleScript 写入；due-today、complete、delete 优先 Swift/EventKit，AppleScript fallback。
- Notes：AppleScript 写入指定 folder；写入前把 Markdown-ish 正文转换成人类可读的简单 Notes HTML；doctor 只列 folder 名称；MCP 可列固定 `Nudge` folder 的标题和标题派生摘要，不读取 note 正文。
- Clock：通过 `/usr/bin/shortcuts` 调用本机 `Nudge Create Alarm` 快捷指令写入 alarm。

用户提出的问题是：在继续投入底层 Apple 集成前，是否已有开源 CLI 或通用接口可复用，避免重复造轮子。

---

## 2. 调研结论

### 2.1 总体判断

| 领域 | 是否已有可复用开源方案 | 推荐策略 |
|------|------------------------|----------|
| Calendar | 有，EventKit CLI 已较成熟 | 保留当前实现；新增 adapter 抽象，后续可评估 `ical` / `ekctl` / MCP |
| Reminders | 有，EventKit CLI 已较成熟 | 保留当前实现；新增 adapter 抽象，后续可评估 `rem` / `ekctl` / MCP |
| Clock / Alarm | 没看到稳定公开 Clock.app CLI；Apple 官方 Shortcuts 支持 Clock actions | 继续使用 Shortcuts bridge；不改为 AppleScript |
| 更广 Apple 生态 | 有 MCP / AppleScript MCP / macOS app bridge | Phase 2 以后再评估；当前不把 MCP 作为核心运行依赖 |

### 2.2 不建议重做 Nudge 的原因

这些开源项目主要解决的是“如何对 Apple 应用 CRUD”。Nudge 的核心价值不在 CRUD，而在：

1. 自然语言计划解析。
2. `--dry-run` 先预览再写入。
3. SQLite 本地 action/state 追踪。
4. `review weekly --adapt` 和历史保留。
5. dogfood 周报、check-in/log、Skill Engine。
6. 对 Apple 权限、timeout、部分失败的统一错误文案。
7. 给其他项目调用的稳定 JSON 契约。

因此最佳路线是：**Nudge 继续拥有产品和执行语义；Apple 底层实现变成可替换 adapter。**


### 2.3 许可结论

> 说明：这是工程侧开源合规判断，不是法律意见。真正把第三方源码合入仓库前，应再次核对对应 commit 的 `LICENSE` 文件。

| 项目 | 当前公开 License | 是否可直接接受源码 | Nudge 推荐做法 |
|------|------------------|--------------------|----------------|
| `ical` | MIT | 可以 | 优先作为外部 CLI backend；若移植小段源码，保留 MIT notice |
| `rem` | MIT | 可以 | 优先作为外部 CLI backend；若移植小段源码，保留 MIT notice |
| `go-eventkit` | MIT | 可以 | 可参考或作为未来 Go helper 依赖；保留 MIT notice |
| `ekctl` | MIT | 可以 | 可参考 Swift/EventKit 结构；优先 subprocess adapter，不整仓库 vendor |
| `mcp-server-apple-events` | MIT | 可以 | 可参考 MCP tool schema 和错误处理；Phase 2+ 再评估接入 |
| `che-ical-mcp` | MIT | 可以 | 可参考 batch / duplicate / conflict / CLI mode；Phase 2+ 再评估 |
| `iMCP` | MIT | 可以 | 可参考“macOS app 处理权限 + stdio server”模式 |
| AppleScript MCP 示例 | MIT | 可以 | 可参考 MCP 包装方式；不作为 Calendar/Reminders 性能路线 |
| `eventkit-node` | MPL-2.0 | 谨慎 | 不建议把源码混入 AGPL 主代码；如使用，保持独立文件/包边界和 MPL notice |

Nudge 当前是 `AGPL-3.0-only`。MIT 代码通常可以并入 AGPL 项目，但必须保留原版权声明和许可文本。MPL-2.0 是文件级弱 copyleft，若直接复制或修改 MPL 文件，需要保留 MPL 文件边界和对应声明；为降低复杂度，当前不建议把 `eventkit-node` 源码直接混入 Nudge。

---

## 3. 现有开源 / 官方方案

### 3.1 Calendar CLI：`ical`

- 地址：https://ical.sidv.dev/
- 覆盖：macOS Calendar create / list / update / delete / search / export。
- 技术：Go + `go-eventkit`，通过 EventKit 直接访问 Calendar store。
- 特点：结构化 JSON、自然语言日期、agent skill、Homebrew / install script。
- 限制：macOS-only；仍受 macOS TCC Calendar 权限控制。

**对 Nudge 的启发：**

- 可作为 Calendar adapter 的候选 backend。
- 可作为 EventKit 性能和 JSON 输出契约参考。
- 不应直接替代 Nudge 的 action/state 层，否则会丢失 Nudge 的 dry-run、历史和安全更新逻辑。

### 3.2 Reminders CLI：`rem`

- 地址：https://rem.sidv.dev/
- 覆盖：macOS Reminders create / list / update / complete / delete / search / export。
- 技术：Go + `go-eventkit`，读写走 EventKit。
- 特点：结构化输出、自然语言日期、agent skill、读取/写入性能明显优于 AppleScript。
- 限制：macOS-only；部分 Reminders App 可见能力不一定由 EventKit 暴露，例如原生 flagged 字段，以及 iOS 共享列表 UI 中的“分配提醒事项”/ assignee。

**对 Nudge 的启发：**

- 可作为 Reminders adapter 的候选 backend。
- 可参考其 EventKit-first、AppleScript-only-for-gap 的策略。
- Nudge 当前 Reminders due-today / complete / delete 已走类似方向。
- 不应把 iOS Reminders 的原生“分配提醒事项”作为当前交付依赖：Apple 公开 `EKReminder` 字段覆盖标题、list、due/start date、priority、completed/completionDate 等常规属性，但没有稳定 assignee 属性。家庭组负责人归属继续使用“每个负责人一条 reminder + 标题/备注 attribution”的 fallback。

### 3.3 Calendar + Reminders CLI：`ekctl`

- 地址：https://schappi.com/blog/meet-ekctl-a-command-line-interface-for-managing-calendars-and-reminders-on-maco
- 覆盖：Calendar events + Reminders。
- 技术：Swift + EventKit。
- 特点：结构化 JSON，命令语义偏自动化 / pipeline。
- 限制：需要评估命令稳定性、安装方式、权限行为和维护活跃度。

**对 Nudge 的启发：**

- 如果想减少 Go/cgo 依赖，Swift EventKit CLI 是自然路线。
- Nudge 已经有 Swift helper，可以继续小步扩展，而不是一次性引入外部 CLI。

### 3.4 底层库：`go-eventkit` / `eventkit-node`

- `go-eventkit` Calendar：https://pkg.go.dev/github.com/BRO3886/go-eventkit/calendar
- `go-eventkit` Reminders：https://pkg.go.dev/github.com/BRO3886/go-eventkit/reminders
- `eventkit-node`：https://github.com/dacay/eventkit-node
- `eventkit-node` License / README：https://github.com/dacay/eventkit-node#license

这些库说明：EventKit 直连是当前 macOS Calendar / Reminders 自动化的主流高性能路线。它们共同的边界是：

- macOS-only。
- TCC 权限不可绕过。
- EventKit 能力由 Apple 公共 API 决定，不能覆盖所有 UI 可见字段。
- CLI / Node / Go 进程的权限归属取决于触发它的 Terminal / IDE / App。
- 共享提醒列表的原生协作/指派 UI 不等于公开 API 能力；若后续 Apple 增加稳定 assignment 字段，再在 Nudge delivery 层新增 native assignment adapter。

**对 Nudge 的启发：**

- 如果未来 Nudge 要彻底摆脱 AppleScript，可选方向是：
  - 继续维护项目内 Swift helper；或
  - 引入 Go/Swift 单独 helper binary；或
  - 接外部 `ical` / `rem` / `ekctl` backend。

### 3.5 通用接口：MCP

可参考项目：

- `mcp-server-apple-events`：https://github.com/FradSer/mcp-server-apple-events
- `che-ical-mcp`：https://mcpservers.org/servers/kiki830621/che-ical-mcp
- `iMCP`：https://github.com/mattt/iMCP
- AppleScript MCP 示例：https://github.com/joshrutkowski/applescript-mcp

MCP 方案的价值是把 Apple 应用暴露给 agent / client，而不是只给 Nudge 自己用。`iMCP` 这类 macOS app + stdio server 的模式尤其值得关注：用 GUI app 处理系统权限，用 CLI/MCP 对外暴露标准接口。

**对 Nudge 的启发：**

- Phase 2 以后，Nudge 可以暴露自己的 MCP server，或把 Apple 写入委托给 MCP backend。
- 但 Phase 1.7 不应把 MCP 作为核心依赖，因为当前目标是本机 dogfood 稳定，而不是 agent ecosystem 扩张。
- MCP client 可能把工具结果发给远端模型，需要明确隐私边界。

### 3.6 Apple 官方 Shortcuts CLI

- 命令行运行 Shortcuts：https://support.apple.com/guide/shortcuts-mac/run-shortcuts-from-the-command-line-apd455c82f02/mac
- Shortcuts Clock actions：https://support.apple.com/en-euro/101583

Apple 官方支持 `/usr/bin/shortcuts`：

- `shortcuts run "Shortcut Name"`
- `shortcuts run ... --input-path <file>`
- `shortcuts list`
- 成功返回 0，失败返回 1。

Apple 也明确把 Clock 的 Create Alarm / Toggle Alarm / Get All Alarms / Start Timer 支持到 macOS Shortcuts。

**对 Nudge 的启发：**

- 当前 Clock bridge 是正确路线。
- Shortcut 应设计成无交互、只接收结构化输入；否则命令行会等待用户输入。
- `nudge doctor` 只读检查 Shortcut 是否存在，缺失时 WARN，不阻塞 Calendar / Reminders。

### 3.7 AlarmKit

- Apple WWDC25：Wake up to the AlarmKit API：https://developer.apple.com/videos/play/wwdc2025/230/
- Apple sample：Scheduling an alarm with AlarmKit：https://developer.apple.com/documentation/AlarmKit/scheduling-an-alarm-with-alarmkit

AlarmKit 是 Apple 给第三方 app 创建自己 alarm/timer 的系统级 API。它值得关注，但现阶段不是 Nudge Clock bridge 的直接替代：

- 它不是“CLI 操作 Clock.app 现有闹钟”的接口。
- 它要求 app 授权和 Info.plist 使用说明。
- 它更适合未来 Nudge App，而不是当前 Python CLI。


### 3.8 本机 ical / rem smoke 结果（2026-04-26）

本轮评估使用临时下载的 release binary，不安装 Homebrew tap，不改系统 PATH：

- `/tmp/nudge-adapter-eval/ical`：`ical v0.9.0`
- `/tmp/nudge-adapter-eval/rem`：`rem v0.10.2`

#### 只读 smoke

| 命令 | 结果 | 观察 |
|------|------|------|
| `ical calendars -o json` | PASS，约 0.37s | 返回 list；字段含 `id/title/source/type/color/readOnly` |
| `ical today -o json` | PASS，约 0.18s | 返回 JSON list；当天无事件时为 `[]` |
| `rem lists -o json` | PASS，约 0.53s | 返回 list；字段含 `ID/Name/Color/Count` |
| `rem today -o json` | PASS，约 0.37s | 返回 JSON list；当天无提醒时为 `[]` |
| `ical` 缺失 Calendar | PASS，非 0 | stderr 含 missing calendar 和 available calendars，可分类 |
| `rem` 缺失 list | PASS，非 0 | stderr 含 list not found 和 available lists，可分类 |

同机对比：Nudge 当前 native `list_calendars()` 约 1.70s，配置日历 `get_today_events()` 约 3.56s；`list_reminder_lists()` 约 0.41s，`query_due_today()` 约 0.67s。因此 Calendar 读路径更值得优先评估 `ical` adapter；Reminders 当前 native 已接近 `rem` 只读速度，但 `rem` 的 CRUD/JSON/ID 语义更完整。

#### 真实写入 smoke

| 项目 | 流程 | 结果 | Adapter 结论 |
|------|------|------|--------------|
| `ical` | `add` → `search` → `show --id` → `delete --id` → `search` | PASS，测试事件已删除，最终搜索 `[]` | `search/show` JSON 稳定；`add/delete` 即使带 `-o json` 仍输出 plain text，不能只依赖 create stdout |
| `rem` | `add -o json` → `search` → `show` → `complete` → `delete --force` → `show` | PASS，测试提醒已删除，最终 `show` 返回 not found | `add/search/show` JSON 可直接取稳定 `id`；`complete/delete` 输出 plain text，但按 ID 操作可靠 |

重要安全发现：`ical add` 的 plain 输出只显示短 ID，例如 `305328BD-BEEB`。一次验证表明，用这个短 ID 直接 `ical delete <short-id>` 可能命中非目标事件。**Nudge adapter 不得使用 `ical add` plain stdout 的短 ID 作为 `external_id`。** 推荐流程是：创建后用唯一标题 + 窄时间范围 `ical search -o json` 找到完整 `id`，再用 `ical show/delete --id <full-id>` 精确操作。若 search 返回 0 或多条，写入应标记为不安全并提示人工处理。

本轮 smoke 结束后，`ical search '[Nudge Adapter Smoke]' --from today --to 'in 7 days' -o json` 返回 `[]`；`rem search '[Nudge Adapter Smoke]'` 返回无匹配。

---

## 4. 推荐 Adapter 设计

### 4.1 已实现配置入口

当前版本已经把下列配置写入 `config.toml`，但只启用默认 runtime；外部 backend 名称保留为后续评估边界，暂不允许生产写入。

```toml
[apple.calendar]
backend = "native"   # 当前唯一已实现；未来候选：ical | ekctl | mcp

[apple.reminders]
backend = "native"   # 当前唯一已实现；未来候选：rem | ekctl | mcp

[apple.notes]
backend = "native"   # 当前唯一已实现

[apple.clock]
backend = "shortcuts" # 当前唯一已实现
shortcut_name = "Nudge Create Alarm"
```

### 4.2 当前 Python 抽象

已新增 `nudge.apple.adapters`，命令层通过 selector 使用 adapter，不直接绑定低层 Apple 函数。当前最小 contract 覆盖 `do` 写入和 `doctor` 诊断；未来再向同一边界补 `list_events` / `update_event` / `delete_event` / `list_due_today` 等读改删方法。

```python
class CalendarBackend(Protocol):
    name: str
    def list_calendars(self) -> tuple[bool, list[str] | str]: ...
    def create_event(self, *, summary: str, start: datetime, end: datetime, calendar_name: str, location: str | None = None, notes: str | None = None) -> WriteResult: ...

class RemindersBackend(Protocol):
    name: str
    def list_lists(self) -> tuple[bool, list[str] | str]: ...
    def probe_read(self, list_name: str | None = None) -> tuple[bool, str]: ...
    def create_reminder(self, *, name: str, due_date: datetime, list_name: str, body: str | None = None, priority: int = 0, remind_date: datetime | None = None) -> WriteResult: ...

class NotesBackend(Protocol):
    name: str
    def list_folders(self) -> tuple[bool, list[str] | str]: ...
    def create_note(self, *, title: str, body: str, folder_name: str = "Nudge") -> WriteResult: ...

class ClockBackend(Protocol):
    name: str
    shortcut_name: str
    def check(self) -> tuple[bool, str]: ...
    def create_alarm(self, *, time: str, label: str) -> WriteResult: ...
```

`resolve_apple_backends(config)` 返回一次命令调用使用的 `AppleBackends(calendar, reminders, notes, clock)`。如果用户把 backend 配成尚未实现的 `ical` / `rem` / `ekctl` / MCP，`nudge doctor` 会 FAIL，`nudge do --json` 会返回 `APPLE_BACKEND_UNSUPPORTED`，避免静默降级或半接入。

### 4.2.1 Agent / MCP 中转接口

已新增 `nudge agent apply --json` 作为其他本机 agent 和后续 MCP wrapper 的统一中转入口。它借鉴 `ical` / `rem` 的 JSON-first、ID-first 接口形态，但不直接复制源码：调用方提交 `request_id`、`source`、`actions[]`，Nudge 负责 adapter 选择、dry-run、真实写入、SQLite tracking、`external_id` 和错误归一化。

当前支持：

- `calendar_event.create`
- `reminder.create`
- `alarm.create`
- `note.create`

已新增 `nudge mcp serve`，通过 stdio JSON-RPC 暴露 `apply_apple_actions` tool，把 tool args 转成同一份 agent request JSON；MCP 层不直接调用 AppleScript / EventKit，也不绕过 Nudge 的权限、错误和状态追踪边界。当前另有窄范围只读 `list_nudge_notes` tool，只列固定 `Nudge` folder 的标题、标题派生摘要和日期；不暴露任意 Calendar / Reminders 读取，不读 Notes 正文、不搜索全部 Notes、不更新、不删除。

### 4.3 Backend 候选

| Backend | Calendar | Reminders | Notes | Clock | 适用阶段 |
|---------|----------|-----------|-------|-------|----------|
| `native` | 当前 AppleScript + Swift/EventKit | 当前 AppleScript + Swift/EventKit | 当前 AppleScript 写入 + 固定 Nudge folder 标题列表 | 不适用 | 默认 |
| `ical` | 外部 `ical` CLI | 不适用 | 不适用 | 不适用 | P2 实验 |
| `rem` | 不适用 | 外部 `rem` CLI | 不适用 | 不适用 | P2 实验 |
| `ekctl` | 外部 `ekctl` CLI | 外部 `ekctl` CLI | 不适用 | 不适用 | P2 实验 |
| `mcp` | MCP tool call | MCP tool call | MCP tool call | 视 MCP server 能力 | Phase 2+ |
| `shortcuts` | 可行但不推荐 | 可行但不推荐 | 可行但不推荐 | 当前默认 | 当前 Clock |

### 4.4 Adapter 必须保持的 Nudge 语义

无论底层 backend 是什么，都必须保持：

1. `--dry-run` 不产生副作用。
2. `--json` stdout 只输出稳定 JSON。
3. 写入成功后必须返回可追踪 `external_id`。
4. 部分失败返回非 0，并且只记录成功 action。
5. 错误进入 `nudge/errors.py` 分类，不能把 backend 原始异常直接泄露给用户。
6. `nudge doctor` 能区分：backend 缺失、权限缺失、目标 Calendar/List 缺失、timeout、未知失败。
7. Calendar / Reminders / Notes 的读范围必须收窄；Notes MCP 读取只能列固定 `Nudge` folder 标题，默认不读正文，避免扫描或导出个人笔记内容。

---

## 5. 风险和边界

### 5.1 不要直接读 Apple 私有数据库

历史上有工具直接读 `Calendar.sqlitedb` 或 Messages `chat.db`。这类方式有几个风险：

- macOS 更新可能破坏 schema。
- TCC / sandbox 行为更难解释。
- 写入私有数据库风险高。
- 与 Nudge 的安全可解释目标冲突。

Nudge 的优先级应是：**EventKit / Shortcuts / 官方自动化 > 外部 EventKit CLI > MCP > AppleScript fallback > 私有数据库只读调研，不作为默认路线。**

### 5.2 AppleScript 仍可作为 fallback，但不适合大列表查询

AppleScript 的优点是系统自带、无需额外编译。缺点是：

- 大 Calendar / Reminders 查询容易 timeout。
- 按属性过滤会跨进程发送大量 Apple Events。
- 错误类型粗糙，不利于稳定 JSON contract。

当前 Nudge 已经把 Calendar 配置日历读取、Reminders due-today / complete / delete 迁到 Swift/EventKit 快路径，方向正确。

### 5.3 MCP 不等于本地隐私安全

MCP server 可以本地运行，但 MCP client / LLM provider 可能把工具结果发到远端。若未来接入 MCP，需要在文档和 CLI 中明确：

- 哪些数据离开本机。
- 是否允许只读模式。
- 写入是否需要确认。
- 工具结果是否包含 Calendar / Reminders 详情。


### 5.4 第三方源码接收边界

Nudge 可以学习这些项目的思想和公开接口设计，例如 EventKit-first、AppleScript fallback、稳定 JSON 输出、TCC 权限提示、MCP stdio server、Shortcuts bridge 等。思想和架构模式可以吸收，但直接复制源码时必须按 license 处理。

当前建议分三档：

1. **优先：吸收思想，自己实现。** 当前 Nudge 已有 Python CLI、状态层、dry-run、错误层和 JSON contract，直接照搬大段源码收益不高。
2. **可接受：小段 MIT 源码移植。** 如果确实需要移植边界处理或 helper 逻辑，应在文件头或 `THIRD_PARTY_NOTICES.md` 记录来源、原 license、修改说明，并保留 MIT notice。
3. **不推荐：整仓库 vendor。** 不把 `ical` / `rem` / `ekctl` / `iMCP` 整仓库塞进 Nudge；更好的方式是通过 adapter 调外部 binary、MCP server 或独立 helper。

如果未来必须引入第三方源码，需要先补一个仓库级 `THIRD_PARTY_NOTICES.md`，至少包含：项目名、来源 URL、commit/release、license、拷贝/修改的文件列表、是否修改、保留的原始 copyright notice。

---

## 6. 后续 TODO

### P1：先文档化，不改变默认行为

- [x] 新增本调研文档。
- [x] 补充开源许可结论：MIT 项目可参考/移植但需保留 notice；MPL-2.0 项目不混入主代码，保持文件/包边界。
- [x] 在 `config.toml` 中预留 `[apple.calendar]` / `[apple.reminders]` / `[apple.notes]` / `[apple.clock]` adapter 配置，默认保持 `native` / `native` / `native` / `shortcuts` runtime。
- [x] 为 `nudge doctor` 增加“backend 选择”输出字段，当前显示 `backend=native` / `backend=shortcuts`。

### P2：评估外部 CLI backend

- [x] 安装并 smoke `ical`：只读和真实写入 smoke 已完成；结论是 read/search/show JSON 可用，但 add/delete 输出 plain，且短 ID 删除不安全，adapter 必须 search 获取 full ID。
- [x] 安装并 smoke `rem`：只读和真实写入 smoke 已完成；结论是 add/search/show JSON 可用，complete/delete plain 但按 ID 可靠。
- [ ] 评估 `ekctl` 是否能同时替代 Calendar + Reminders helper。
- [x] 写 `CalendarBackend` / `RemindersBackend` / `NotesBackend` / `ClockBackend` 协议和 backend selector 测试；当前只实现 `NativeCalendarBackend` / `NativeRemindersBackend` / `NativeNotesBackend` / `ShortcutsClockBackend`。
- [ ] 增加 `ical` / `rem` adapter 的 dry-run contract 测试，不先接真实写入。

### P3：评估 MCP / App 化路线

- [ ] 评估 Nudge 自己暴露 MCP server 是否比调用第三方 MCP 更有价值。
- [x] 新增 `nudge agent apply` 作为 MCP tool 的底层 CLI 中转入口，先让其他本机 agent 可以结构化写入 Apple apps。
- [x] 新增 `nudge mcp serve`，暴露 MCP tool `apply_apple_actions`，内部复用 agent apply engine。
- [ ] 评估 `iMCP` 这种 macOS app 处理权限、CLI/MCP 走 stdio 的架构是否适合未来 Nudge App。
- [ ] 如果未来做 Nudge App，再重新评估 AlarmKit。

---

## 7. 当前决策

**决策：不重写当前 Apple 层；短期继续 native + Shortcuts。**

- Calendar：继续当前 Swift/EventKit 快路径 + AppleScript fallback。
- Reminders：继续当前 Swift/EventKit 快路径 + AppleScript fallback。
- Clock：继续 Shortcuts bridge。
- 外部开源 CLI：进入 P2 评估，不作为 Phase 1.7 默认依赖。
- MCP：进入 Phase 2+ 调研，不作为当前 dogfood 核心依赖。

这能避免为了替换底层 CRUD 而打断当前 dogfood 主线，同时为未来降低 AppleScript 维护成本留下清晰出口。

---

## 8. 参考来源

- `ical` macOS Calendar CLI：https://ical.sidv.dev/
- `ical` GitHub / License：https://github.com/BRO3886/ical
- `rem` macOS Reminders CLI：https://rem.sidv.dev/
- `rem` GitHub / License：https://github.com/BRO3886/rem
- `ekctl` Calendar / Reminders CLI：https://schappi.com/blog/meet-ekctl-a-command-line-interface-for-managing-calendars-and-reminders-on-maco
- `ekctl` GitHub / License：https://github.com/schappim/ekctl
- `go-eventkit` GitHub / License：https://github.com/BRO3886/go-eventkit
- `go-eventkit` Calendar：https://pkg.go.dev/github.com/BRO3886/go-eventkit/calendar
- `go-eventkit` Reminders：https://pkg.go.dev/github.com/BRO3886/go-eventkit/reminders
- `eventkit-node`：https://github.com/dacay/eventkit-node
- `eventkit-node` License / README：https://github.com/dacay/eventkit-node#license
- Apple Shortcuts CLI：https://support.apple.com/guide/shortcuts-mac/run-shortcuts-from-the-command-line-apd455c82f02/mac
- Apple Shortcuts Clock actions：https://support.apple.com/en-euro/101583
- Apple EventKit / Calendar WWDC23：https://developer.apple.com/videos/play/wwdc2023/10052/
- Apple AlarmKit WWDC25：https://developer.apple.com/videos/play/wwdc2025/230/
- Apple AlarmKit sample：https://developer.apple.com/documentation/AlarmKit/scheduling-an-alarm-with-alarmkit
- `mcp-server-apple-events` / License：https://github.com/FradSer/mcp-server-apple-events
- `che-ical-mcp`：https://mcpservers.org/servers/kiki830621/che-ical-mcp
- `che-ical-mcp` GitHub / License：https://github.com/kiki830621/che-ical-mcp
- `iMCP` / License：https://github.com/mattt/iMCP
- AppleScript MCP / License：https://github.com/joshrutkowski/applescript-mcp
- GitHub license guidance：https://docs.github.com/github/creating-cloning-and-archiving-repositories/licensing-a-repository
