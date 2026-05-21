# Nudge Prompt Playbook

本文档记录 Nudge 当前所有生产 prompt 的用途、输入、输出契约、模型档位和维护规则。目标是让后续修改 prompt 时有共同标准：知道每个 prompt 为什么存在、应该返回什么、哪里有测试保护，以及出错时怎么排查。

## 设计原则

1. **结构化任务优先约束输出**：会被代码解析的 prompt 必须明确“只返回 JSON”，并说明数组或对象结构。
2. **面向用户的文本默认中文输出**：briefing、review、adaptation、chat 等用户可见内容默认中文输出；除非用户显式要求英文。
3. **时间必须注入上下文**：涉及相对日期的 prompt 必须注入 `current_datetime` 或当前日期，避免模型自行猜测日期。
4. **模型档位匹配任务成本**：解析类轻任务用 `task="fast"`，计划生成和调整建议用 `task="strong"`，日常总结用 `task="default"`。
5. **失败要可诊断**：JSON 解析失败时要暴露清晰错误，不把坏输出当成空结果。
6. **不要让 prompt 承担系统权限或执行逻辑**：prompt 只生成结构化 action 或建议；写入 Apple Calendar / Reminders / Notes / Clock 等执行逻辑由命令层和 Apple 集成负责。

## Prompt 索引

| Prompt | 位置 | 模型档位 | 输出 | 用途 |
|---|---|---:|---|---|
| `PARSE_SYSTEM` | `nudge/brain.py` | `task="fast"` | JSON array | 自然语言 → calendar/reminder/alarm action |
| `BRIEFING_SYSTEM` | `nudge/brain.py` | `task="default"` | plain text | 生成每日早报 |
| `EVENING_SYSTEM` | `nudge/brain.py` | `task="default"` | plain text | 生成晚报 / 今日回顾 |
| `ADAPTATION_SYSTEM` | `nudge/brain.py` | `task="strong"` | JSON array | 根据执行数据生成调整建议 |
| `CHECK_IN_PARSE_SYSTEM` | `nudge/brain.py` | `task="fast"` | JSON object | 自然语言 check-in → status / note / metrics |
| `TRAINER_PLAN_SYSTEM` | `nudge/brain.py` | `task="strong"` | JSON array | 生成一周训练计划 |
| `TRAINER_LOG_SYSTEM` | `nudge/brain.py` | `task="fast"` | JSON object | 解析训练完成反馈 |
| `CHAT_SYSTEM` | `nudge/commands/chat.py` | `task="default"` | text + optional JSON block | 多轮对话与可选 action 创建 |
| `FAMILY_ROUTING_SYSTEM` | `nudge/brain.py` | `task="fast"` | JSON object | 家庭组 action 未命中关键词规则时，从已配置 family member keys 中选择 assignees，并返回 confidence / reason；非法成员或低置信度会被命令层丢弃并回退 default |

## 详细说明

### `PARSE_SYSTEM`

- **位置**：`nudge/brain.py`
- **调用方**：`parse_actions()`，由 `do` 命令和默认自然语言入口触发。
- **模型档位**：`task="fast"`
- **输入上下文**：`current_datetime`、family member aliases、用户原始文本。
- **输出契约**：只返回 JSON array。每个元素必须是 `calendar_event`、`reminder` 或 `alarm`。
- **关键规则**：
  - 相对时间必须基于注入的 `current_datetime` 解析。
  - 未提供结束时间的 calendar event 默认 1 小时。
  - 识别到家庭成员时，`person` 必须等于 alias 列表里的原文名称。
  - 识别到“家庭组 / 全家 / 家人 / 所有人”等家庭组目标时，`person` 必须等于 alias 列表里的对应家庭组别名；命令层现在按 `[family.routing.rules]` 关键词规则、LLM 兜底和 default fallback 决定接收人，不再简单默认每个成员。家庭组 calendar event 会按路由结果改写为对应成员在开始前 30 分钟和开始时各一条 reminder。
  - Reminder 的 `name` 必须是短标题，不包含日期或时间；排期放在 `due_date`，细节放在 `body`。
