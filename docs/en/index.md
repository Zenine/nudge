---
layout: home
titleTemplate: ':title'
hero:
  name: "Nudge"
  text: "Public runtime, private state"
  tagline: "Turn natural-language plans into Apple Calendar, Reminders, Notes, and Clock actions safely: dry-run first, then write."
  image:
    src: /hero.svg
    alt: Nudge
  actions:
    - theme: brand
      text: Quick Start
      link: /en/quick-start
    - theme: alt
      text: GitHub
      link: https://github.com/Zenine/nudge
features:
  - icon:
      src: /icons/terminal.svg
    title: macOS CLI runtime
    details: "A local CLI for driving Calendar, Reminders, Notes, and the optional Clock shortcut through one entrypoint."
  - icon:
      src: /icons/check-circle.svg
    title: Dry-run first
    details: "Inspect the parse before real writes so schedule and reminder mistakes stay visible."
  - icon:
      src: /icons/lock.svg
    title: Private overlay
    details: "Keep runtime public while personal config, SQLite state, secrets, and Health exports stay private."
  - icon:
      src: /icons/bot.svg
    title: MCP wrapper
    details: "`nudge mcp serve` gives agents a stable and auditable local tool endpoint."
  - icon:
      src: /icons/refresh.svg
    title: Daily sync
    details: "Reconcile Reminders completions, HealthExport data, and documentation maintenance signals."
  - icon:
      src: /icons/wrench.svg
    title: Verified workflow
    details: "`scripts/verify.sh` covers tests, compile checks, CLI smoke checks, and read-only docs audit."
---
<!--
  Translation status:
  Source file : docs/index.md
  Source commit: 0cb38bb
  Translated  : 2026-06-02
  Status      : up-to-date
-->
