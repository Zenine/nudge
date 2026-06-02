---
layout: home
titleTemplate: ':title'
hero:
  name: "Nudge"
  text: "把计划变成当天真的会发生的事"
  tagline: "Nudge 已适配 Apple 生态：作为 AI 的 MCP 工具或日常 CLI，把一句自然语言计划落到日程、提醒、笔记和复盘里。"
  image:
    src: /hero.svg
    alt: Nudge
  actions:
    - theme: brand
      text: 快速开始
      link: /quick-start
    - theme: alt
      text: GitHub
      link: https://github.com/Zenine/nudge
features:
  - icon:
      src: /icons/target.svg
    title: 从想法到日程
    details: "把“明天下午三点项目同步”这类自然语言直接变成 Calendar 和 Reminders 里的具体安排。"
  - icon:
      src: /icons/check-circle.svg
    title: 写入前先确认
    details: "所有真实动作都可以先 dry-run，确认时间、标题、列表和目标应用，再写入 Apple 应用。"
  - icon:
      src: /icons/refresh.svg
    title: 每天自动对齐
    details: "把 Reminders 完成状态、HealthExport 信号和文档维护债同步成可追踪的本地状态。"
  - icon:
      src: /icons/bot.svg
    title: AI MCP + CLI 双入口
    details: "AI 助手可以通过 MCP 调用 Nudge；你也可以直接用 CLI 执行同一套计划、提醒、复盘和状态查询。"
  - icon:
      src: /icons/lightbulb.svg
    title: 从记录里调整节奏
    details: "weekly review 可以把一周执行记录转成安全的调整建议，而不是只生成一份漂亮总结。"
  - icon:
      src: /icons/lock.svg
    title: 公开工具，私有生活
    details: "公开仓库只放可复用 runtime；个人计划、密钥、SQLite 状态和健康数据留在 private overlay。"
---

## 适合这些场景

- 你在聊天或笔记里定了计划，但经常没有进入日历和提醒。
- 你想让 AI 助手帮忙安排事项，但不希望它直接乱写 Apple Reminders。
- 你希望同一个工具既能被 AI 作为 MCP 调用，也能在终端里作为 CLI 手动执行。
- 你需要每天同步完成状态，把“做了什么、漏了什么、该调整什么”留成本地记录。
- 你希望公开维护一套自动化 runtime，同时把个人数据、密钥和健康资料隔离在私有目录。

## 一句话理解

Nudge 不是另一个待办清单 UI。它是一条适配 Apple 生态的本地执行管道：AI 可通过 MCP 调用，人也可用 CLI 操作；计划会先展示给你确认，再写入 Apple 应用，并在后续同步和复盘里持续校正。