- **常见故障**：模型返回 markdown fence 或解释文字。当前 `_parse_json()` 可剥离简单 fence；失败后会追加 “只返回 JSON” 重试一次。
- **执行边界**：`alarm` 只需要 `HH:MM` 和 `label`；命令层会通过本机 `Nudge Create Alarm` Shortcuts bridge 调用 Clock。若 Shortcut 缺失，命令层返回 `CLOCK_SHORTCUT_MISSING`，不会伪装成成功。
- **测试入口**：`pytest tests/test_brain.py`

### `FAMILY_ROUTING_SYSTEM`

- **位置**：`nudge/brain.py`
- **调用方**：`suggest_family_routing()`；仅当家庭组 action 未命中关键词规则且 `[family.routing].llm_fallback=true` 时由命令层调用。
- **模型档位**：`task="fast"`
- **输入上下文**：待路由 action、可选上下文、已配置家庭成员 keys、家庭路由配置摘要。启用 `llm_fallback=true` 时，这些最小化后的家庭事项内容、成员 key/display_name/role 和路由规则摘要会发送给配置的 LLM provider；隐私优先可设 `llm_fallback=false`，未命中关键词时只走 default。
- **输出契约**：只返回 JSON object，包含 `assignees`、`confidence`、`reason`。`assignees` 只能使用已配置 member key；`confidence` 低于 `[family.routing].llm_confidence_threshold` 或返回非法成员时，命令层会丢弃 LLM 结果并回退 default。
- **关键规则**：prompt 只给接收人建议，不负责创建提醒、不写 Apple Reminders，也不承诺 Apple 原生 assignment；最终标题/备注显示由 `[family.routing.display]` 决定，calendar event 改写和 routing metadata 都由命令层处理。Apple 公开接口当前没有稳定的 Reminders assignee 字段，因此 prompt 不得声称已经使用 iOS 原生“分配提醒事项”。`--json --dry-run` / JSON 输出的 `actions[].routing` 还可能包含 `llm_error` / `llm_confidence`，用于调试 LLM 兜底失败原因和置信度。
- **测试入口**：`pytest tests/test_brain.py tests/test_commands_do.py tests/test_commands_chat.py`

### `BRIEFING_SYSTEM`

- **位置**：`nudge/brain.py`
- **调用方**：`generate_briefing()`，由 `briefing morning` 触发。
- **模型档位**：`task="default"`
- **输入上下文**：`current_datetime`、今日日历事件、今日到期提醒、未读邮件数、近期邮件。
- **输出契约**：中文 plain text，不使用 markdown，300 字以内。
- **关键规则**：
  - 按上午 / 下午 / 晚上组织。
  - 突出冲突或紧凑日程。
  - 最后只给一个具体下一步，不能用空泛鼓励替代行动。
  - 保持冷静 coach 语气，不制造负罪感，不用夸张鸡血话术。
- **常见故障**：遗漏日程冲突、输出太长。优先收紧规则，不要在代码层截断核心内容。

### `EVENING_SYSTEM`

- **位置**：`nudge/brain.py`
- **调用方**：`generate_evening_review()`，由 `briefing evening` 和 `review daily` 间接触发。
- **模型档位**：`task="default"`
- **输入上下文**：`current_datetime`、今日日历、已完成 actions、跳过/待完成 actions、habit streaks。
- **输出契约**：中文 plain text，不使用 markdown，300 字以内。
- **关键规则**：
  - 总结完成事实。
  - 对跳过项只陈述事实，不制造负罪感。
  - 给出一个明天可执行的具体建议，优先一个小动作，不给宽泛建议。

### `ADAPTATION_SYSTEM`

