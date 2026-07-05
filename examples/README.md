# Nudge 示例库

本目录提供面向公开仓库的安全示例，帮助新用户在不写入 Apple 应用的前提下理解 Nudge 的输入、Skill 扩展和 agent/MCP 调用方式。

## 安全边界

- 示例只使用占位符：如 `request-2026-07-05-demo-001`、`Personal`、`Tasks`、`<LOCAL_AUTH_TOKEN>`。
- 不要把真实 API key、OAuth token、家庭成员信息、健康数据、本机私有路径或机器专属配置写入示例文件。
- 建议先运行 `--dry-run`、`dry_run: true` 或解析-only 路径，确认输出符合预期后再考虑真实写入。
- 真实写入 Apple Calendar / Reminders / Notes / Clock 需要 macOS、本机 Apple 应用权限，以及用户确认的配置；非 Mac 用户仍可阅读示例、运行 JSON/YAML 解析检查和部分 dry-run/文档审计流程。

## 示例索引

- [`natural-language.md`](natural-language.md)：自然语言输入、裸文本入口和 dry-run 建议。
- [`skills/custom-skill-template.yaml`](skills/custom-skill-template.yaml)：符合 Skill Spec v0.1 的自定义 Skill YAML 模板。
- [`mcp/apply_apple_actions.jsonl`](mcp/apply_apple_actions.jsonl)：MCP JSON-RPC 初始化、列工具、dry-run 调用样例。
- [`mcp/apply_apple_actions.md`](mcp/apply_apple_actions.md)：MCP 调用说明、token 占位符和真实写入注意事项。
- [`agent/apply-request.json`](agent/apply-request.json)：`nudge agent apply --dry-run` 的结构化请求样例。

## 建议上手顺序

1. 先读自然语言示例，理解 `nudge --dry-run "..."` 与 `nudge "..."` 的区别。
2. 再读 agent/MCP 示例，理解结构化动作、`request_id` 幂等键和 `auth_token` 占位符。
3. 最后参考 Skill 模板，按 `nudge/skills/schema.py` 的字段约束写自己的 YAML，并先做解析/校验。
