# Nudge Documentation

This directory contains public-safe project documentation for the reusable Nudge runtime.

## Start Here

- [CLI](CLI.md): command usage, JSON contracts, return codes, automation examples, and troubleshooting.
- [Architecture](ARCHITECTURE.md): local-first runtime architecture, data flow, Apple adapter boundaries, and MCP placement.
- [Design](DESIGN.md): product interaction principles and user-facing workflow constraints.
- [MCP Security](MCP_SECURITY.md): local MCP tool surface, capability boundaries, confirmation policy, and client guidance.

## Operations

- [Daemon Runbook](DAEMON_RUNBOOK.md): daemon health checks, stale jobs, retry flow, launchd operations, and recovery.
- [Apple Adapter Survey](APPLE_ADAPTER_SURVEY.md): Calendar, Reminders, Notes, Clock, EventKit, AppleScript, and Shortcuts tradeoffs.
- [Module Map](MODULE_MAP.md): source navigation guide for common changes.

## Customization

- [Skill Spec](SKILL_SPEC.md): deterministic skill format, rule limits, templates, and validation workflow.
- [Prompt Playbook](PROMPT_PLAYBOOK.md): prompt ownership, model tiers, and parsing guardrails.

Private plans, local config, state, secrets, Health exports, and user-specific documents are intentionally excluded from the public repository.
