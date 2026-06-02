# Quick Start

Nudge 是一个 local-first macOS CLI runtime，用来把结构化计划或自然语言计划转换为 Apple Calendar、Reminders、Notes 和 Clock 动作。

## 三步上手

### 1. 获取项目

```bash
git clone https://github.com/Zenine/nudge.git
cd nudge
```

### 2. 安装并检查环境

```bash
scripts/bootstrap_mac.sh
nudge doctor
```

`scripts/bootstrap_mac.sh` 会创建项目内 `.venv`，所以不需要手动管理 Python virtual environment。

### 3. 先 dry-run，再执行

```bash
nudge --dry-run "Project sync tomorrow at 3pm"
nudge "Project sync tomorrow at 3pm"
```

dry-run 会展示解析结果；确认无误后再运行不带 `--dry-run` 的命令。

## 使用 private overlay

Nudge 的推荐边界是“公开 runtime，私有状态”。把个人计划、本地配置、SQLite 状态、API key、Health export 和机器专属路径放在 private overlay。

```bash
export NUDGE_CONFIG=/path/to/private/config.toml
export NUDGE_STATE_DIR=/path/to/private/state

bin/nudge doctor
bin/nudge mcp serve
```

单次命令也可以直接指定配置：

```bash
bin/nudge --config /path/to/private/config.toml doctor
```

## 你只需要做三件事

1. 先运行 `nudge doctor`，确认 Apple 权限和配置可用。
2. 对任何真实写入先运行 `--dry-run`。
3. 提交代码变更前运行 `scripts/verify.sh`。

## 中断后恢复

如果你让 AI 助手维护这个仓库，中断后告诉它：

```text
请读 checkpoint.md，继续上次未完成的工作。
```

## 深入了解

- [README](https://github.com/Zenine/nudge#readme)
- [FAQ](./faq.md)
- [GitHub](https://github.com/Zenine/nudge)
