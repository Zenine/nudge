# Nudge — MCP 安全策略

> 状态：Phase 1.7 本地 dogfood。当前 MCP 只作为本机 `stdio` server；写入由 `apply_apple_actions` 转发到 `nudge agent apply` engine，Notes 只通过 `list_nudge_notes` 读取固定 `Nudge` folder 的标题和标题派生摘要；不提供 HTTP 服务，不暴露任意 Calendar / Reminders 读取或 Notes 正文读取。

## 1. 设计原则

Nudge 的 MCP server 目标不是把 Apple 生态完全开放给任意 agent，而是提供一个**最小、可审计、本机运行**的 Apple 写入中转站。

核心原则：

1. **最小工具面**：当前暴露 `apply_apple_actions`、`report_action_status` 和 `list_nudge_notes`；不暴露 shell、文件系统、网络请求、任意 AppleScript、任意 Calendar / Reminders 读取，或 Notes 正文读取。
2. **结构化输入**：tool arguments 必须符合 `nudge agent apply` 的 action envelope；不接受自然语言直接写 Apple apps。
3. **复用安全执行层**：写入型 MCP 不直接调用 AppleScript/EventKit，必须经过 Nudge adapter、dry-run、统一错误、SQLite tracking 和 `external_id` 追踪；Notes 只读工具只能调用固定的标题列表函数。
4. **本机 stdio 优先**：当前只支持 stdio。stdout 只输出 JSON-RPC，普通日志不得写 stdout。
5. **默认不处理 secrets**：MCP tool 不接收 API key、OAuth token、账号密码；LLM key 仍由 Nudge 本机配置加载。
6. **写操作可追踪**：真实写入成功的 action 必须进入 SQLite action log；Calendar / Clock 成功时返回 `external_id`，Reminders / Notes 暂无稳定外部 ID 时保持 `external_id = null`。
7. **文本计划确认字段**：计划驱动写入必须显式携带 `plan_driven=true`、`text_plan_confirmed=true` 和非空 `text_plan_ref`，否则 `agent apply` / `apply_apple_actions` 在 dry-run 前返回 `AGENT_TEXT_PLAN_CONFIRMATION_REQUIRED`。
8. **确认 token 绑定**：`require_confirmation=true` 时，真实写入必须携带前一次匹配 dry-run 返回的 `dry_run_token`。

## 2. 当前 MCP 能力边界

启动方式：

```bash
/path/to/nudge/bin/nudge mcp serve
```

暴露的 tools：

| Tool | 能力 | 备注 |
|------|------|------|
| `apply_apple_actions` | 写入 Apple Calendar / Reminders / Notes / Clock | 支持文本计划确认字段和 `dry_run`；内部复用 `agent apply` engine；单次最多 10 个 action，schema 标记 `maxItems=10` |
| `report_action_status` | 本地写入 action 状态与反馈 | 不读取/不写 Calendar / Reminders / Notes / Mail |
| `doctor_status` | 只读返回本机配置、权限和 backend 诊断状态 | 只返回 PASS/WARN/FAIL、message 和修复建议；不返回 Calendar / Reminders / Mail 条目内容 |
| `list_nudge_notes` | 列出 Apple Notes 固定 `Nudge` folder 中的 note 标题和标题派生摘要 | 只接受 `limit`；不接受 folder；不读取正文 |

Capability 分类：

| Tool | Capability | 是否写 Apple apps | 是否读取个人内容 | 确认策略 |
|------|------------|-------------------|------------------|----------|
| `apply_apple_actions` | 写入 Apple apps | 是，仅 create 类 action | 否 | 必须先 dry-run，用户确认后带匹配 `dry_run_token` 写入 |
| `report_action_status` | 写本地 SQLite 状态 | 否 | 否 | 可由可信本地自动化调用；不得把它包装成 Apple 数据读取工具 |
| `doctor_status` | 只读本机诊断 | 否 | 否，只返回诊断状态和 hint | 可自动调用；调用方仍应把 FAIL/WARN 展示给用户 |
| `list_nudge_notes` | 窄范围只读 Notes 标题 | 否 | 只读固定 `Nudge` folder 的标题和标题派生摘要，不读正文 | 可自动调用；不得暴露 folder、搜索词或正文读取参数 |

