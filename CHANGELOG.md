# 变更日志

## 2026-06-07

- 修复顶层 `--config` 未传递到嵌套 group 子命令的问题，确保 `nudge --config /path/to/config.toml mcp serve` 与命令级 `nudge mcp serve --config /path/to/config.toml` 一致使用 private overlay 配置。
- 增加发布质量门：`config.example.toml` 改为公开安全的本地默认配置，MCP `doctor_status` 明确禁用 LLM ping 并拒绝路径参数，文档公开 smoke 命令可在临时 HOME/STATE 下运行。
- 增加发布前硬化测试：覆盖 CLI help 与四语言 reference 的新增命令一致性、公开文档/llms 边界审计、安装态导入 smoke 和 console script 元数据。
- 完成 P2 维护性和文档增强：`doctor` 新增 SQLite integrity、daemon 队列、磁盘空间和可选 LLM ping 检查；Apple Calendar/Reminders 统一 TSV parser；文档补齐 Skills 端到端示例、runtime log 截断策略和 macOS-first daemon 平台边界。
- 完成 P1 收口：新增 `nudge/runtime.py` 统一 runtime config/state 初始化，顶层 `--config` 不再写入 `NUDGE_CONFIG`，并通过 Click default map 下传给子命令。
- 补齐剩余 SQLite 写入命令的 `--config` state 重定向测试和实现，覆盖 `habits log`、`health import --apply`、`daemon enqueue/queue/status/recover/retry/health/run`、`dogfood weekly --save`、`review weekly --adapt --apply`。
- 补齐 routing/hygiene/sleep/feedback 工具函数测试，并增强 reminder 标题归一化和 feedback 枚举过滤。
- 补齐 `do` 命令核心测试，覆盖 action schema、datetime 校验、calendar/reminder/alarm/note dry-run JSON、失败项 JSON 和 family group rewrite。
- 补齐 `state.py` 队列与 action 状态测试，覆盖 action log/status、external_id、queue claim、stale recovery、dead_letter 和 retry；同时拒绝未知队列完成状态。
- 新增 `skills` engine 端到端测试，覆盖 builtin list/show/validate/apply/dry-run、自定义 skill import/delete，以及 personalization/adaptation 规则命中和未命中。
- 补齐 daemon 队列执行聚焦测试，覆盖 enqueue、run-once 成功、payload invalid、单条异常隔离，以及失败后的 queue 状态和 daemon run log；同时让 daemon 对合法 JSON 非对象 payload 走失败落库路径而不是在 claim 阶段崩溃。
- 使用子代理并行完成 P1 功能闭环首批切片：`do` 支持 note 自然语言链路，`trainer` 迁移到 Apple backend 并补 `--config` state 重定向，`schedule` 改为推荐 slot，`chat` 增加安全自动化入口，LLM 增加 retry/backoff 与任务级 `max_tokens`，MCP 增加探测响应并统一版本来源。
- 新增四语言命令参考页，覆盖常用 runtime 命令、安全边界、发布入口和站长验证 token 配置文件。
- 增加 Health import 边界测试，覆盖 HealthExport JSON、Apple Health ZIP XML、`--from/--to` 半开日期区间、workout `external_id` 和 route GPX ignored count，并同步 CLI reference 说明。
- 将 GitHub Pages build source 切换为 GitHub Actions workflow；公开 README 维持简体中文默认入口，英文入口继续保留为 `README.en.md`。
- 统一 `CHANGELOG.md` 为简体中文，并同步 README 翻译元数据，避免 i18n drift 检查把已同步翻译误报为 stale。

## 2026-06-06

- 完成 P0 runtime hardening：`scripts/verify.sh` 现在覆盖公开测试、compile、CLI smoke、i18n drift、VitePress build 和 docs audit。
- 修复 `review weekly --adapt --apply` 的 Calendar update/split 状态一致性风险，避免同一 `external_id` 产生重复 active action，并在 split 部分外部写入失败时写回 blocked feedback。
- 修复 daemon `NUDGE_DAEMON_SLEEP_MS` 非数字环境变量导致 `daemon run` 崩溃的问题。
- 增强 LLM JSON 解析和错误分类：支持带额外说明的 Markdown JSON fence，并避免把普通网络错误误分类为 invalid JSON。
- 修复 Notes / Reminders 正文 AppleScript 转义会吞掉换行的问题，同时保留 title / summary 等单行字段的旧行为。
- 新增 P0 回归测试，覆盖 adapt、Apple text escape、brain JSON parsing、daemon env parsing、LLM error classification 和 verify script coverage。
- 新增 runtime verification GitHub Actions workflow，在 PR、`main` push 和手动触发时运行项目级 `scripts/verify.sh`。
- 同步四语言 README 和 `llms-full.txt`，说明 `scripts/verify.sh` 现在包含 i18n drift 和 VitePress docs build。

## 2026-06-02

- 明确文档首页定位：Nudge 适配 Apple 生态，既可以作为 AI MCP 工具使用，也可以作为日常 CLI 使用。
- 重写 VitePress 首页，从面向用户的场景和价值主张切入，而不是以 runtime 架构开头。
- 改进 VitePress dev-native 主题对比度，覆盖文档页面、侧栏、菜单、搜索、终端风格代码块和导航。
- 新增 Nudge 的 Meridian dev-native 视觉识别，包括 SVG logo、OG 图片、双色 Lucide 图标资产和 VitePress 主题覆盖。
- 新增简体中文、英文、日文和繁体中文四语言 README。
- 新增 VitePress 文档站，包含四语言首页、快速开始和 FAQ 页面。
- 新增 GitHub Pages workflow、SEO metadata、`robots.txt`、`llms.txt` 和 `llms-full` 生成支持。
- 新增 AI 助手上下文文件：`CLAUDE.md`、`AGENTS.md`、Cursor rules、Windsurf rules 和 `QUICK_START.md`。
- 新增 `i18n/glossary.md`、`scripts/check-i18n-drift.py` 和 Meridian checkpoint 追踪。
- 更新 `nudge docs audit`，忽略 VitePress 依赖和构建目录，并补充覆盖 `docs/node_modules` 的回归测试。
