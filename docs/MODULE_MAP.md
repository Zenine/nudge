# Nudge 源码模块地图

这份文档用于快速定位代码。它不替代 [Architecture v2](ARCHITECTURE.md)，而是回答一个更日常的问题：想改某个功能时，应该先看哪些文件。

## 1. 读源码的主线

建议按这条线理解 Nudge：

1. `nudge/cli.py`：Click 根入口，负责把根命令文本转给 `do`，并注册所有子命令。
2. `nudge/commands/do.py`：自然语言到 Apple action 的主路径，串起配置、LLM、dry-run、写入和状态记录。
3. `nudge/commands/agent.py`：结构化 action 中转入口，不调用 LLM，是其他本机 agent 和 MCP wrapper 的稳定底座。
4. `nudge/apple/`：Apple Calendar / Reminders / Notes / Clock 的真实适配层。
5. `nudge/state.py`：SQLite 本地状态，包括 action、habit、review、chat history 和健康汇总。
6. `nudge/brain.py` 与 `nudge/llm.py`：自然语言解析、briefing、review、adapt 等 LLM 编排。
7. `nudge/skills/`：Skill Spec 验证和确定性规则执行，不碰 LLM、shell、网络或 Apple 应用。

如果只想理解“用户一句话如何变成日历/提醒事项”，先读 `cli.py`、`commands/do.py`、`brain.py`、`apple/` 和 `state.py`。

## 2. CLI 层

### `nudge/cli.py`

职责：

- 定义根命令和全局参数。
- 注册 `do`、`doctor`、`briefing`、`review`、`schedule`、`daily`、`docs`、`daemon`、`agent`、`mcp`、`skills` 等子命令。
- 支持 `nudge "明天早上8点开会"` 这种根命令自然语言简写。
- 处理 `--file` 和管道输入。

适合查：

- 某个子命令在哪里注册。
- 根命令文本为什么会进入 `do`。
- 全局 `--dry-run`、`--json`、`--file` 行为。

### `nudge/commands/*`

职责：

- 每个文件对应一个 CLI 功能域。
- 负责命令参数、用户输出、JSON 输出、错误转 `click.ClickException`。
- 编排底层模块，但不直接承载 AppleScript / EventKit 细节。

重点文件：

- `commands/do.py`：自然语言 action 创建主路径。
- `commands/agent.py`：结构化 Apple action relay。
- `commands/mcp.py`：stdio MCP server wrapper。
- `commands/doctor.py`：只读本机诊断。
- `commands/briefing.py`：早晚简报。
- `commands/review.py`：周报、adapt 建议和安全 apply。
- `commands/daily.py`：每日同步聚合入口。
- `commands/docs.py`：只读文档审计入口。
- `commands/reminders.py`：Apple Reminders 完成状态同步。
- `commands/daemon.py`：本地队列、launchd、恢复和重试。
- `commands/health.py`：Apple 健康导出导入与查询。
- `commands/db.py`：SQLite 备份、导出、恢复。
- `commands/skills.py`：Skill 验证、展示、apply 和 dry-run。

## 3. Apple 集成层

### `nudge/apple/`

职责：

- 封装 AppleScript、Swift/EventKit helper、Shortcuts CLI 和 macOS 通知。
- 对上层返回可解释的成功/失败结果。
- 保持 Apple 权限、timeout、fallback 和正文格式化逻辑集中。

重点文件：

- `apple/calendar.py`：Calendar 写入和读取。
- `apple/reminders.py`：Reminders 创建、读取、完成和删除。
- `apple/notes.py`：Notes folder 检查、标题列表和人类可读 HTML 写入。
- `apple/clock.py`：通过 Shortcuts bridge 创建 Clock 闹钟。
- `apple/mail.py`：Mail 简报信号读取。
- `apple/notifications.py`：macOS 通知。
- `apple/common.py`：AppleScript 执行、错误和共享工具。
- `apple/adapters.py`：结构化 action 到具体 Apple adapter 的分发。
- `apple/mock_backends.py`：in-memory backend 示例，用于非 macOS 测试或 agent 写入路径回归。
- `apple/eventkit_*.swift`：EventKit 原生 helper，用于 Calendar / Reminders 性能和权限边界。

