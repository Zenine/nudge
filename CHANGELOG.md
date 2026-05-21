# Changelog

## Unreleased

### Added

- 新增 `tests/` 回归测试，覆盖默认 LLM 配置、默认密钥路径、bootstrap 初始化、verify 编译检查和 README quick start。
- 从 private control plane 吸收 public-safe 回归测试，覆盖 agent apply、MCP 工具列表、配置读取和 JSON schema contract。
- 新增本地维护文件：`TODO.md`。
- 新增 runtime JSONL 日志：`<state.dir>/logs/nudge-runtime.jsonl`。
- `requirements.txt` 增加 `pytest`，保证项目自带验证入口可以在新环境运行测试。

### Changed

- 默认 LLM provider 从 Anthropic 调整为 Qwen/DashScope，与安装脚本和示例配置保持一致。
- 默认 secrets 路径统一为部署用户私有配置目录：`~/.config/nudge/secrets.yaml`。
- `scripts/bootstrap_mac.sh` 在缺少 `config.toml` 时会先从 `config.example.toml` 初始化配置。
- `scripts/verify.sh` 增加 `python3 -m compileall -q nudge` 编译检查。
- README 快速开始改为当前公共导出目录 `nudge-public`，并补充本机默认密钥路径说明。
- README 扩展为完整使用文档，增加安装、配置、诊断修复、常用命令、Agent/MCP、daemon、开发验证和项目结构说明。
- README 补充 Qwen/DashScope、OpenAI、Anthropic、DeepSeek、Ollama 的配置示例和密钥来源说明。
- `nudge doctor` 的默认 LLM provider/model 与 runtime 默认配置保持一致。
- 默认 README 改为英文，并新增 `README.zh-CN.md` 作为中文文档。
- 将用户可见默认配置集中到 `nudge.config`，包括 Calendar、Reminders、Notes、Clock shortcut、LLM 默认模型和 secrets 路径。
- 删除本地开发过程 `LOG.md`，新增 runtime JSONL 日志记录 WARN/ERROR 以便用户排障。
- README / README.zh-CN 补充 Apple 默认目标、macOS 权限获取和 runtime log 排障说明。

### Fixed

- 修复设置 `NUDGE_SECRETS_PATH` 或 `EMAIL_SECRETS_PATH` 时 LLM secrets 路径解析缺少 `Path` import 的问题。
