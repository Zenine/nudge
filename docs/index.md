---
layout: home
titleTemplate: ':title'
hero:
  name: "Nudge"
  text: "公开 runtime，私有状态"
  tagline: "把自然语言计划安全地转换为 Apple Calendar、Reminders、Notes 和 Clock 动作；先 dry-run，再写入。"
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
      src: /icons/terminal.svg
    title: macOS CLI runtime
    details: "面向本机自动化的 CLI，用统一入口驱动 Calendar、Reminders、Notes 和可选 Clock shortcut。"
  - icon:
      src: /icons/check-circle.svg
    title: Dry-run first
    details: "先检查解析结果，再执行真实写入，降低误写日程和提醒的风险。"
  - icon:
      src: /icons/lock.svg
    title: Private overlay
    details: "公开仓库只放 runtime；个人配置、SQLite 状态、密钥和 Health export 留在私有目录。"
  - icon:
      src: /icons/bot.svg
    title: MCP wrapper
    details: "通过 `nudge mcp serve` 为 agent 提供稳定、可审计的本地工具入口。"
  - icon:
      src: /icons/refresh.svg
    title: Daily sync
    details: "对齐 Reminders 完成状态、HealthExport 数据和文档维护信号。"
  - icon:
      src: /icons/wrench.svg
    title: Verified workflow
    details: "`scripts/verify.sh` 覆盖测试、compile、CLI smoke 和只读文档审计。"
---
