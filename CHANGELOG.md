# Changelog

## 2026-06-06

- 完成 P0 runtime hardening：`scripts/verify.sh` 现在覆盖公开测试、compile、CLI smoke、i18n drift、VitePress build 和 docs audit。
- 修复 `review weekly --adapt --apply` 的 Calendar update/split 状态一致性风险，避免同一 `external_id` 产生重复 active action，并在 split 部分外部写入失败时写回 blocked feedback。
- 修复 daemon `NUDGE_DAEMON_SLEEP_MS` 非数字环境变量导致 `daemon run` 崩溃的问题。
- 增强 LLM JSON 解析和错误分类：支持带额外说明的 Markdown JSON fence，并避免把普通网络错误误分类为 invalid JSON。
- 修复 Notes / Reminders 正文 AppleScript 转义会吞掉换行的问题，同时保留 title / summary 等单行字段的旧行为。
- 新增 P0 回归测试，覆盖 adapt、Apple text escape、brain JSON parsing、daemon env parsing、LLM error classification 和 verify script coverage。
- 新增 runtime verification GitHub Actions workflow，在 PR、`main` push 和手动触发时运行项目级 `scripts/verify.sh`。
- 同步四语言 README 和 `llms-full.txt`，说明 `scripts/verify.sh` 现在包含 i18n drift 和 VitePress docs build。

## 2026-06-02

- Clarified the documentation homepage positioning: Nudge is adapted for the Apple ecosystem and can be used both as an AI MCP tool and as a CLI.
- Reworked the VitePress homepage around user-facing scenarios and value propositions instead of leading with runtime architecture.
- Improved VitePress dev-native theme contrast across document pages, sidebars, menus, search, terminal-style code blocks, and navigation.
- Added Meridian dev-native visual identity for Nudge, including SVG logo, OG image, two-tone Lucide icon assets, and VitePress theme overrides.
- Added multilingual README files for Simplified Chinese, English, Japanese, and Traditional Chinese.
- Added VitePress documentation site with four-language home, Quick Start, and FAQ pages.
- Added GitHub Pages workflow, SEO metadata, robots.txt, llms.txt, and llms-full generation support.
- Added AI assistant context files: `CLAUDE.md`, `AGENTS.md`, Cursor rules, Windsurf rules, and `QUICK_START.md`.
- Added `i18n/glossary.md`, `scripts/check-i18n-drift.py`, and Meridian checkpoint tracking.
- Updated `nudge docs audit` to ignore VitePress dependency/build directories, with regression coverage for `docs/node_modules`.
