# Changelog

## Unreleased - 2026-05-26

### Added

- 新增 `tests/` 回归测试，覆盖默认 LLM 配置、默认密钥路径、bootstrap 初始化、verify 编译检查和 README quick start。
- 从 private control plane 吸收 public-safe 回归测试，覆盖 agent apply、MCP 工具列表、配置读取和 JSON schema contract。
- 从 private README 吸收 public-safe 的 hero 图、架构图、读者入口和能力流程说明，并为 README 图片资产增加回归测试。
- 从 private docs 吸收并清理 public-safe 文档：CLI、Architecture、Design、MCP Security、Daemon Runbook、Apple Adapter Survey、Module Map、Skill Spec、Prompt Playbook，并在 README 中增加文档索引。
- 新增本地维护文件：`TODO.md`。
- 新增 runtime JSONL 日志：`<state.dir>/logs/nudge-runtime.jsonl`。
- 新增只读 `nudge docs audit`，用于报告文档断链、系统垃圾文件、陈旧计划/spec、TODO 历史标记和过长入口文档。
- `nudge daily sync` 新增 docs audit 结果；`--apply` 时如发现文档 error/warning，会创建一条本地文档维护 action。
- `requirements.txt` 增加 `pytest`，保证项目自带验证入口可以在新环境运行测试。

### Changed

- `Nudge Daemon Health.app` 打开时会运行期显示当前 macOS 版本、Mac 型号和 CPU 架构，避免图形化健康入口使用编译时写死的环境说明。
- 默认 LLM provider 从 Anthropic 调整为 Qwen/DashScope，与安装脚本和示例配置保持一致。
- 默认 secrets 路径统一为部署用户私有配置目录：`~/.config/nudge/secrets.yaml`。
- `scripts/bootstrap_mac.sh` 在缺少 `config.toml` 时会先从 `config.example.toml` 初始化配置。
- `scripts/bootstrap_mac.sh` 在 Apple Silicon Mac 上优先使用原生 Python，并拒绝 Rosetta / x86_64 Python 创建 `.venv`。
- `scripts/bootstrap_launchd.sh` 新增 `com.nudge.daily-sync`，默认每天 07:15 运行 `nudge daily sync --apply --json`。
- `scripts/verify.sh` 增加 `python3 -m compileall -q nudge` 编译检查。
- `scripts/verify.sh` 增加 docs audit smoke 和只读文档审计。
- Prompt 维护规则改为使用仓库根目录 `TODO.md`，并用测试防止 public 文档重新引用旧 `docs/TODO.md` 路径。
- README 快速开始改为当前公共导出目录 `nudge-public`，并补充本机默认密钥路径说明。
- README 扩展为完整使用文档，增加安装、配置、诊断修复、常用命令、Agent/MCP、daemon、开发验证和项目结构说明。
- README 补充 Qwen/DashScope、OpenAI、Anthropic、DeepSeek、Ollama 的配置示例和密钥来源说明。
- `nudge doctor` 的默认 LLM provider/model 与 runtime 默认配置保持一致。
- 默认 README 改为英文，并新增 `README.zh-CN.md` 作为中文文档。
- 将用户可见默认配置集中到 `nudge.config`，包括 Calendar、Reminders、Notes、Clock shortcut、LLM 默认模型和 secrets 路径。
- 删除本地开发过程 `LOG.md`，新增 runtime JSONL 日志记录 WARN/ERROR 以便用户排障。
- README / README.zh-CN 补充 Apple 默认目标、macOS 权限获取和 runtime log 排障说明。

### Fixed

- 修复 public 文档中指向未导出 PRD/Roadmap/Business/docs TODO 的内部链接，避免 docs audit 在 public 仓库中失败。
- 将 docs audit 当前 README 过长 suggestion 记录到 `TODO.md`，避免自动审计发现的问题只停留在命令输出中。
- 修复设置 `NUDGE_SECRETS_PATH` 或 `EMAIL_SECRETS_PATH` 时 LLM secrets 路径解析缺少 `Path` import 的问题。
