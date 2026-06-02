<!--
  Translation status:
  Source file : docs/quick-start.md
  Source commit: 0cb38bb
  Translated  : 2026-06-02
  Status      : up-to-date
-->

# Quick Start

Nudge 是一個 local-first 的 macOS CLI runtime，用來把結構化計畫或自然語言計畫轉換為 Apple Calendar、Reminders、Notes 和 Clock 動作。

## 三步上手

### 1. 取得專案

```bash
git clone https://github.com/Zenine/nudge.git
cd nudge
```

### 2. 安裝並檢查環境

```bash
scripts/bootstrap_mac.sh
nudge doctor
```

`scripts/bootstrap_mac.sh` 會建立專案內 `.venv`，所以不需要手動管理 Python virtual environment。

### 3. 先 dry-run，再執行

```bash
nudge --dry-run "Project sync tomorrow at 3pm"
nudge "Project sync tomorrow at 3pm"
```

Dry-run 會展示解析結果；確認無誤後再執行不帶 `--dry-run` 的命令。

## 使用 Private Overlay

Nudge 的推薦邊界是「公開 runtime，私有狀態」。把個人計畫、本機設定、SQLite 狀態、API key、Health export 和機器專屬路徑放在 private overlay。

```bash
export NUDGE_CONFIG=/path/to/private/config.toml
export NUDGE_STATE_DIR=/path/to/private/state

bin/nudge doctor
bin/nudge mcp serve
```

單次命令也可以直接指定 config：

```bash
bin/nudge --config /path/to/private/config.toml doctor
```

## 你只需要做三件事

1. 先執行 `nudge doctor`，確認 Apple 權限和設定可用。
2. 對任何真實寫入先執行 `--dry-run`。
3. 提交程式碼變更前執行 `scripts/verify.sh`。

## 中斷後恢復

如果你讓 AI 助手維護這個儲存庫，中斷後告訴它：

```text
请读 checkpoint.md，继续上次未完成的工作。
```

## 深入了解

- [README](https://github.com/Zenine/nudge#readme)
- [FAQ](./faq.md)
- [GitHub](https://github.com/Zenine/nudge)
