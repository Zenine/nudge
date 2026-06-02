---
layout: home
titleTemplate: ':title'
hero:
  name: "Nudge"
  text: "公開 runtime，私有狀態"
  tagline: "把自然語言計畫安全地轉換為 Apple Calendar、Reminders、Notes 和 Clock 動作；先 dry-run，再寫入。"
  image:
    src: /hero.svg
    alt: Nudge
  actions:
    - theme: brand
      text: 快速開始
      link: /zh-TW/quick-start
    - theme: alt
      text: GitHub
      link: https://github.com/Zenine/nudge
features:
  - icon:
      src: /icons/terminal.svg
    title: macOS CLI runtime
    details: "面向本機自動化的 CLI，用統一入口驅動 Calendar、Reminders、Notes 和可選 Clock shortcut。"
  - icon:
      src: /icons/check-circle.svg
    title: Dry-run first
    details: "先檢查解析結果，再執行真實寫入，降低誤寫日程和提醒的風險。"
  - icon:
      src: /icons/lock.svg
    title: Private overlay
    details: "公開儲存庫只放 runtime；個人設定、SQLite 狀態、secrets 和 Health export 留在私有目錄。"
  - icon:
      src: /icons/bot.svg
    title: MCP wrapper
    details: "透過 `nudge mcp serve` 為 agent 提供穩定、可審計的本機工具入口。"
  - icon:
      src: /icons/refresh.svg
    title: Daily sync
    details: "對齊 Reminders 完成狀態、HealthExport 資料和文件維護訊號。"
  - icon:
      src: /icons/wrench.svg
    title: Verified workflow
    details: "`scripts/verify.sh` 覆蓋測試、compile、CLI smoke 和唯讀文件審計。"
---
<!--
  Translation status:
  Source file : docs/index.md
  Source commit: 8a9b525
  Translated  : 2026-06-02
  Status      : up-to-date
-->
