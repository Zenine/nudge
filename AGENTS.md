# Nudge — AI Coding Assistant Context

## Quick Reference

一句话启动：
> Nudge 的源码在 /path/to/nudge-public。请读 QUICK_START.md，然后向我提问。没有问题就开始工作。

中断后恢复：
> 请读 checkpoint.md，继续上次未完成的工作。

---

## About This Project

- **Name**: Nudge
- **Description**: local-first macOS CLI runtime for turning plans into Apple Calendar, Reminders, Notes, and Clock actions.
- **GitHub**: https://github.com/Zenine/nudge
- **Primary language**: Python 3.12+
- **License**: AGPL-3.0-only

---

## Architecture

Nudge keeps the reusable runtime public and the user's personal state private. The public repository contains the CLI, Apple adapters, daemon, MCP wrapper, skills engine, bootstrap scripts, tests, and documentation; private plans, config files, SQLite databases, API keys, Health exports, and machine-specific paths must live outside this repository.

The CLI entrypoint is `bin/nudge` / `nudge.py`, with command modules under `nudge/commands/`. Apple integrations live under `nudge/apple/`, persistent state handling lives in `nudge/state.py`, and configuration resolution lives in `nudge/config.py`.

---

## Key Files

| 文件 | 说明 |
|------|------|
| `README.md` | 简体中文项目入口和运营化 README |
| `README.en.md` / `README.ja.md` / `README.zh-TW.md` | 多语言 README |
| `QUICK_START.md` | AI 编排入口，一句话启动项目维护工作 |
| `checkpoint.md` | Meridian 运营配套进度追踪文件 |
| `pyproject.toml` | Python package metadata 和 console script 配置 |
| `bin/nudge` | 本地 CLI wrapper |
| `nudge/cli.py` | Click CLI 根入口 |
| `nudge/commands/` | 子命令实现 |
| `nudge/apple/` | Calendar / Reminders / Notes / Clock 适配器 |
| `nudge/config.py` | 公开 runtime + private overlay 配置解析 |
| `nudge/state.py` | SQLite 状态访问 |
| `scripts/verify.sh` | 项目级完整验证入口 |
| `docs/` | VitePress 多语言文档站 |

---

## Rules

1. 提交前优先运行 `scripts/verify.sh`；失败时不得提交。
2. 新功能、bugfix、重构或行为变更前先写/更新测试，并先确认目标测试失败。
3. 不提交 `config.toml`、SQLite state、API key、OAuth token、Health export、个人计划或机器绝对私有路径。
4. 公开代码优先读取环境变量或配置项；本机私有路径只应存在于未提交的 private overlay。
5. Apple Reminders / Calendar / Notes / Clock 写入能力必须先支持 dry-run 或只读检查路径。
6. 修改文档时同步检查 `README*`、`docs/`、`llms.txt`、`TODO.md`、`CHANGELOG.md` 和 `checkpoint.md`。
7. 修改 Meridian 运营资产后运行 `python3 scripts/check-i18n-drift.py` 和 `cd docs && npm run docs:build`。
8. 不直接手写 SQL 修改 Nudge 状态；优先使用 `nudge` 命令。只读排查可以读 SQLite，写入前必须确认并备份。

---

## Workflow

1. 先做只读上下文检查：`git status --short --branch`、README、TODO、CHANGELOG、最近提交、验证入口。
2. 对运行时代码改动走测试驱动：写失败测试、实现、跑聚焦测试、跑 `scripts/verify.sh`。
3. 对运营文档改动保持四语言结构同步，并更新 `checkpoint.md`。
4. 收尾时明确说明完成项、未完成 TODO、验证命令和结果。