说明：MCP 官方 `ToolAnnotations`（如 `readOnlyHint` / `destructiveHint` / `idempotentHint`）只能作为客户端提示，不能替代服务端安全边界。`nudge mcp serve` 会在 `tools/list` 中按上表语义返回 annotations，方便客户端 UI 分组；Nudge 的真实边界仍以工具名称、schema、参数白名单、dry-run token 和本地执行层校验为准。

当前支持 action：

- `calendar_event.create`
- `reminder.create`
- `alarm.create`
- `note.create`

`note.create` 只用于创建给人看的计划文档。调用方可以提交 Markdown-ish 正文，但 Nudge 会在本机写入前转换成简单 Notes HTML；MCP 不把 Apple Notes 当作 Markdown 源码仓库，也不把 Notes 当作状态追踪系统。

当前明确不支持：

- 任意 shell 命令。
- 任意 AppleScript 执行。
- Calendar / Reminders / Mail 的任意读取和全文导出；`doctor_status` 只返回诊断状态和修复建议。
- 读取 Notes 正文、搜索全部 Notes、传任意 folder、按标题更新或删除 note。
- 批量删除、按标题删除、按模糊匹配修改。
- 第三方 token 透传。
- HTTP / SSE 远程 MCP transport。

## 3. 官方 MCP 安全要求对 Nudge 的落地

官方 MCP 文档强调：MCP 消息基于 JSON-RPC；tools 会被模型自动发现和调用；对敏感工具应有用户可见的授权/确认；本地 MCP server 可能带来任意代码执行、数据外泄、数据损坏等风险；stdio server 不应向 stdout 写普通日志。

Nudge 当前落地如下：

| 官方关注点 | Nudge 当前策略 |
|------------|----------------|
| Tool 调用可被模型触发 | 只暴露窄工具集；文档要求 MCP client 对写工具启用人工确认 |
| Local MCP server compromise | 只建议配置固定路径 `bin/nudge mcp serve`；不要配置 `curl | sh`、`npx` 或未知脚本 |
| Scope minimization | 当前没有 broad scope；写入只支持 create 类 action；`doctor_status` 只读诊断状态；Notes 只读固定 `Nudge` folder 的标题，不读正文 |
| Token passthrough | 禁止 tool arguments 携带 token；Nudge 不把上游 token 传给下游 API |
| stdout 污染 | `mcp serve` stdout 只输出 JSON-RPC；日志必须走 stderr 或文件 |
| 数据外泄 | Calendar/Reminders/Mail 不暴露条目读取工具；`doctor_status` 只返回 PASS/WARN/FAIL 和修复建议；`list_nudge_notes` 只返回 `Nudge` folder 标题、标题派生摘要和日期，不返回正文 |

参考：

- MCP Base Protocol / JSON-RPC：https://modelcontextprotocol.io/specification/2025-11-25/basic
- MCP Tools：https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- MCP Security Best Practices：https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices
- MCP Authorization：https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization
- MCP server stdio logging guidance：https://modelcontextprotocol.io/docs/develop/build-server

## 4. 使用策略

### 4.1 MCP client 配置

推荐配置固定路径，避免 PATH 被污染：

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

不要这样配置：

```json
{
  "command": "sh",
  "args": ["-c", "curl https://example.com/install.sh | sh && nudge mcp serve"]
}
```

### 4.2 写入确认

当前 `apply_apple_actions` 是写工具。推荐客户端策略：

