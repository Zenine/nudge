# TODO

## 待用户确认

- [ ] GitHub Pages：推送到 `main` 后，在 GitHub Settings → Pages → Source 选择 **GitHub Actions**，再触发或等待 docs workflow。
- [ ] Search Console：等站点部署后，按 `checkpoint.md` 中任务 12 指引获取 Google / Bing verification token，再写入 `docs/.vitepress/verification-meta.mts`。
- [ ] Sitemap：Search Console / Bing Webmaster 验证后提交 `https://zenine.github.io/nudge/sitemap.xml`。

## 后续可选增强

- [ ] 若公开 README 需要以 English 作为默认入口，可在发布前把 `README.en.md` 内容切回 `README.md`，并保留简中为 `README.zh-CN.md`。
- [ ] 为 Nudge 文档站补更深的命令参考页，例如 `doctor`、`daily sync`、`review weekly`、`mcp serve`。

## P1：功能闭环

- [ ] 让 `note` 动作在 `do` 自然语言链路中完整闭环。
  - 范围：`brain.PARSE_SYSTEM` 明确支持 `note` 类型；`do.format_action` 能展示 note；`do --dry-run --json` 和真实执行都覆盖 Notes folder target。
  - 验收：新增测试覆盖 LLM 返回 `{"type": "note"}` 的 schema 校验、展示、JSON payload、dry-run 不写入、执行时调用 notes backend。

- [ ] 统一 state/config 解析，避免顶层 `--config` 依赖进程环境副作用。
  - 范围：评估并改造 `cli.py` 中写入 `os.environ["NUDGE_CONFIG"]` 的做法；优先通过 Click context 或显式 config 对象传递；同时保持现有 `NUDGE_CONFIG` 环境变量兼容。
  - 验收：新增测试覆盖顶层 `--config`、子命令 `--config`、原有环境变量、无配置文件四种场景；同一命令内 state path 和 agent confirmation secret path 指向同一 overlay。

- [ ] 为所有会写 SQLite 的子命令补齐 `--config` 后的 state 重定向。
  - 范围：重点检查 `trainer`、`chat`、`briefing/review` 间接路径、`dogfood`、`habits`、`health import --apply`、`daemon enqueue/run`；不要求一次改完所有 Apple 读写，只保证状态库不写错。
  - 验收：每个受影响命令至少有一个测试证明 private overlay 下写入 tmp state，而不是默认 `.nudge` 或 `~/.local/share/nudge`。

- [ ] 把 `trainer` 写 Calendar 的路径迁移到 Apple backend adapter。
  - 范围：`nudge/commands/trainer.py` 不再直接调用 `create_calendar_event`；使用 `resolve_apple_backends(config).calendar.create_event`，并保留 dry-run 行为。
  - 验收：新增测试覆盖 dry-run 不写入、真实写入使用配置中的 calendar backend、失败时输出结构化 Apple 错误。

- [ ] 把 `schedule` 从“列出所有空闲段”升级为按需求推荐 slot。
  - 范围：解析请求中的时长、日期范围、工作/个人偏好；输出推荐 slot；可选支持 `--json`，但不直接写 Calendar。
  - 验收：新增测试用假日历事件覆盖“找 2 小时深度工作时间”、最小时长过滤、跨天/当天过滤、无可用 slot。

- [ ] 为 `chat` 增加安全自动化入口。
  - 范围：支持 `--config`、`--dry-run`、可选 `--json` 或至少复用 `do`/`agent` 的确认语义；避免 chat 中检测到 action 后只能走交互式真实写入。
  - 验收：新增测试覆盖 chat action detection 后 dry-run 不写 Apple、不写 SQLite；真实写入仍需确认或确认 token。

- [ ] 为 LLM provider 增加统一 retry/backoff 和可配置 `max_tokens`。
  - 范围：`nudge/llm.py` 对 OpenAI-compatible、Anthropic、Ollama 的瞬时网络错误和 5xx 做有限重试；`max_tokens` 从 `[llm]` 或 `[llm.tasks]` 配置读取，保留默认值。
  - 验收：新增测试用 fake provider/client 覆盖 transient error 重试、鉴权错误不重试、任务级 max_tokens 覆盖默认值。

- [ ] 为 MCP server 补齐常见 client 探测方法的稳定响应。
  - 范围：`nudge/commands/mcp.py` 对 `ping` 给出标准成功响应；对未实现的 `prompts/list`、`resources/list` 等返回稳定 JSON-RPC error，避免客户端噪声。
  - 验收：新增 MCP stdio 测试覆盖 initialize、ping、tools/list、未知方法、prompts/resources 探测。