适合查：

- 某个 Apple 应用写入失败时错误从哪里来。
- Notes 为什么要把 Markdown-ish 内容转成 HTML。
- Calendar/Reminders 什么时候走 Swift/EventKit，什么时候 fallback 到 AppleScript。

## 4. LLM 与自然语言编排

### `nudge/brain.py`

职责：

- 维护 prompt 和自然语言解析策略。
- 把用户输入、briefing、review、adapt、check-in parse 等场景转成结构化结果。
- 处理 LLM 返回 JSON 的解析和降级。

适合查：

- “一句话排期”如何变成 action。
- 周报 adapt 建议如何生成。
- check-in / log parse 的结构化字段。

### `nudge/llm.py`

职责：

- 抽象不同 provider。
- 支持 Qwen/DashScope、Anthropic、OpenAI、DeepSeek、Ollama。
- 读取模型档位和 key。

适合查：

- provider 切换逻辑。
- key 缺失时的错误。
- 新增 LLM provider 的入口。

## 5. 状态、配置与契约

### `nudge/state.py`

职责：

- 管理 SQLite schema 和迁移。
- 记录 action、habit、evaluation、chat history。
- 存储 HealthExport 的每日聚合和 workout 元数据。

适合查：

- `nudge log` / `check-in` 最终写到哪里。
- 本地状态目录如何影响数据库位置。
- review / daily sync 使用哪些表。

### `nudge/config.py`

职责：

- 读取 `config.toml`。
- 解析默认 Calendar / Reminders / family routing / state dir。
- 从本机外部密钥文件或环境变量读取 provider key。

注意：

- 长期密钥不能写入仓库。
- 本机密钥路径应保持在 `~/.config/nudge/` 下。

### `nudge/json_contract.py`

职责：

- 定义结构化 action request/response 的稳定 JSON 契约。
- 服务 `agent apply` 和 MCP wrapper。

适合查：

- 其他项目应该如何构造 request。
- `plan_driven`、`text_plan_confirmed`、`text_plan_ref` 等安全字段。

### `nudge/errors.py`

职责：

- 把 LLM、AppleScript、EventKit、配置等底层错误归类。
- 生成面向 CLI 用户的可操作错误信息。

## 6. Skill Engine

### `nudge/skills/`

职责：

- 验证 Skill YAML/JSON。
- 执行 JSONLogic 子集和 patch 白名单。
- 提供 dry-run 和内置 Skill 示例。

重点文件：

- `skills/schema.py`：Skill schema 校验。
- `skills/jsonlogic.py`：受限 JSONLogic 执行。
- `skills/patch.py`：安全 patch 应用。
- `skills/engine.py`：个性化和规则执行主流程。
- `skills/dryrun.py`：dry-run 输出。
- `skills/builtins/*.yaml`：内置 Skill 模板。

边界：

- Skill 不调用 LLM。
- Skill 不执行 shell。
- Skill 不访问网络。
- Skill 不直接写 Apple 应用。

## 7. Daemon、队列与恢复

### `nudge/commands/daemon.py`

职责：

- 管理本地 daemon 队列。
- 支持 enqueue、queue、status、run、recover、retry、health。
- 管理 launchd 和菜单栏 app 相关命令。

相关文件：

- `nudge/daemon_control_app.py`：daemon 控制 app 支持。
- `scripts/bootstrap_launchd.sh`：安装早晚 briefing、daily sync 和无头 daemon 的 launchd 任务。
- `docs/DAEMON_RUNBOOK.md`：恢复、人工回放和故障排查。

适合查：

