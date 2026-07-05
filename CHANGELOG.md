# Changelog

本项目遵循“公开 runtime 与私人数据分离”的发布边界。公开变更记录只描述可复用代码、文档、测试和安全边界；不记录个人计划、私有配置、真实健康数据或本机专属路径。

## [0.5.1] - 2026-07-05

### Added

- 新增 Skills runtime 接线：`skills start/status/adapt` 可创建本地 plan instance、materialize week actions，并通过 SQLite 追踪进度。
- `trainer plan/status` 默认统一到内置 `strength-basics-12w` Skill runtime；旧 LLM 周计划保留为 `trainer plan --legacy-llm`。
- `nudge log --metric key=value` 支持记录数值/结构化指标，供 Skills adaptation 使用。
- 新增 MCP/agent 可选本地 token 认证：`[security.local_auth]` 可保护 `agent apply/status`、MCP `apply_apple_actions/report_action_status` 与 daemon 队列执行路径。
- 新增开源基础设施：`CONTRIBUTING.md`、`SECURITY.md`、`CODE_OF_CONDUCT.md`、GitHub Actions verify workflow、issue/PR 模板。
- 新增文档：命令参考、配置参考、架构与数据流文档、LLM provider 选择指南、非 macOS 评估指南、示例库、PyPI 发布 checklist。
- 新增示例：自然语言 dry-run、agent apply 请求、MCP JSON-RPC 调用、自定义 Skill YAML 模板。
- `nudge schedule` 支持按时长过滤空档、JSON 输出，以及显式 `--book --slot` 创建 Calendar event。
- 新增安全/回归测试：LLM JSON fence 解析、Health XML 安全与每日汇总校验、local auth、SQLite 初始化/迁移、AppleScript escape 契约、Reminder AppleScript fallback 同名安全。
- 新增离线 packaging 检查脚本，构建并检查 wheel/sdist 是否包含 Swift/YAML 包数据，且不包含 tests、私有配置、本地数据库或 Health export。

### Changed

- LLM JSON 解析支持 fenced JSON、前后说明文字，以及正文内首个 JSON object/list 提取。
- SQLite 状态层按 `DB_PATH` 缓存 schema 初始化，并为 actions 常用查询列添加索引。
- 睡眠 action 完成后的后续睡眠提醒 auto-skip 改为同一 SQLite 连接/事务内批量更新，避免逐条重新打开写连接。
- legacy `state.json` 迁移改为事务写入；提交成功后再归档，归档失败会记录 `archive_pending` 并在下次初始化重试。
- `config.example.toml` 补齐公开安全的脱敏示例，覆盖 `[family]`、`[user]`、`[calendars]`、`[reminders]` 与 `[security.local_auth]`。
- README 增加命令、配置、架构、示例入口，并区分当前源码安装与未来 PyPI/pipx 安装路径。
- Health 每日汇总解析会跳过负值、明显异常值与未知单位,并对同一导出内完全重复的 XML Record 按稳定 key 去重。

### Security

- Apple Health XML 解析改用 `defusedxml`，并增加 XML entry size 上限，降低实体膨胀/超大输入风险。
- agent dry-run confirmation secret 改为 `O_CREAT|O_EXCL` 原子创建，创建权限为 `0600`，并发创建输掉时读取已有 secret，不覆盖。
- AppleScript `escape` 的当前防注入契约已通过离线测试固定；Notes 正文路径确认先 HTML 化，不直接把原始多行正文交给 `escape`。

### Notes

- 真实 Apple 写入仍需要 macOS 和相应 App 权限；非 Mac 用户可使用文档审计、JSON/YAML 示例、纯逻辑测试和 dry-run/解析-only 路径评估项目。
- 本版本已完成 PyPI 发布准备文档与本地 packaging 验证入口，但仍没有发布到 PyPI/Homebrew；安装路径仍以源码仓库和本地 bootstrap 脚本为主。

## [0.5.0 and earlier]

- 公开仓库初始 runtime 基线：CLI、Apple adapters、SQLite state、daemon、MCP wrapper、Health/daily/review/trainer/skills 基础模块。
- 历史变更未完整记录；后续发布从 `0.5.1` 起维护本文件。