- [ ] 统一 MCP/agent/server 版本来源。
  - 范围：移除 `mcp.py`、`agent.py` 中硬编码 `0.5.1`；从 package metadata 或单一常量读取，确保与 `pyproject.toml` 不漂移。
  - 验收：新增测试断言 MCP `serverInfo.version` 和 agent payload 版本来源一致。

## P1：测试覆盖补全

- [ ] 增加 `do` 命令核心单元测试。
  - 范围：schema 校验、datetime 校验、calendar/reminder/alarm/note dry-run JSON、失败项 JSON、family group rewrite。
  - 验收：不调用真实 Apple 应用，全部使用 fake backend。

- [ ] 增加 `state.py` 队列与 action 状态测试。
  - 范围：action log/status 更新、external_id 更新、queue claim、stale recovery、dead_letter、retry。
  - 验收：使用 tmp SQLite，测试不依赖真实 private overlay。

- [ ] 增加 `daemon` 队列执行测试。
  - 范围：enqueue、run-once 成功、payload invalid、单条异常隔离、失败后 queue 状态和 daemon runtime log。
  - 验收：fake `apply_agent_request` / `apply_action_status`，不写 Apple。

- [ ] 增加 `health` 导入边界测试。
  - 范围：JSON export、ZIP XML export、`date_from/date_to` 语义、workout external_id、route GPX ignored count。
  - 验收：小型 fixture 覆盖半开/闭区间预期，并同步更新 CLI 文档说明。

- [ ] 增加 `skills` engine 端到端测试。
  - 范围：builtin list/show/validate/apply/dry-run、自定义 skill import/delete、personalization/adaptation rule 命中与未命中。
  - 验收：使用 tmp custom skill dir，测试不污染 `~/.nudge/skills`。

- [ ] 增加 routing/hygiene/sleep/feedback 工具函数测试。
  - 范围：`family_routing.py`、`action_hygiene.py`、`sleep_reminders.py`、`feedback.py` 的边界和错误输入。
  - 验收：覆盖 `all`、未知成员、低置信度 fallback、睡眠终止提醒 cascade、标题归一化。

## P2：维护性 / 文档 / 平台增强

- [ ] 增强 `doctor` 的本地健康检查。
  - 范围：增加 SQLite `PRAGMA integrity_check`、daemon dead_letter/stale running 摘要、磁盘剩余空间、LLM 可选 ping。
  - 验收：新增测试覆盖 JSON payload 中的新增 check，默认不做昂贵或写入操作。

- [ ] 为 runtime 命令补文档参考页。
  - 范围：`doctor`、`daily sync`、`review weekly`、`mcp serve`、`agent apply/status`、`daemon`、`skills`、`health import`；保持四语言结构同步。
  - 验收：运行 `python3 scripts/check-i18n-drift.py`、`cd docs && npm run docs:build`、`scripts/verify.sh`。

- [ ] 为 Skills 生态补端到端示例。
  - 范围：新增 README/docs 示例，说明 builtin skill、custom skill、context JSON、dry-run、apply/personalize/adapt 的完整流程。
  - 验收：示例命令可在公开仓 dry-run，不需要私有配置或真实 Apple 写入。

- [ ] 明确 Health import 的日期区间语义。
  - 范围：确认 `date_to` 是半开区间还是包含当天；更新 CLI help/docs；必要时调整实现。
  - 验收：实现、测试、文档三者一致。

- [ ] 统一 Apple TSV 行解析工具。
  - 范围：抽出 Calendar/Reminders 共用 TSV parser，替代 `_parse_event_rows` 和 `_parse_due_today_rows` 的重复逻辑。
  - 验收：现有 Calendar/Reminders 解析测试通过，并新增 malformed row 覆盖。

- [ ] 梳理 runtime log 截断策略。
  - 范围：在 docs 中说明 `runtime_log.py` 对 payload/error 的截断阈值；必要时让阈值可配置。
  - 验收：日志不会泄露密钥，用户能从文档知道为什么长 payload 被截断。

- [ ] 评估非 macOS daemon 入口。
  - 范围：当前 Nudge 是 macOS-first，launchd 是主路径；只评估是否需要 Linux systemd/cron 文档或轻量脚本，不默认实现跨平台 Apple 写入能力。
  - 验收：若决定支持，新增文档和只读/队列处理路径；若决定不支持，在 README/docs 明确 macOS-first 边界。