- dead letter 如何查看和重试。
- launchd plist 如何安装、启动、停止。
- daemon 健康状态如何进入 briefing。

## 8. 健康、反馈和复盘

重点文件：

- `nudge/health.py`：Apple Health export 解析、聚合和导入。
- `nudge/feedback.py`：反馈标准化。
- `nudge/failures.py`：失败可见性和待处理项。
- `nudge/adapt.py`：weekly adapt 的 safe/unsafe 计划转换与 apply。
- `nudge/dogfood.py`：Nudge 自身使用情况周报。
- `nudge/sleep_reminders.py`：睡眠终止型 reminder 后续自动跳过逻辑。
- `nudge/family_routing.py`：家庭提醒路由。
- `nudge/docs_audit.py`：文档债审计规则，包括断链、断锚点、缺图片、重复标题、索引一致性、垃圾文件、旧计划/spec 和 TODO 历史标记。
- `nudge/runtime_log.py`：用户可修复 warning/error 的 JSONL 运行日志，按 `runtime_log.max_bytes` 轮转并保留 3 份历史文件。

适合查：

- 完成、跳过、部分完成、延期、阻塞如何归一化。
- 睡觉后同日晚间提醒为什么会自动作废。
- weekly review 如何决定下一轮调整。

## 9. 安装、验证与分发

### `scripts/bootstrap_mac.sh`

职责：

- 检查 `python3` 和 pip。
- 安装 `requirements.txt`。
- 调用 `scripts/install_cli.sh` 安装 `nudge` 命令。
- 引导配置本地状态目录。
- 可选运行 `nudge doctor`。

这是最接近“一键安装”的入口。

### `scripts/install_cli.sh`

职责：

- 安装或更新用户可直接调用的 `nudge` 命令。
- 处理 `~/.local/bin` 等 PATH 相关提示。

### `scripts/verify.sh`

职责：

- 运行完整 pytest 测试套件。
- 对核心 CLI 子命令做 smoke check。
- 是提交前优先使用的验证入口。

提交前优先运行：

```bash
scripts/verify.sh
```

## 10. 测试目录

### `tests/`

测试按功能域命名：

- `test_commands_*.py`：CLI 子命令行为。
- `test_apple_*.py`：Apple adapter 和 AppleScript/EventKit 边界。
- `test_skills_*.py`：Skill schema、engine、dry-run、patch、JSONLogic。
- `test_*_docs.py`：README、PRD、Architecture、Security、Runbook 等文档契约。
- `test_state.py`、`test_config.py`、`test_errors.py`、`test_llm.py`：核心模块。

新增功能时，优先找同名功能域测试补覆盖；涉及 CLI 输出时同时检查 JSON 输出和人类可读输出。

## 11. 常见修改入口

| 想改什么 | 先看哪里 |
|----------|----------|
| 新增 CLI 子命令 | `nudge/cli.py`、`nudge/commands/`、`scripts/verify.sh` |
| 调整自然语言解析 | `nudge/brain.py`、`tests/test_brain.py`、相关 `test_commands_*.py` |
| 新增 Apple action 类型 | `nudge/json_contract.py`、`nudge/apple/adapters.py`、对应 `nudge/apple/*.py`、`commands/agent.py` |
| 调整 MCP tool | `nudge/commands/mcp.py`、`docs/MCP_SECURITY.md`、`tests/test_commands_mcp.py` |
| 修改本地状态 schema | `nudge/state.py`、`tests/test_state.py`、备份/恢复相关测试 |
| 改 Skill Spec | `nudge/skills/`、`docs/SKILL_SPEC.md`、`tests/test_skills_*.py` |
| 改安装体验 | `scripts/bootstrap_mac.sh`、`scripts/install_cli.sh`、`README.zh-CN.md`、`README.md` |
| 改验证入口 | `scripts/verify.sh`、`tests/test_verify_script.py`、README 测试段落 |
