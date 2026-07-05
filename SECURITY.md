# Security Policy

Nudge is local-first software. It stores state locally and can write to Apple apps on the user's machine when the user or a trusted local caller asks it to do so.

## Do not share secrets or private exports

Never commit, attach, or paste:

- API keys, OAuth tokens, passwords, or session credentials.
- Apple Health exports or raw health records.
- Local SQLite state or database snapshots.
- Personal `config.toml` files.
- Private calendar, reminder, note, or plan data.

Use synthetic examples when reporting bugs.

## Reporting a vulnerability

Prefer GitHub private vulnerability reporting when it is available for this repository. If private vulnerability reporting is not available, open a GitHub issue with minimal public detail and avoid exploit instructions, secrets, private data, or raw Health exports. A maintainer can then coordinate a safer follow-up channel in GitHub.

## Local-first threat model

Nudge's MCP and agent entrypoints are designed for a local-first workflow. By default, a process that can invoke the CLI, write to stdin, or connect through a configured local MCP client is treated as a trusted local caller. Dry-run, confirmation, schema validation, and batch limits reduce accidental writes and hidden payload changes, but they are not a full authentication boundary against malicious local processes. (Optional asynchronous `daemon enqueue` uses `request_id` as a queue idempotency key; direct `agent apply` / MCP writes are not deduplicated.)

For stricter local automation, Nudge supports optional token authentication for mutating agent/MCP entrypoints:

```toml
[security.local_auth]
enabled = true
token_env = "NUDGE_LOCAL_AUTH_TOKEN"
protect_agent_apply = true
protect_agent_status = true
protect_mcp_write_tools = true
```

When enabled, `agent apply`, `agent status`, MCP `apply_apple_actions`, and MCP `report_action_status` require an `auth_token` field matching the configured environment variable. Missing or invalid tokens are rejected before Apple writes or SQLite status updates. Read-only MCP tools such as `doctor_status` and `list_nudge_notes` do not require this token. The token is a local automation guard; it is not a substitute for OS isolation if an attacker can run arbitrary code as the same user.

If you run Nudge in a production, shared, remote, multi-user, or untrusted environment, isolate it yourself. Use separate OS users, filesystem permissions, process sandboxing, network restrictions, and secret management appropriate for that environment. Do not expose local write entrypoints to untrusted callers.
