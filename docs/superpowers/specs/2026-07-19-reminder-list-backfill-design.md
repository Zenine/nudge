# Legacy Reminder 列表归属 Backfill 设计

- 日期：2026-07-19
- 状态：已实现并通过公开运行库完整验证
- 首版入口：`nudge reminders backfill-lists`
- 写入边界：只更新 Nudge SQLite 的 `actions.reminder_list`，不修改 Apple Reminders

## 1. 背景

Nudge 已为新建 reminder action 持久化实际目标列表，并让 `reminders sync-completed`、`daily sync`、legacy ID backfill 和睡眠派生完成尊重该列表归属。升级前创建的 action 没有 `reminder_list` 字段值，只能在多个配置列表中保守查找明确 Apple 记录。

这一兼容策略不会仅凭“某列表中不存在”把 action 推断为完成，但仍会扩大读取和匹配范围。首版需要一个独立、默认只读的工具：从用户明确配置的列表中为仍未闭环的 legacy reminder action 找到全局唯一归属，经统一确认和自动备份后，只把列表名回填到本地 SQLite。

## 2. 目标

1. 新增独立命令 `nudge reminders backfill-lists`，避免与会修改 Apple 数据的 `backfill-ids` 混合语义。
2. 默认只扫描 `[reminders].sync_lists`；重复传入 `--list` 时完全覆盖配置。
3. 只处理 `type=reminder`、`status in {created, pending}`、`reminder_list IS NULL` 且有合法 `scheduled_at` 的 action。
4. 同时识别到期日内未完成和已完成的 Apple Reminder。
5. 只接受精确到期分钟和受限标题规范化后的全局一对一唯一匹配。
6. 默认 dry-run；写入前统一确认并创建一致性 SQLite 备份。
7. 使用单个 SQLite 事务和候选快照防止并发部分写入。
8. 产生稳定的文本与 JSON 结果，明确区分候选、未匹配、歧义、非法数据和查询错误。

## 3. 非目标

- 不创建、完成、删除、移动或修改任何 Apple Reminder。
- 不补写 Apple Reminder 外部 ID；该能力继续由 `backfill-ids` 单独承担。
- 不处理 `done`、`partial`、`skipped`、`deferred`、`blocked`、`skipped_after_sleep` 等已闭环历史 action。
- 不自动扫描配置范围外的 Apple Reminders 列表。
- 不在 schema 初始化、安装升级、`doctor` 或 `daily sync` 中自动执行 backfill。
- 不使用 GPT、关键词、编辑距离或其它模糊规则推断列表。
- 不自动解决跨列表重复、同列表重复或多个本地 action 争用同一 Apple Reminder 的情况。

## 4. 已批准的产品决策

| 决策点 | 结论 |
|---|---|
| 写入目标 | 仅补本地 SQLite 的列表归属 |
| 列表范围 | `[reminders].sync_lists`，重复 `--list` 可显式覆盖 |
| action 范围 | 仅 `created` / `pending` 且 `reminder_list IS NULL` |
| 匹配规则 | 精确到期分钟 + 完全标题或受限尾部日期规范化 |
| 唯一性 | 所有候选列表中的全局一对一唯一匹配 |
| 确认方式 | `--apply` 后统一交互确认；自动化必须显式 `--yes` |
| 备份 | 每次真实写入前自动创建并校验 SQLite 备份 |
| CLI 入口 | 独立 `backfill-lists`，不扩展 `backfill-ids` |

## 5. CLI 契约

```bash
nudge reminders backfill-lists
nudge reminders backfill-lists --list Tasks --list Health
nudge reminders backfill-lists --from 2026-07-01 --to 2026-08-01 --limit 100 --json
nudge reminders backfill-lists --apply
nudge reminders backfill-lists --apply --yes --json
```

参数语义：

- `--list`：可重复；只要出现一次，就完全覆盖 `[reminders].sync_lists`。
- `--from`：可选，包含该本地日期的 00:00。
- `--to`：可选，不包含该本地日期的 00:00。
- `--limit`：默认 100，允许 1 至 500。action 按 `scheduled_at`、`id` 稳定排序后截取。
- `--apply`：请求真实写入；不传时始终为 dry-run。
- `--yes`：仅用于跳过 TTY 统一确认；没有 `--apply` 时拒绝该参数。
- `--json`：输出稳定 JSON。在非交互终端或使用 `--json --apply` 时必须同时传 `--yes`。
- `--config`：沿用 reminders 命令的配置与状态目录解析规则。

