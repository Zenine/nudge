# Nudge 安装、配置与排障

本文档承接 README 中不适合放在入口页的安装、配置、LLM provider、诊断和运行日志细节。CLI 参数、JSON 契约和自动化示例见 [CLI](CLI.md)；daemon 恢复流程见 [Daemon Runbook](DAEMON_RUNBOOK.md)。

## 安装入口

首次在 macOS 上配置时，优先运行：

```bash
scripts/bootstrap_mac.sh
```

该脚本会：

- 检查 Python 版本；
- 创建项目内 `.venv`；
- 安装 `requirements.txt`；
- 在缺少本地配置时从 `config.example.toml` 初始化 `config.toml`；
- 安装 `nudge` 命令；
- 可选运行 `nudge doctor`。

也可以直接使用仓库内固定入口，不安装到 `PATH`：

```bash
bin/nudge --help
bin/nudge doctor
```

需要自动化早报、晚报、每日同步和 daemon 时，运行：

```bash
scripts/bootstrap_launchd.sh
scripts/bootstrap_launchd.sh status
scripts/bootstrap_launchd.sh uninstall
```

`scripts/bootstrap_launchd.sh` 会安装 morning briefing、daily sync、evening briefing 和 headless daemon。daily sync 运行 `nudge daily sync --apply --json`，可以创建本地文档维护 action，但不会移动、删除或重写文档。

## 基础配置

从示例配置创建本地配置：

```bash
cp config.example.toml config.toml
```

最小配置示例：

```toml
[general]
default_calendar = "Personal"
default_reminder_list = "Tasks"
locale = "zh-CN"

[state]
dir = "~/.local/share/nudge"

[llm]
provider = "qwen"
secrets_path = "~/.config/nudge/secrets.yaml"

[llm.models]
fast = "qwen-plus"
default = "qwen-plus"
strong = "qwen-plus"
```

`secrets_path` 应指向部署用户拥有的私有文件；也可以用 `NUDGE_SECRETS_PATH` 或 `EMAIL_SECRETS_PATH` 覆盖。不要把密钥写进仓库。

API key 解析顺序：

1. `config.toml [llm].api_key`
2. provider 专用环境变量
3. `secrets_path`
4. `LLM_API_KEY`

长期运行环境优先使用环境变量或 `secrets_path`，避免把 `api_key` 内联进配置。

## Apple 默认目标

默认 Apple 目标在 `config.toml` 中配置：

```toml
[general]
default_calendar = "Personal"
default_reminder_list = "Tasks"
default_notes_folder = "Nudge"

[apple.clock]
backend = "shortcuts"
shortcut_name = "Nudge Create Alarm"
```

请在目标 Mac 上创建匹配的 Calendar、Reminders list 和 Notes folder，或把这些值改成本机已有名称。创建 Clock 闹钟需要先在 Shortcuts 中创建名为 `Nudge Create Alarm` 的桥接快捷指令。

## 密钥文件

常用环境变量：

```bash
export DASHSCOPE_API_KEY="<your DashScope key>"
export OPENAI_API_KEY="<your OpenAI key>"
export ANTHROPIC_API_KEY="<your Anthropic key>"
export DEEPSEEK_API_KEY="<your DeepSeek key>"
```

`secrets.yaml` 使用顶层 key/value：

```yaml
dashscope_api_key: "<your DashScope key>"
qwen_api_key: "<your Qwen key>"
openai_api_key: "<your OpenAI key>"
anthropic_api_key: "<your Anthropic key>"
deepseek_api_key: "<your DeepSeek key>"
```

## LLM Provider

Nudge 从 `config.toml [llm]` 和 `[llm.models]` 读取模型设置。`provider` 选择 API 家族；`fast`、`default`、`strong` 分别用于轻量解析、常规对话和较重规划。

| provider | 推荐模型示例 | key 来源 |
|----------|--------------|----------|
| `qwen` / `dashscope` | `qwen-plus` | `DASHSCOPE_API_KEY`、`QWEN_API_KEY`、`dashscope_api_key`、`qwen_api_key` |
| `openai` | `gpt-4.1-mini` / `gpt-4.1` | `OPENAI_API_KEY`、`openai_api_key` |
| `anthropic` | `claude-haiku-4-5-20251001` / `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY`、`anthropic_api_key` |
| `deepseek` | `deepseek-chat` | `DEEPSEEK_API_KEY`、`deepseek_api_key` |
| `ollama` | `llama3.1` | 不需要 API key |

OpenAI-compatible gateway 可设置 `base_url`：

```toml
[llm]
provider = "openai"
base_url = "https://your-compatible-endpoint/v1"
```

Ollama 本地部署示例：

```bash
ollama serve
```

```toml
[llm]
provider = "ollama"
base_url = "http://localhost:11434/v1"

[llm.models]
fast = "llama3.1"
default = "llama3.1"
strong = "llama3.1"
```

## 诊断与修复

先运行诊断：

```bash
nudge doctor
nudge doctor --json
```

常见修复：

- `Config file not found`：运行 `cp config.example.toml config.toml`，或传 `--config <path>`。
- 缺少 API key：设置 provider 专用环境变量，或让 `config.toml [llm].secrets_path` 指向私有 `secrets.yaml`。
- Calendar 权限失败：打开 macOS 系统设置 -> 隐私与安全性 -> 日历，给运行 Nudge 的 shell host app 授权。macOS 单独区分访问级别时，需要 Full Calendar Access。
- Reminders 权限失败：打开系统设置 -> 隐私与安全性 -> 提醒事项，允许 Terminal、iTerm、Python 或运行 Nudge 的 app。
- Notes / Mail Automation 失败：打开系统设置 -> 隐私与安全性 -> 自动化，允许 shell host app 控制 Notes 或 Mail。
- 闹钟创建失败：确认 Shortcuts 中存在 `Nudge Create Alarm`，或在 `config.toml [apple.clock].shortcut_name` 中配置真实快捷指令名称。
- `nudge` 命令不存在：先试 `bin/nudge --help`；如果可用，把 `~/.local/bin` 加入 `PATH`。

## 运行日志

Nudge 会把可由用户修复的 WARN/ERROR 写入本地 JSONL 运行日志；`nudge daemon run` 启动时也会写入一条 INFO，记录当前代码 revision、工作树是否有本地改动、repo 路径和 daemon 参数，方便确认更新代码后实际运行的是哪一版：

```text
<state.dir>/logs/nudge-runtime.jsonl
```

默认状态目录下通常是：

```text
.nudge/logs/nudge-runtime.jsonl
```

日志记录诊断、可操作错误和 daemon 启动上下文，不保存 API key 或 provider 原始输出。写入前，如果当前日志超过 `runtime_log.max_bytes`，Nudge 会轮转日志；默认上限为 `1048576` bytes，并保留 `nudge-runtime.jsonl.1` 到 `.3`。

常用排障命令：

```bash
tail -n 50 .nudge/logs/nudge-runtime.jsonl
nudge doctor
nudge doctor --json
```
