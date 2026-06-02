---
layout: home
titleTemplate: ':title'
hero:
  name: "Nudge"
  text: "Turn plans into things that actually happen"
  tagline: "Nudge turns a natural-language plan into calendar events, reminders, notes, and reviews: preview first, then write, so ideas do not stay trapped in chat."
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
      src: /icons/target.svg
    title: From idea to schedule
    details: "Turn phrases like “project sync tomorrow at 3pm” into concrete Calendar and Reminders actions."
  - icon:
      src: /icons/check-circle.svg
    title: Confirm before writing
    details: "Dry-run every real action first, then confirm the time, title, list, and target Apple app before writing."
  - icon:
      src: /icons/refresh.svg
    title: Daily alignment
    details: "Sync Reminders completions, HealthExport signals, and documentation maintenance into local state you can review."
  - icon:
      src: /icons/bot.svg
    title: A local execution lane for agents
    details: "AI assistants can call Nudge through MCP to schedule, remind, review, and query local status."
  - icon:
      src: /icons/lightbulb.svg
    title: Adjust from real records
    details: "Weekly review turns actual activity into safe adjustment suggestions, not just a polished summary."
  - icon:
      src: /icons/lock.svg
    title: Public tool, private life
    details: "Keep reusable runtime public while plans, secrets, SQLite state, and health data stay in a private overlay."
---
<!--
  Translation status:
  Source file : docs/index.md
  Source commit: 9d535b3
  Translated  : 2026-06-02
  Status      : up-to-date
-->

## Best-fit scenarios

- Your plans start in chat or notes but never make it into calendar and reminders.
- You want an AI assistant to help schedule work without giving it unchecked write access to Apple Reminders.
- You need daily sync to preserve what was done, what slipped, and what should change.
- You want to maintain a public automation runtime while keeping personal data, secrets, and health records private.

## One-sentence model

Nudge is not another todo-list UI. It is a local execution pipeline: parse the plan, show it for confirmation, write to Apple apps, then keep correcting the loop through sync and review.
