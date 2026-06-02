---
layout: home
titleTemplate: ':title'
hero:
  name: "Nudge"
  text: "把計畫變成當天真的會發生的事"
  tagline: "Nudge 已適配 Apple 生態：可作為 AI 的 MCP 工具，也可作為日常 CLI，把自然語言計畫落到日程、提醒、筆記和回顧裡。"
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
      src: /icons/target.svg
    title: 從想法到日程
    details: "把「明天下午三點專案同步」這類自然語言直接變成 Calendar 和 Reminders 裡的具體安排。"
  - icon:
      src: /icons/check-circle.svg
    title: 寫入前先確認
    details: "所有真實動作都可以先 dry-run，確認時間、標題、列表和目標 Apple app，再寫入。"
  - icon:
      src: /icons/refresh.svg
    title: 每天自動對齊
    details: "把 Reminders 完成狀態、HealthExport signals 和文件維護債同步成可追蹤的本機狀態。"
  - icon:
      src: /icons/bot.svg
    title: AI MCP + CLI 雙入口
    details: "AI assistant 可以透過 MCP 呼叫 Nudge；你也可以直接用 CLI 執行同一套計畫、提醒、回顧和狀態查詢。"
  - icon:
      src: /icons/lightbulb.svg
    title: 從記錄裡調整節奏
    details: "weekly review 可以把一週執行記錄轉成安全的調整建議，而不是只產生一份漂亮摘要。"
  - icon:
      src: /icons/lock.svg
    title: 公開工具，私有生活
    details: "公開儲存庫只放可重用 runtime；個人計畫、secrets、SQLite 狀態和 health data 留在 private overlay。"
---
<!--
  Translation status:
  Source file : docs/index.md
  Source commit: 6f4a28f
  Translated  : 2026-06-02
  Status      : up-to-date
-->

## 適合這些場景

- 你在 chat 或 note 裡定了計畫，但經常沒有進入 calendar 和 reminder。
- 你想讓 AI assistant 幫忙安排事項，但不希望它直接亂寫 Apple Reminders。
- 你希望同一個工具既能被 AI 作為 MCP 呼叫，也能在 terminal 裡作為 CLI 手動執行。
- 你需要每天同步完成狀態，把「做了什麼、漏了什麼、該調整什麼」留成本機記錄。
- 你希望公開維護一套 automation runtime，同時把個人資料、secrets 和 health records 隔離在私有目錄。

## 一句話理解

Nudge 不是另一個 todo-list UI。它是一條適配 Apple 生態的本機執行 pipeline：AI 可透過 MCP 呼叫，人也可用 CLI 操作；計畫會先展示給你確認，再寫入 Apple apps，並在後續 sync 和 review 裡持續校正。