1. 如果请求来源是长期计划、周计划、Skill 或复盘调整等计划驱动写入，客户端 / agent 必须先展示并确认人类可读文本计划或变更说明；文本确认是 dry-run 之前的前置条件。
2. 计划驱动 request 必须设置 `plan_driven=true`、`text_plan_confirmed=true`，并填写非空 `text_plan_ref`；缺少任一字段会被服务端拒绝为 `AGENT_TEXT_PLAN_CONFIRMATION_REQUIRED`。
3. MCP client 必须对写工具开启用户可见的确认 UI，把将写入的 Calendar / Reminder / Note / Alarm 明确展示给用户。
4. 文本确认通过后，默认调用 `dry_run=true` 和 `require_confirmation=true`。
5. 用户确认 action dry-run 后，才用同一 `request_id`、`source`、`plan_driven`、`text_plan_confirmed`、`text_plan_ref` 和完全相同的 `actions` 调用 `dry_run=false`，并带回 `dry_run_token`。
6. 如果 dry-run 后修改了任意 action、target、时间或内容，必须重新 dry-run 获取新 token。
7. 如果返回 `ok=false`，只处理失败项，不要整包重试，避免重复创建已成功项。

`dry_run_token` 使用本机状态目录下的 `agent_confirm_secret` 作为 HMAC secret 生成；状态目录可由 `NUDGE_STATE_DIR` 或 `config.toml [state].dir` 覆盖，默认是安装底座下的 `.nudge/`。secret 首次使用时以 `0600` 权限创建。它只用于绑定“用户看过的 dry-run 摘要”和“随后真实写入的同一请求”，不替代 MCP client 自身的用户确认 UI，也不是跨设备身份凭证。

### 4.2.1 MCP client 安全检查清单

接入任何 MCP client 时，先按这份 checklist 检查，不依赖某个客户端的私有配置名：

- **固定 server 命令路径**：`command` 使用 `/path/to/nudge/bin/nudge`，不要用相对路径、PATH 查找、`npx`、`curl | sh` 或 shell wrapper。
- **开启写工具人工确认**：凡是调用 `apply_apple_actions`，客户端必须在 UI 中展示将写入的 app、标题、时间、目标 Calendar/List/Folder，以及 action 数量。
- **计划写入先确认文本**：如果 action 来自长期计划、周计划、Skill、复盘调整或其他批量计划生成，客户端必须先让用户确认人类可读文本计划 / 变更说明；不能直接把计划转成 action 写入。调用 `apply_apple_actions` 时必须带 `plan_driven=true`、`text_plan_confirmed=true` 和 `text_plan_ref`，否则服务端返回 `AGENT_TEXT_PLAN_CONFIRMATION_REQUIRED`。
- **默认先 dry-run**：首次调用写工具应设置 `dry_run=true` 和 `require_confirmation=true`；真实写入必须带回同一 request 的 `dry_run_token`。
- **修改即重新预览**：dry-run 后只要改了 `request_id`、`source`、`actions`、target、时间或正文，就必须重新 dry-run，不复用旧 token。
- **按 capability 分组授权**：只读/诊断工具（`doctor_status`、`list_nudge_notes`）可以和写入工具分开显示；写 Apple apps 的 `apply_apple_actions` 不应被放进“自动允许”组。
- **小批量执行**：每批最多 10 个 action；更大的计划拆成多批，每批独立 dry-run、确认、写入。
- **失败只重试失败项**：如果 `ok=false` 或 `failures[]` 非空，只根据失败项构造新 request，不要原样整包重试。
- **不扩大 scope**：不要通过 MCP client 自定义 prompt 或中间层把自然语言直接映射到任意 shell、AppleScript、文件读取或 Notes 正文读取。

### 4.3 请求约束

调用方应遵守：

