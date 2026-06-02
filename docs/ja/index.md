---
layout: home
titleTemplate: ':title'
hero:
  name: "Nudge"
  text: "公開 runtime、私的な状態"
  tagline: "自然言語の計画を Apple Calendar、Reminders、Notes、Clock のアクションへ安全に変換します。先に dry-run し、その後書き込みます。"
  image:
    src: /hero.svg
    alt: Nudge
  actions:
    - theme: brand
      text: Quick Start
      link: /ja/quick-start
    - theme: alt
      text: GitHub
      link: https://github.com/Zenine/nudge
features:
  - icon:
      src: /icons/terminal.svg
    title: macOS CLI runtime
    details: "Calendar、Reminders、Notes、任意の Clock shortcut を一つの入口から扱う local CLI です。"
  - icon:
      src: /icons/check-circle.svg
    title: Dry-run first
    details: "実際の書き込み前に解析結果を確認し、予定や reminder の誤書き込みを見える化します。"
  - icon:
      src: /icons/lock.svg
    title: Private overlay
    details: "runtime は公開し、個人設定、SQLite 状態、secrets、Health export は private overlay に置きます。"
  - icon:
      src: /icons/bot.svg
    title: MCP wrapper
    details: "`nudge mcp serve` は agent に安定した監査可能なローカル tool endpoint を提供します。"
  - icon:
      src: /icons/refresh.svg
    title: Daily sync
    details: "Reminders の完了状態、HealthExport データ、文書メンテナンス信号を照合します。"
  - icon:
      src: /icons/wrench.svg
    title: Verified workflow
    details: "`scripts/verify.sh` はテスト、compile check、CLI smoke check、読み取り専用 docs audit を実行します。"
---
<!--
  Translation status:
  Source file : docs/index.md
  Source commit: 0cb38bb
  Translated  : 2026-06-02
  Status      : up-to-date
-->