## 6. 候选选择与 Apple 只读查询

### 6.1 本地候选

候选选择只读取 SQLite，并要求：

- `type == "reminder"`；
- `status` 为 `created` 或 `pending`；
- `reminder_list` 为 SQL `NULL`，空字符串按非法数据处理，不视为可自动修复候选；
- `scheduled_at` 可解析为本地分钟；
- `summary` 为非空字符串；
- 落在 `--from` / `--to` 范围内。

缺少或非法的 `summary`、`scheduled_at` 或列表字段进入 `invalid`，不参与匹配。合法但已闭环的状态直接排除，不算 `invalid`，也不计入 `total_eligible`。

### 6.2 Apple 查询

EventKit helper 新增只读的“按到期日列出全部 Reminder”模式。它只接收一个已选列表和一个本地日期，返回该日到期的未完成与已完成 Reminder；不得读取备注正文，也不得调用 mutation helper。

返回给 Python 的最小字段为：

- `name`
- `list`
- `due_at`
- `due_time`
- `completed_at`（可以为空）

查询按 `(list, local_date)` 缓存，同一列表和日期只调用一次。任一所需列表/日期查询失败时，报告可保留已经计算出的只读诊断，但 `ok=false`、`apply_allowed=false`，禁止真实写入。

## 7. 匹配与全局唯一性

一个 Apple Reminder 只有同时满足以下条件才可匹配本地 action：

1. `due_at` 与 `scheduled_at` 精确到同一分钟；
2. 标题完全一致，或双方仅经现有 `normalize_reminder_title()` 去除标题尾部重复日期/时间后相等；
3. Apple Reminder 属于本次选定列表之一。

禁止大小写折叠、关键词、子串、编辑距离或 GPT 推断。

匹配必须在所有选定列表和当前批次 action 中执行全局一对一检查：

- 一个 action 命中零条 Apple Reminder：进入 `missing`；
- 一个 action 命中多条：进入 `ambiguous`；
- 同一 Apple Reminder 被多个 action 命中：所有相关 action 都进入 `ambiguous`；
- 只有 action 与 Apple Reminder 构成唯一一对一关系时才进入 `candidates`。

Apple 查询结果没有稳定 ID 时，以“列表 + 原始标题 + due_at + 结果序号”区分重复行；两个完全相同的 Reminder 仍视为两个匹配对象，因此不会被错误折叠为唯一候选。

每个候选至少包含：

- `id`
- `summary`
- `scheduled_at`
- `status`
- `current_reminder_list`：固定为 `null`
- `target_list`
- `match_type`：`exact_title` 或 `normalized_trailing_date`

结果不得包含 Reminder 备注或其它未纳入最小读取契约的 Apple 字段。

## 8. 确认、备份与事务

### 8.1 确认

默认 dry-run 只展示 `candidates`、`missing`、`ambiguous`、`invalid` 和 `errors`。`--apply` 会在同一进程内重新计算候选并展示最终汇总：

- TTY：使用默认否的统一确认；取消时零备份、零写入。
- 非 TTY：缺少 `--yes` 时以稳定错误退出。
- `--json --apply`：缺少 `--yes` 时以稳定错误退出，避免机器调用被交互提示阻塞。

没有唯一候选时，`--apply` 直接返回零更新结果，不创建备份、不启动事务。

### 8.2 备份

用户确认后、启动写事务前，复用 `nudge.commands.db.backup_database()` 创建 SQLite online backup，并执行既有完整性检查。备份失败时禁止启动写事务。

成功结果返回备份路径和完整性状态。路径只写到本机 CLI 输出，不进入公开日志或遥测。

### 8.3 原子写入

状态层新增批量 backfill 函数，输入为候选更新与本地快照。快照至少包括：

- `id`
- `type`
- `summary`
- `scheduled_at`
- `status`
- `reminder_list`

写入流程：

1. `BEGIN IMMEDIATE`；
2. 一次读取全部 action；
3. 校验 action 仍存在，且上述快照字段完全一致；
4. 校验 `reminder_list IS NULL` 且状态仍为 `created/pending`；
5. 对全部候选执行条件更新；
6. 任一更新行数不是 1，整批回滚；
7. 全部成功后提交。