- **位置**：`nudge/brain.py`
- **调用方**：`suggest_adaptation()`，由 `review weekly --adapt` 显式触发。
- **模型档位**：`task="strong"`
- **输入上下文**：period、完成率指标、最近 actions、habit streaks。
- **输出契约**：只返回 JSON array，每个建议包含 `type`、`title`、`reason`、`suggestion`、`confidence`；当建议要修改已有 action 时应包含 `action_id`，可执行建议使用 `start` / `end` / `duration_minutes`。
- **关键规则**：
  - `type` 只能是 `move`、`reduce`、`split`、`delete`、`keep`、`increase`。
  - 建议必须基于执行数据，不得编造外部事实。
  - 语气诚实、冷静、非评判，像教练指出下一步，而不是批评用户。
  - 完成率高时建议小幅升级或保持节奏。
  - 完成率低时建议减量、换时间或简化习惯。
- **执行边界**：`review weekly --adapt --apply` 只会自动执行带 `external_id` 的 safe Calendar action；`split` 会保留原 Calendar UID 作为第一段，并创建后续分段事件；缺少 `external_id` 的老 action 会在 dry-run 中显示为 unsafe。
- **常见故障**：返回聊天式建议而非 JSON。当前实现会抛出“调整建议 JSON 解析失败”。
- **测试入口**：`pytest tests/test_brain.py::TestSuggestAdaptation -v`

### `TRAINER_PLAN_SYSTEM`

- **位置**：`nudge/brain.py`
- **调用方**：`generate_workout_plan()`，由 `trainer plan` 触发。
- **模型档位**：`task="strong"`
- **输入上下文**：当前日期、用户 fitness profile、本周 busy slots。
- **输出契约**：只返回 JSON array。每个 session 包含日期、时间、时长、训练类型、中文标题和 exercises。
- **关键规则**：
  - 只安排在用户偏好的日期和时间。
  - 避开已有日历事件。
  - 平衡肌群，并避开伤病风险动作。
- **常见故障**：日期漂移或无视 busy slots。修改时必须保留当前日期和 busy slots 注入。

### `CHECK_IN_PARSE_SYSTEM`

- **位置**：`nudge/brain.py`
- **调用方**：`parse_check_in_feedback()`，由 `nudge log parse` / `nudge check-in parse` 触发。
- **模型档位**：`task="fast"`
- **输入上下文**：用户原始自然语言完成反馈。
- **输出契约**：只返回 JSON object，包含 `status`、`note`、`reason`、`next_action`、`metrics`、`match`。
- **关键规则**：
  - `status` 只能是 `done`、`skipped`、`partial`、`deferred`、`blocked`。
  - `reason` 只能是 `too_hard`、`no_time`、`conflict`、`low_energy`、`forgot`、`unclear`、`not_important`、`waiting_on_other` 或空。
  - `next_action` 只能是 `keep`、`reduce`、`split`、`reschedule`、`cancel` 或空。
  - 只提取用户明确说出的数值 metrics，例如 `effort`、`minutes`、`distance_km`。
  - `match` 只在用户文本明确提到任务/习惯名称时填写，用于匹配本地 pending action。
- **执行边界**：命令层会再次校验 status、reason、next_action 和 metrics 类型；`--dry-run` 只展示解析结果和将更新的 action，不写 SQLite。
- **常见故障**：返回不支持的 status / reason / next_action 或 metrics 非对象。命令层会拒绝，并建议改用显式 `nudge log done/skipped/partial/deferred/blocked`。
- **测试入口**：`pytest tests/test_brain.py::TestParseCheckInFeedback tests/test_commands_log.py -v`

### `TRAINER_LOG_SYSTEM`

- **位置**：`nudge/brain.py`
- **调用方**：`parse_workout_log()`，由 `trainer log` 触发。
- **模型档位**：`task="fast"`
- **输入上下文**：当前计划 session、用户训练反馈文本。
- **输出契约**：只返回 JSON object，包含 `completed`、`effort`、`notes`、`metrics`。
- **关键规则**：
  - 如果用户提到距离、时间、重量、次数，要放进 `metrics`。
  - `completed` 必须是布尔值，不能返回“可能完成”。
