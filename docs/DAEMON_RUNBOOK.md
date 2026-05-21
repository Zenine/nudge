# Nudge daemon 人工回放操作手册

> 适用范围：`nudge daemon` 队列执行异常、Mac 睡眠/唤醒后遗留 `running`、`dead_letter`、LaunchAgent 未加载、早晚报出现「Nudge daemon 告警」或 `nudge daemon health --notify` 发出本机通知。

核心原则：**先诊断，再恢复；先确认幂等，再 retry**。不要为了清空告警直接重放所有命令。

---

## 1. 快速判断当前状态

先跑健康巡检：

```bash
nudge daemon health --json
```

如果怀疑是自启动问题，单独看 LaunchAgent：

```bash
nudge daemon launchd status --json
```

常见告警：

| code | 含义 | 第一动作 |
|------|------|----------|
| `DAEMON_HEALTH_UNAVAILABLE` | briefing 读取 daemon health 失败 | 直接运行 `nudge daemon health --json` 看原始错误 |
| `LAUNCHD_PLIST_MISSING` | `com.nudge.agent` plist 不存在 | `nudge daemon launchd install` |
| `LAUNCHD_NOT_LOADED` | plist 存在但没有加载 | `nudge daemon launchd start` |
| `STALE_RUNNING_COMMANDS` | 有命令长时间卡在 `running` | `nudge daemon recover --stale-minutes 30 --max-attempts 3` |
| `DEAD_LETTER_COMMANDS` | 有命令进入 `dead_letter` | 逐条检查后再 `retry` |

---

## 2. 恢复 stale running

如果 health 显示 `STALE_RUNNING_COMMANDS`，先执行自动恢复：

```bash
nudge daemon recover --stale-minutes 30 --max-attempts 3
```

规则：

- `attempts < max-attempts`：回到 `queued`，daemon 后续会重新执行。
- `attempts >= max-attempts`：进入 `dead_letter`，必须人工确认后再重放。

恢复后复查：

```bash
nudge daemon health --json
nudge daemon queue --status queued --json
```

---

## 3. 处理 dead_letter

先列出死信队列：

```bash
nudge daemon queue --status dead_letter --json
```

必要时用 SQLite 只读查看关键字段：

```bash
sqlite3 "$(python3 - <<'PY'
from nudge.state import DB_PATH
print(DB_PATH)
PY
)" "
SELECT request_id, status, attempts, last_error, last_exit_code, started_at, finished_at
FROM command_queue
WHERE status IN ('dead_letter', 'failed', 'running')
ORDER BY queue_created_at;
"
```

禁止动作：

- 不要批量 retry 全部 dead_letter。
- 不要在没确认 Apple 端是否已经写入的情况下重试写操作。
- 不要把 `last_error` 清掉当作修复。

逐条确认后再重放：

```bash
nudge daemon retry --request-id <request_id>
nudge daemon run --once --verbose
```

重放后检查：

```bash
nudge daemon health --json
nudge daemon queue --status failed --json
nudge daemon queue --status dead_letter --json
```

---

## 4. retry 前的幂等检查

不同 action 类型的重复风险不同。重放前先看 `payload` 和 Apple 端实际状态：

```bash
nudge daemon queue --status dead_letter --json
```

### Calendar

- 如果本地 action 已有 `Calendar external_id`，优先确认这个事件是否已经存在。
- 如果没有 `external_id`，按 summary / start / end / calendar 人工检查 Calendar，避免重复创建同一时间块。
- 如果 Apple 端已经存在，通常不要 retry；应把本地状态补齐或把该 request 保留为排障记录。

### Reminders

- 按 Reminders 标题和 due_date 检查是否已经在目标列表存在。
- 对睡后作废场景，后续睡眠提醒可能已经被标记完成；不要把它们重新创建成响铃提醒。
- 如果只是状态同步失败，优先使用 `nudge reminders sync-completed --date YYYY-MM-DD --apply`，不要直接 retry 创建请求。

### Notes

- 检查 Apple Notes 的 `Nudge` folder 是否已经有 Notes 重复标题。
- 对长计划或报告，确认正文不是重复写入；必要时保留一个版本，手动删除重复 note。

### Clock

- 检查 Clock 重复闹钟，尤其是同一时间同一 label。
- Clock 写入通常没有稳定 `external_id`；如果已经有对应闹钟，通常不要 retry。

---

## 5. LaunchAgent 手动启停

只管理 daemon，不影响 morning/evening briefing 定时任务：

```bash
nudge daemon launchd install
nudge daemon launchd status
nudge daemon launchd stop
nudge daemon launchd start
nudge daemon launchd restart
```

完全移除 daemon plist：

```bash
nudge daemon launchd uninstall
```

日志路径可从 status JSON 里读取，也可直接看：

```bash
tail -n 100 ~/Library/Logs/com.nudge.agent.out.log
tail -n 100 ~/Library/Logs/com.nudge.agent.err.log
```

---

## 6. 结束条件

一次人工回放结束前，至少确认：

```bash
nudge daemon health --json
nudge daemon queue --status running --json
nudge daemon queue --status dead_letter --json
```

期望状态：

- `health.status` 为 `ok`，或剩余 `warn` 有明确原因和后续动作。
- 没有 stale `running`。
- `dead_letter` 要么为空，要么每条都已记录为什么暂不 retry。
- Apple Calendar / Reminders / Notes / Clock 没有明显重复写入。

如果问题会反复出现，把现象补进 `docs/TODO.md` 的运行时可观测或告警策略条目，不靠记忆追踪。

---

## 7. 告警升级策略

`nudge daemon health --json` 会返回 `alert_policy`，用于说明每类告警如何触达、由谁处理、是否需要升级：

| code | touch | operator_action | escalation |
|------|-------|-----------------|------------|
| `LAUNCHD_PLIST_MISSING` | `briefing+notification` | `install_launchagent` | `same_day` |
| `LAUNCHD_NOT_LOADED` | `briefing+notification` | `start_launchagent` | `same_day` |
| `STALE_RUNNING_COMMANDS` | `briefing+notification` | `recover` | `same_day` |
| `DEAD_LETTER_COMMANDS` | `briefing+notification` | `manual_replay` | `manual_review_required` |

当前更强触达的边界：

- `DEAD_LETTER_COMMANDS` 不能自动升级为批量 retry；它的更强触达是持续出现在 briefing / 本机通知 / 图形化入口中，直到人工确认。
- `STALE_RUNNING_COMMANDS` 可以先自动 `recover`，但进入 `dead_letter` 后必须回到人工检查。
- LaunchAgent 问题可以通过 `nudge daemon launchd install/start/restart` 处理，不需要重写队列。

如果需要图形化入口：

```bash
nudge daemon app install --login-item
nudge daemon app open
```

这会生成 `~/Applications/Nudge Daemon Health.app`。这个 app 只调用本机 CLI：显示 `nudge daemon health`、打开 `com.nudge.agent` 日志、执行 `nudge daemon launchd restart`；不提供任意 shell 输入。