事务只执行 `UPDATE actions SET reminder_list = ? ...`，不改变状态、完成时间、feedback、external ID 或 Apple 数据。

## 9. 输出与错误契约

JSON 顶层至少包含：

- `ok`
- `dry_run`
- `apply_allowed`
- `lists`
- `range`
- `limit`
- `total_eligible`
- `remaining`
- `candidates`
- `missing`
- `ambiguous`
- `invalid`
- `updated`
- `backup`
- `conflicts`
- `errors`

普通 `missing` 和 `ambiguous` 不令 `ok=false`，也不阻止其它唯一候选写入。Apple 查询、备份、并发或 SQLite 错误会令 `ok=false`；其中查询和备份错误发生在事务前，并发或 SQLite 错误触发整批回滚。

稳定错误码：

- `REMINDER_LIST_BACKFILL_CONFIG_INVALID`
- `REMINDER_LIST_BACKFILL_RANGE_INVALID`
- `REMINDER_LIST_BACKFILL_QUERY_FAILED`
- `REMINDER_LIST_BACKFILL_CONFIRMATION_INVALID`
- `REMINDER_LIST_BACKFILL_CONFIRMATION_REQUIRED`
- `REMINDER_LIST_BACKFILL_CANCELLED`
- `REMINDER_LIST_BACKFILL_BACKUP_FAILED`
- `REMINDER_LIST_BACKFILL_CONFLICT`
- `REMINDER_LIST_BACKFILL_WRITE_FAILED`

## 10. 组件边界

### `ReminderListBackfillSelector`

只读取 SQLite，过滤并稳定排序 legacy open reminder action。它不知道 Apple adapter，也不写状态。

### `ReminderListBackfillReader`

只读取选定 Apple Reminders 列表的最小字段，按列表和日期缓存。它不持有任何 mutation 能力。

### `ReminderListBackfillPlanner`

纯函数：接收本地 action 与 Apple 行，执行受限标题规范化、分钟匹配、跨列表及跨 action 一对一唯一性判断，返回结构化报告。

### `ReminderListBackfillApplier`

只负责快照复核和 SQLite 原子更新。它不调用 Apple adapter，不重新推断匹配。

### Click 命令层

负责参数解析、配置列表解析、确认、备份、错误码映射和文本/JSON 输出，不在命令函数内复制匹配规则。

## 11. 测试策略

实现必须测试先行，至少覆盖：

1. 只选择 `created/pending + reminder_list IS NULL`；
2. 日期范围、稳定排序、默认/最大 limit 和 remaining；
3. 配置列表与重复 `--list` 覆盖、去重和非法列表；
4. 完全标题匹配；
5. 仅尾部重复日期/时间规范化匹配；
6. 到期分钟不同不匹配；
7. 同列表重复、跨列表重复和多个 action 争用同一 Apple Reminder；
8. 未完成及已完成 Apple Reminder 的只读查询；
9. 任一 Apple 查询失败时 `apply_allowed=false`；
10. dry-run、取消和缺少 `--yes` 时 SQLite 与 Apple 均零写入；
11. 确认后备份成功再写入；备份失败零写入；
12. 快照冲突、条件更新失败和 SQLite 异常整批回滚；
13. Apple mutation 函数在所有路径均不被调用；
14. 文本与 JSON 不泄露 Reminder 备注；
15. CLI 帮助、命令文档、验证脚本、状态隔离和公开打包边界。

## 12. 文档、TODO 与交付

实施完成并验证后同步更新：

- `README.md`
- `docs/commands.md`
- `docs/configuration.md`
- `CHANGELOG.md`
- `TODO.md`
- 相关测试与 `scripts/verify.sh` CLI smoke

只有在完整 `scripts/verify.sh`、公开包内容检查和隐私扫描全部通过后，才从 `TODO.md` 移除 legacy reminder list backfill 事项。未来 IM / iOS 结构化反馈协议继续作为独立后续任务，不并入本实现。

## 13. 上线与回滚

首版不自动运行。推荐顺序：

1. 在真实配置上执行 dry-run；
2. 检查候选、歧义和未匹配清单；
3. 使用 `--apply` 统一确认；
4. 回读 SQLite 中本批 action 的 `reminder_list`；
5. 重新运行多列表 `sync-completed` dry-run，确认读取范围收敛。

若发现归属错误，先停止后续同步，再从命令自动生成的备份恢复；不要直接手写 SQL 批量纠正。