- `request_id` 应可追踪，建议包含调用方、日期和短随机后缀。
- `source` 应填写 agent / workflow 名称。
- Calendar / Reminder / Notes folder 目标名称必须和 Apple app 中完全一致；Notes 默认写入 `Nudge` folder，当前只创建新 note。
- 时间必须使用 `YYYY-MM-DD HH:MM`；alarm 使用 `HH:MM`。非法时间、结束时间不晚于开始时间，或必填字段缺失都会返回 `AGENT_REQUEST_INVALID`，且不会写入 Apple 应用。
- 单次请求必须保持小批量：`actions` 最多 10 个，MCP schema 用 `maxItems=10` 暴露此限制；超限返回 `AGENT_BATCH_TOO_LARGE`，且不会进入 Apple 写入路径。更大的计划必须拆成多次 request，每批都先 dry-run / 确认。

### 4.4 只读与本地状态工具约束

`doctor_status`、`list_nudge_notes` 与 `report_action_status` 是当前可用的只读/本地状态 tool。调用方应遵守：

- `report_action_status` 仅用于写本地状态，不读取个人内容，不触发 Apple 应用。
- `action_id` 必须存在于本机 SQLite；否则返回 `AGENT_ACTION_NOT_FOUND`。
- `status` 仅允许 `done` / `skipped` / `partial` / `deferred` / `blocked`。
- `reason` 和 `next_action` 必须为约定枚举；`feedback` 只能是对象。

`doctor_status` 是本机诊断 tool。调用方应遵守：

- 只能传 `include_pass`，默认 `true`；传 `config_path`、文件路径或 Apple 数据读取参数会返回 `MCP_REQUEST_INVALID`。
- 返回字段只包含 `summary`、`checks` 和 `errors`；`checks` 只含 `status`、`name`、`message`、`hint`。
- 它会复用 `nudge doctor` 的只读检查，因此可能触发本机权限诊断，但不会写 Apple 应用，不读取 Notes body，不返回 Calendar event、Reminder item 或 Mail message 内容。

`list_nudge_notes` 是当前唯一 Apple 内容读取 tool。调用方应遵守：

- 只能读取 Apple Notes 的固定 `Nudge` folder。
- 只能传 `limit`，默认 20，最大 50；传 `folder`、搜索词或正文读取参数会返回 `MCP_REQUEST_INVALID`。
- 返回字段只包含 `title`、`summary`、`created_at`、`modified_at`；`summary` 由标题派生，不读取 note body。
- 如果需要真正基于正文总结，必须新增单独设计和确认流程，不能复用本工具绕过安全边界。

## 5. 错误与审计策略

MCP tool 返回 MCP `CallToolResult`：

- `content[0].text`：完整 Nudge JSON 字符串。
- `structuredContent`：同一份结构化 payload。
- `isError=true`：请求结构错误、doctor 存在 FAIL、未实现 backend、或部分/全部写入失败。

Nudge JSON 中：

- `ok=false` 表示调用方不能假设所有 action 成功。
- `failures[]` 只列失败 action。
- `errors[]` 保留机器可读错误码。
- 成功写入的 action 会进入本地 SQLite action log。

重要错误码：

| 错误码 | 含义 | 调用方处理 |
|--------|------|------------|
| `AGENT_BATCH_TOO_LARGE` | `apply_apple_actions` / `agent apply` 单次 action 数超过 10 | 拆成每批最多 10 个 action；每批都先 dry-run / 确认，不要整包盲目重试 |
| `AGENT_REQUEST_INVALID` | 输入结构或 action 值不符合 contract | 修正 JSON、时间格式或时间范围，不要重试真实写入 |
| `AGENT_TEXT_PLAN_CONFIRMATION_REQUIRED` | `plan_driven=true` 但缺少 `text_plan_confirmed=true` 或 `text_plan_ref` | 先确认人类可读文本计划，再重新 dry-run |
| `AGENT_CONFIRMATION_REQUIRED` | `require_confirmation=true` 但缺少 `dry_run_token` | 先 dry-run，带回返回 token |
| `AGENT_CONFIRMATION_INVALID` | `dry_run_token` 与当前 request 摘要不匹配 | 重新 dry-run，不要复用旧 token 写不同内容 |
| `MCP_REQUEST_INVALID` | MCP tool arguments 不符合安全 contract | 修正参数；不要传 folder、搜索词、正文读取参数、config_path 或任意文件路径 |
| `APPLE_BACKEND_UNSUPPORTED` | config 选择了尚未实现 backend | 切回 `native` / `shortcuts` 或等待 backend 接入 |
| `APPLE_PERMISSION_DENIED` | macOS 权限不足 | 提示用户在本机处理 Calendar / Reminders / Notes / Automation 权限，再运行 `nudge doctor` |
| `APPLE_TARGET_NOT_FOUND` | Calendar/List/Folder 不存在 | 修正配置或目标名称 |
| `CLOCK_SHORTCUT_MISSING` | Clock Shortcut 缺失 | 创建 `Nudge Create Alarm` 或禁用 alarm action |

