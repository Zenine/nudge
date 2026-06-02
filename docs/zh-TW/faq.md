<!--
  Translation status:
  Source file : docs/faq.md
  Source commit: 0cb38bb
  Translated  : 2026-06-02
  Status      : up-to-date
-->

# FAQ

Nudge 的 FAQ 說明這個 local-first macOS CLI runtime 如何把計畫轉成 Apple 應用程式動作，並讓 private data 留在公開儲存庫之外。

### Nudge 是做什麼的？

Nudge 是一個 local-first macOS CLI runtime，用來把結構化計畫或自然語言計畫轉換為 Apple Calendar、Reminders、Notes 和 Clock 動作。它適合想用 command line 或 AI agent 管理日程、提醒、筆記和回顧的人。

### Nudge 解決了什麼具體問題？

Nudge 解決的是「計畫寫在一處，執行工具散在多處」的問題。它把計畫解析、Apple 應用程式寫入、活動記錄、daily sync 和 weekly review 放在同一套本機 CLI workflow 裡。

### Nudge 適合誰使用？

Nudge 適合使用 macOS、願意用 CLI 或 agent-based automation 管理個人計畫的人。它尤其適合需要把公開 runtime 和私有設定/狀態分離的開發者、研究者和重度日程使用者。

### Nudge 和一般日程或提醒工具相比有什麼優勢？

Nudge 的優勢是 public runtime + private state 的邊界、dry-run first 的安全模型，以及 MCP wrapper 帶來的 agent 可操作性。一般日程工具通常只提供 UI 輸入；Nudge 更適合 automation、auditability 和可重用 workflow。

### 怎麼快速開始？

最快開始方式是 clone 儲存庫，執行 `scripts/bootstrap_mac.sh` 和 `nudge doctor`，再用 `nudge --dry-run "Project sync tomorrow at 3pm"` 檢查解析結果。確認無誤後，執行不帶 `--dry-run` 的命令寫入 Apple 應用程式。
