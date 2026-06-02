# FAQ

Nudge 的 FAQ 解释这个 local-first macOS CLI runtime 如何把计划转成 Apple 应用动作，并说明它如何保护私有数据。

### Nudge 是做什么的？

Nudge 是一个 local-first macOS CLI runtime，用来把结构化计划或自然语言计划转换为 Apple Calendar、Reminders、Notes 和 Clock 动作。它面向希望用命令行和 AI agent 管理日程、提醒、记录和复盘的人。

### Nudge 解决了什么具体问题？

Nudge 解决的是“计划写在一处，执行工具散在多处”的问题。它把计划解析、Apple 应用写入、执行记录、daily sync 和 weekly review 放在同一套本地 CLI 流程里。

### Nudge 适合谁用？

Nudge 适合使用 macOS、愿意用 CLI 或 agent 自动化个人计划的人。它尤其适合需要把公开 runtime 和私有配置/状态分离的开发者、研究者和重度日程使用者。

### Nudge 和普通日程/提醒工具相比有什么优势？

Nudge 的优势是 public runtime + private state 的边界、dry-run first 的安全模型，以及 MCP wrapper 带来的 agent 可操作性。普通日程工具通常只提供 UI 输入；Nudge 更适合自动化、审计和可复用工作流。

### 怎么快速开始？

最快开始方式是克隆仓库，运行 `scripts/bootstrap_mac.sh` 和 `nudge doctor`，再用 `nudge --dry-run "Project sync tomorrow at 3pm"` 检查解析结果。确认无误后，运行不带 `--dry-run` 的命令写入 Apple 应用。