## 6. 未来增强

按优先级：

1. **客户端配置指南**：针对常用 MCP client 增加配置截图/示例，明确必须开启写工具确认 UI。
2. **可配置批量上限**：当前默认硬上限为 10；如未来确需调整，应通过显式本机配置和测试，而不是让 MCP client 自行覆盖。
3. **只读 capability 分离**：`doctor_status` 已作为诊断只读 tool 单独命名；如果未来增加其他读取工具，必须单独命名、单独文档化，并默认最小范围读取。
4. **结构化反馈回写**：`report_action_status` 已支持写 Nudge 本地 SQLite action 状态（status、note、reason、next_action、feedback 合并字段），并严格限制只读/只写边界；不得读取 Calendar / Reminders / Notes / Mail 内容。
5. **操作审计导出**：增加按 `source` / `request_id` 查询最近写入记录的只读 CLI，不直接暴露完整日历内容。
6. **HTTP transport 另行设计**：若未来支持 HTTP/SSE MCP，必须重新设计 auth、CSRF、origin、token、HTTPS 和 scope，不复用当前 stdio 假设；跨设备优先走 Cloud Relay 命令队列，而不是把本机 MCP server 暴露到公网。

## 7. 当前决策

- Phase 1.7 只启用本机 stdio MCP。
- 只暴露 `apply_apple_actions` 写入工具、`report_action_status` 本地反馈写工具、`doctor_status` 只读诊断工具，另有 `list_nudge_notes` 一个窄范围只读工具。
- 不做 token passthrough。
- 不暴露任意个人内容读取工具；`doctor_status` 只返回诊断状态和修复建议；Notes 只允许 `note.create` 写入指定 folder，以及 `list_nudge_notes` 列固定 `Nudge` folder 的标题和标题派生摘要，不读取 note bodies。
- MCP 是 `agent apply` / `report_action_status` 的 wrapper，不是第二套 Apple 操作实现。
- `apply_apple_actions` 和 `agent apply` 单次最多 10 个 action；MCP schema 通过 `maxItems=10` 暴露限制，超限返回 `AGENT_BATCH_TOO_LARGE`。
- 计划驱动写入的文本确认已成为服务端校验字段；`plan_driven=true` 时缺少 `text_plan_confirmed=true` 或 `text_plan_ref` 会在 dry-run 前被拒绝。
- 反馈回写 tool 已启用；仍禁止读取个人内容或绕过 Apple 写入确认。
- 未来跨设备同步不通过公网直连本机 MCP；Cloud Relay 只能排队白名单命令，由 Mac / iOS agent 出站拉取后本机执行。
- Apple ID / iCloud 只用于 Apple 自身同步，不是 Nudge 授权；每台设备必须单独授权本机 Apple 权限。
- iOS agent 不能被当成 24 小时后台 MCP server；远程命令必须允许排队、过期和 `needs_permission`。
- `require_confirmation=true` 已启用本机 HMAC `dry_run_token` 绑定；它防止 dry-run 后内容被悄悄改写，但不替代 MCP client 的用户确认 UI。
