# MCP `apply_apple_actions` 调用样例

[`apply_apple_actions.jsonl`](apply_apple_actions.jsonl) 是换行分隔 JSON-RPC 示例，可用于理解 MCP stdio 交互顺序：

1. `initialize`
2. `notifications/initialized`
3. `tools/list`
4. `tools/call` 调用 `apply_apple_actions`

样例里的 `dry_run` 为 `true`，用于预览结构化动作，不应写入 Apple 应用。

## 字段说明

- `request_id`：调用方生成的幂等键。真实写入时必须稳定保存，重试同一请求时使用同一个值，例如 `request-2026-07-05-demo-001`。
- `source`：可选调用方名称，便于日志和排查。
- `dry_run`：建议首次调用设为 `true`。
- `auth_token`：仅当本机启用 `[security.local_auth]` 时需要。公开示例只能写 `<LOCAL_AUTH_TOKEN_IF_ENABLED>`，不要提交真实 token。
- `actions`：结构化 Apple 动作数组；单次批量大小受服务端限制。

## 运行提示

真实 MCP client 通常负责启动：

```bash
bin/nudge mcp serve
```

如果要手动实验，可把 JSONL 按行写入该进程的 stdin，并读取 stdout 的 JSON-RPC 响应。不要把调试日志写入 stdout，因为 MCP stdio 的 stdout 保留给 JSON-RPC 消息。

## 真实写入注意事项

- 先 dry-run，并让用户确认人类可读计划。
- 真实写入只应在 macOS 上运行，且 Calendar / Reminders / Notes / Clock 权限已授权。
- 若启用本地 auth，真实 token 应来自环境变量或私有配置，不应进入仓库、日志、issue 或 PR。
- plan-driven 多动作请求应提供 `plan_driven: true`、`text_plan_confirmed: true` 和稳定的 `text_plan_ref`。