- **常见故障**：effort 缺失或 metrics 非对象。优先在 prompt 中收紧 schema。

### `CHAT_SYSTEM`

- **位置**：`nudge/commands/chat.py`
- **调用方**：`chat` 命令。
- **模型档位**：`task="default"`
- **输入上下文**：当前时间、今日日历、今日提醒、近期 actions、habit streaks、最近对话历史。
- **输出契约**：默认中文对话；如果需要创建事项，在回复中包含 fenced `json` block，结构与 action JSON 一致。
- **关键规则**：
  - 日常回复要简洁温暖。
  - 创建事项必须让命令层继续走用户确认，不允许 prompt 假装已经写入。
  - JSON block 之外可以有人类可读说明。
- **测试入口**：`pytest tests/test_commands_chat.py -v`

## 维护流程

修改或新增 prompt 时按以下流程走：

1. **先写测试**：解析类 prompt 至少覆盖 JSON 解析失败、单对象转数组或必要 schema。文档索引由 `tests/test_prompt_playbook.py` 保护。
2. **更新本文档**：新增 prompt 常量时必须添加 `### \`PROMPT_NAME\`` 小节。
3. **标注模型档位**：明确使用 `task="fast"`、`task="default"` 或 `task="strong"`。
4. **说明输出契约**：写清楚 plain text / JSON array / JSON object / fenced JSON block。
5. **运行相关测试**：至少运行对应模块测试，例如 `pytest tests/test_brain.py`。
6. **运行完整测试**：提交前运行 `python3 -m pytest tests/ -q`，pre-commit 也会再执行完整测试。

## 测试策略

- Prompt 文档完整性：`pytest tests/test_prompt_playbook.py -v`
- Brain JSON 解析和 adaptation：`pytest tests/test_brain.py -v`
- Chat JSON block 提取：`pytest tests/test_commands_chat.py -v`
- CLI 端到端入口：`pytest tests/test_cli_installation.py tests/test_cli_docs.py -v`
- 完整套件：`python3 -m pytest tests/ -q`

测试重点不是断言 LLM 的具体自然语言，而是保护这些稳定契约：

- prompt 常量有文档条目；
- 代码能解析合法 JSON；
- 非法 JSON 会显式失败；
- 需要写入系统应用的命令仍然先预览/确认；
- 用户可见文字默认中文输出。

## 常见故障与处理

| 故障 | 可能原因 | 处理 |
|---|---|---|
| LLM 返回解释文字，JSON 解析失败 | prompt 没强调只返回 JSON | 在对应 prompt 的 Rules 中加强“只返回 JSON”，并加测试 |
| 相对日期解析错误 | 没注入 `current_datetime` 或当前日期 | 保留时间上下文，测试中传固定时间 |
| 早报输出太长 | briefing 规则不够收敛 | 明确字数上限和“不使用 markdown” |
| 调整建议太空泛 | 缺少 actions 指标或 reason/suggestion schema | 确保 metrics、actions、habit streaks 都进入 prompt |
| Chat 假装已经创建事件 | prompt 边界不清 | 强调只返回 action JSON，由命令层确认和执行 |
| 训练计划撞日程 | busy slots 格式不清或 prompt 被改弱 | 保留 busy slots 注入和“avoid conflicts”规则 |

## 示例：新增 prompt 检查清单

新增 prompt 时，至少完成：

- [ ] 在代码里新增清晰命名的 `*_SYSTEM` 常量。
- [ ] 在本文件 `Prompt 索引` 表中增加一行。
- [ ] 在本文件增加 `### \`PROMPT_NAME\`` 小节。
- [ ] 写明输入上下文、输出契约、模型档位。
- [ ] 增加或更新测试。
- [ ] 更新 `CHANGELOG.md`；如果对应 TODO 完成，也更新 `docs/TODO.md`。
