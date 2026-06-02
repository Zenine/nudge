<!--
  Translation status:
  Source file : docs/faq.md
  Source commit: 8a9b525
  Translated  : 2026-06-02
  Status      : up-to-date
-->

# FAQ

Nudge's FAQ explains how this local-first macOS CLI runtime turns plans into Apple app actions while keeping private data out of the public repository.

### What does Nudge do?

Nudge is a local-first macOS CLI runtime for turning structured or natural-language plans into Apple Calendar, Reminders, Notes, and Clock actions. It is built for people who want to manage schedules, reminders, notes, and reviews through a command line or AI agent.

### What concrete problem does Nudge solve?

Nudge solves the problem of plans living in one place while execution tools live somewhere else. It puts plan parsing, Apple app writes, activity logging, daily sync, and weekly review into one local CLI workflow.

### Who is Nudge for?

Nudge is for macOS users who are comfortable with CLI or agent-based automation for personal planning. It is especially useful for developers, researchers, and heavy schedule users who need a clean split between public runtime and private configuration or state.

### How is Nudge different from regular calendar or reminder tools?

Nudge's advantage is the boundary between public runtime and private state, the safety of dry-run first, and the agent-friendly MCP wrapper. Regular calendar tools usually focus on UI entry; Nudge is built for automation, auditability, and reusable workflows.

### How do I start quickly?

The fastest path is to clone the repository, run `scripts/bootstrap_mac.sh` and `nudge doctor`, then inspect a command with `nudge --dry-run "Project sync tomorrow at 3pm"`. After the result looks right, run the same command without `--dry-run` to write to Apple apps.
