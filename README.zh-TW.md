<!--
  Translation status:
  Source file : README.md
  Source commit: 40b12c7
  Translated  : 2026-06-07
  Status      : up-to-date
-->

> **語言 / Language**: [简体中文](README.md) · [English](README.en.md) · [日本語](README.ja.md) · **繁體中文**

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg?style=flat-square)](LICENSE)
[![Stars](https://img.shields.io/github/stars/Zenine/nudge?style=flat-square&color=gold)](https://github.com/Zenine/nudge/stargazers)
[![Last Commit](https://img.shields.io/github/last-commit/Zenine/nudge?style=flat-square)](https://github.com/Zenine/nudge/commits/main)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](https://github.com/Zenine/nudge/pulls)
[![Docs](https://img.shields.io/badge/Docs-online-22d3ee?style=flat-square&logo=vitepress&logoColor=white)](https://zenine.github.io/nudge/)
[![Powered by Meridian](https://img.shields.io/badge/Powered%20by-Meridian-8b5cf6?style=flat-square)](https://github.com/lordmos/meridian)

<div align="center">
  <img src=".github/assets/hero.svg" alt="Nudge" width="120" />
</div>

# Nudge

Nudge 是一個 local-first 的 macOS CLI runtime，用來把結構化計畫或自然語言計畫轉換為 Apple Calendar、Reminders、Notes 和 Clock 動作。

這個公開儲存庫只包含可重用 runtime、CLI、Apple adapters、daemon、MCP wrapper 和安裝腳本。個人計畫、本機設定、私有狀態、API key、Health 匯出和使用者專屬文件都應留在 private overlay 中。

## Quick Start

> 完整文件 → [線上閱讀](https://zenine.github.io/nudge/zh-TW/quick-start)

**Step 1** — 取得專案：

```bash
git clone https://github.com/Zenine/nudge.git
cd nudge
```

**Step 2** — 安裝並檢查本機環境：

```bash
scripts/bootstrap_mac.sh
nudge doctor
```

**Step 3** — 先 dry-run，再寫入 Apple 應用程式：

```bash
nudge --dry-run "Project sync tomorrow at 3pm"
nudge "Project sync tomorrow at 3pm"
```

`scripts/bootstrap_mac.sh` 會建立專案內 `.venv`；使用者不需要手動管理 Python virtual environment。

## Features

- Local-first macOS CLI：支援 Calendar、Reminders、Notes 和可選的 Clock shortcut。
- Dry-run first：`nudge --dry-run "..."` 會在任何寫入前展示解析結果。
- Private overlay：公開 runtime 可以讀取私有設定和 SQLite 狀態，避免把個人資料放進公開儲存庫。
- MCP wrapper：`nudge mcp serve` 提供 agent 穩定入口。
- Daily sync：對齊 Reminders 完成狀態、HealthExport 資料和文件維護訊號。
- Review loop：把一週活動轉成安全的調整建議。
- `scripts/verify.sh` 覆蓋測試、compile checks、CLI smoke checks、i18n drift checks、VitePress docs build 和唯讀文件審計。

## Recommended Flow

1. `nudge doctor` 檢查設定、LLM key 和 Apple 權限。
2. `nudge --dry-run "..."` 在寫入 Apple 前檢查解析結果。
3. `nudge "..."` 寫入確認過的 Calendar / Reminders / Notes / Clock 動作。
4. `nudge log ...` 記錄實際發生的事。
5. `nudge daily sync --json` 對齊 Reminders、HealthExport 和文件審計訊號。
6. `nudge review weekly --adapt --dry-run` 產生週次回顧和調整建議。
7. `scripts/bootstrap_launchd.sh` 可自動化 morning brief、daily sync、evening brief 和 daemon。

## Using a Private Overlay

Nudge 可以執行公開 runtime，同時從另一個目錄讀取私有設定和 SQLite 狀態。個人計畫、database file、API key path、Health 匯出和機器專屬設定都應放在 private overlay。

```bash
export NUDGE_CONFIG=/path/to/private/config.toml
export NUDGE_STATE_DIR=/path/to/private/state

bin/nudge doctor
bin/nudge mcp serve
bin/nudge agent status --file /path/to/status.json
```

也可以為單次命令指定 private config：

```bash
bin/nudge --config /path/to/private/config.toml doctor
bin/nudge --config /path/to/private/config.toml --dry-run "Project sync tomorrow at 3pm"
```

如果 `NUDGE_CONFIG` 指向 private config file，相對的 `[state].dir` 會以該 config file 所在目錄為基準解析。明確的 `--config /path/to/config.toml` 優先於 `NUDGE_CONFIG`。

## Maintenance

```bash
nudge docs audit
nudge docs audit --json
scripts/bootstrap_launchd.sh status
```

`nudge docs audit` 是唯讀命令。`nudge daily sync --apply --json` 在發現文件錯誤或 warning 需要處理時，可以建立本機 maintenance action；它不會移動、刪除或重寫文件。

## 平台邊界

Nudge 是 macOS-first runtime。CLI 的 dry-run、Skill rules 驗證、文件審計和 JSON preview 可以在公開儲存庫中執行；真實 Apple Calendar / Reminders / Notes / Clock 寫入、`launchd` daemon 安裝和 graphical control app 只支援 macOS。非 macOS 環境預設用於閱讀文件、執行 tests 和預覽 JSON，不預設實作跨平台 Apple 寫入。

## Testing and Verification

提交變更前執行儲存庫驗證腳本：

```bash
scripts/verify.sh
```

該腳本會執行公開測試套件、Python compile checks、CLI smoke checks、i18n drift checks、VitePress 文件建置和唯讀文件審計。

開發時也可以執行聚焦檢查：

```bash
python3 -m pytest tests/ -q
bin/nudge docs audit --json
```

## Private Data

這些內容必須留在公開儲存庫之外：

- `config.toml`
- local SQLite state
- API keys and OAuth tokens
- personal plans and health documents
- Apple Health exports
- app-specific local database snapshots

Secrets 優先使用環境變數或 `config.toml [llm].secrets_path`。不要把 secrets、token、database 或個人機器絕對路徑提交到公開儲存庫。

## License

Nudge 使用 [AGPL-3.0-only](LICENSE) 授權。

---

<sub>Built with [Meridian](https://github.com/lordmos/meridian) · open-source ops toolkit for Agent projects</sub>
