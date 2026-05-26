# Nudge — Product & Interaction Design v2

> v2 日期：2026-04-25  
> 对齐文档：PRD v2（private control-plane 文档，未随 public runtime 导出）
> 当前设计重点：CLI 是当前 UI，先打磨 Dogfood 闭环，不马上设计完整 App。

See also: [Architecture](ARCHITECTURE.md) | [CLI](CLI.md) | [Skill Spec](SKILL_SPEC.md) | [TODO](../TODO.md)

---

## 0. v2 设计决策

Nudge v1 的 Design 文档过早进入 Bot 卡片、iOS App、Web Portal 和 Marketplace。v2 先回到当前真实产品：**Mac + iPhone 本地执行教练**。

### 设计原则

1. **CLI 是当前 UI。** 用户实际看到的是命令、输出、错误文案，以及 Calendar / Reminders / Notes / Clock 中生成的结果。
2. **document-confirmation first for plans。** 长期计划、周计划、Skill 或复盘调整要批量写入 Apple 前，先给出人类可读文本计划 / 变更说明并让用户确认；不能先写 Apple，再回补说明。服务端以 `plan_driven`、`text_plan_confirmed`、`text_plan_ref` 校验这个前置条件。
3. **dry-run first。** 文本确认后，真实写入前必须能预览结构化 action。
4. **权限问题要可修。** `nudge doctor` 是 onboarding 和排障体验的一部分。
5. **少打扰，但要推进。** Nudge 的语气像 coach，不像日志系统。
6. **不马上设计完整 App。** App/Bot 只保留边界原则，等 Phase 2/3 数据触发。

---

## 1. 当前 UI：CLI 就是产品界面

当前用户的主要界面不是 App，而是：

- Terminal 输出。
- 其他项目调用 `bin/nudge` 后的 stdout/stderr。
- Apple Calendar / Reminders / Notes / Clock 中生成的事件、任务、文档和提醒。
- `nudge doctor` 的诊断结果。
- `review weekly` 和 `briefing` 的文本报告。

### CLI 输出设计目标

| 目标 | 说明 |
|------|------|
| 可预期 | 同类命令输出结构稳定，便于人读和脚本解析 |
| 可确认 | 写入前显示将创建什么、写到哪里 |
| 可恢复 | 失败时告诉用户下一步做什么 |
| 可复制 | 示例能直接复制运行 |
| 不吓人 | 权限/LLM/JSON 错误不要输出内部堆栈给普通用户 |

---

## 2. Dogfood 核心体验

Phase 1.7 的体验主线：每天自然地用 Nudge 管计划。

```text
早上：briefing morning
白天：nudge "..." 创建或更新计划
事件后：check-in / log
周末：review weekly --adapt --dry-run
确认后：review weekly --adapt --apply 更新下周计划
```

### 关键时刻

| 时刻 | 用户期待 | 当前设计要求 |
|------|----------|--------------|
| 第一次使用 | 知道能不能跑通 | 先 `nudge doctor`，再 dry-run |
| 写入计划前 | 知道会写什么 | 显示 action、时间、Calendar/List |
| 写入成功后 | 相信已经同步 | 显示成功数和目标日历 |
| 写入失败时 | 知道怎么修 | 错误文案指向权限、配置或目标对象 |
| 执行后 | 快速反馈真实状态 | 默认问完成 / 部分 / 延期 / 跳过；原因可一句话输入 |
| 每周复盘 | 知道下一步怎么改 | `review weekly --adapt --dry-run` 输出可执行预览，`--apply` 确认后只执行 safe 项 |

---

## 2.1 执行载体分工

Nudge 不把所有任务都写成 Calendar event。界面设计要让不同原生 App 各司其职：

| 载体 | 适合放 | 避免放 |
|------|--------|--------|
| Calendar | 高层次时间块、每日目标、不可错过的关键安排 | 细碎 checklist、可随手完成的小任务 |
| Reminders | 细颗粒任务、可打勾步骤、可事后同步的完成信号 | 需要整段专注时间的深度工作 |
| Clock / 通知 | 必须触达的重要时间点 | 普通任务列表 |
| Mail / briefing | 摘要、复盘问题、计划说明 | 紧急触达 |
| Notes | 给人看的计划正文和拆解文档 | 完成状态追踪、Markdown 源码式展示 |
| Nudge SQLite | action 状态、原因、延期、复盘数据 | 用户日常查看计划的主界面 |

Calendar 事件过去不等于完成；Calendar 被移动或删除也不等于延期或取消。它们只能作为 Nudge 询问用户的信号。完成状态的权威来源是 Nudge 本地 action 状态。

Notes 的设计重点是“打开就能读”。不要把 Markdown 原文当作最终 UI；`note.create` 应把常见标题、列表、checkbox、强调、代码围栏和 Markdown 表格渲染成简单的 Apple Notes HTML。Notes 适合承载计划说明和上下文，真正要打勾、延期、统计的内容应进入 Reminders 或 Nudge SQLite。真实写入后要以手机 / Mac 里的展示结果为准：如果还能看到 `#`、`- [ ]`、三反引号或 `|---|` 这类 Markdown 控制符，就视为写入质量失败，需要更新同一条 note 或重新写入人类可读版本。

## 3. 命令交互规范

### 3.1 自然语言写入

```bash
nudge --dry-run "明天下午3点开会"
```

推荐输出结构：

```text
Parsing: 明天下午3点开会

Found 1 action(s):

  1. [CALENDAR] "开会"
     When: 2026-04-26 15:00 - 2026-04-26 16:00
     Calendar: Personal

(dry-run, nothing created)
```

真实写入：

```bash
nudge "明天下午3点开会"
```

输出必须包含：

- 解析出的 action 数量。
- 每个 action 的目标 Calendar / Reminder list。
- 成功/失败数量。
- 失败原因。

### 3.2 本机诊断

```bash
nudge doctor
```

`nudge doctor` 输出要保持三态：

```text
PASS  Config     config.toml loaded
PASS  LLM        provider=qwen, model=qwen-plus, API key found
PASS  Calendar   AppleScript readable; configured calendars found: Personal
WARN  Reminders  Reminders AppleScript not verified: timeout
      Fix: 先打开一次 Reminders；再到 系统设置 → 隐私与安全性 → 提醒事项...
```

设计原则：

- FAIL：核心路径不可用。
- WARN：不阻塞当前 Calendar/LLM 核心路径，但需要修。
- Fix：必须给可操作步骤。

### 3.3 Skill 命令

```bash
nudge skills list
nudge skills show strength-basics-12w
nudge skills validate path/to/skill.yaml
nudge skills validate strength-basics-12w
nudge skills apply path/to/skill.yaml --context context.json --json
nudge skills dry-run strength-basics-12w --context context.json --json
```

设计原则：

- `validate` 只检查，不产生副作用。
- `list/show` 只展示包内内置 Skill 样例，方便 dogfood 和脚本发现。
- `apply` 只执行确定性规则，不调用 LLM，不写 Apple 应用。
- `dry-run` 只生成候选 action 预览，不写 Calendar / Reminders。
- JSON 输出给脚本用，文本输出给人用；机器可读输出统一带 `schema_version = "nudge.cli.v1"`。

### 3.4 Check-in / log

当前已提供最小 check-in：

```bash
nudge log done
nudge log partial "晨跑只做了一半，明天继续"
nudge log skipped --match "晨跑" "太晚了"
nudge log parse "晨跑完成了，跑了 2 公里，体感 7 分"
```

也可以使用别名：

```bash
nudge check-in done
nudge check-in parse "今天没做力量训练，临时开会"
```

输出应直接告诉用户：

- 记录到了哪个 action。
- 状态是 done / skipped / partial。
- 是否影响本周 review。
- 如果使用 `parse`，展示解析出的 metrics；`--dry-run --json` 必须能让脚本预览而不写 SQLite。

后续反馈模型要支持更丰富的状态和原因，但仍保持一句话可完成：

| 字段 | 值 |
|------|----|
| status | done / partial / skipped / deferred / blocked |
| reason | too_hard / no_time / conflict / low_energy / forgot / unclear / not_important / waiting_on_other |
| next_action | keep / reduce / split / reschedule / cancel |
| note | 用户原话，保留上下文 |

交互原则：

- 事件结束后只问一个轻问题：“完成 / 部分 / 延期 / 跳过？”
- 晚报批量拉回今天没有反馈的 action，避免每个事件都打断用户。
- 周报只追问模式原因，例如“这周延期最多的是训练，主要是太难还是时间不合适？”
- Reminders 打勾可以自动作为 done 候选，但仍要写回 SQLite。
- Calendar 移动/删除只显示为待确认信号，不自动改成 done / skipped。

### 3.5 Dogfood weekly

Dogfood 周报是给作者自己的最小复盘界面：

```bash
nudge dogfood weekly
nudge dogfood weekly --note "本周主要验证真实使用闭环"
nudge dogfood weekly --save
nudge dogfood weekly --json
nudge dogfood weekly --export-json dogfood.json
```

设计原则：

- 只读：读取 SQLite 和 `nudge doctor`，不调用 LLM，不写 Apple Calendar / Reminders。
- 简短：输出使用次数、完成率、真实 Calendar 写入、Adapt 采纳、跳过/partial 原因和权限/错误状态。
- 可存档：`--save` 写入本地状态目录的 `dogfood/YYYY-WW.md`，方便连续 4 周复盘。
- 可分析：`--json` / `--export-json` 输出结构化周报，供后续 PRD 复盘或其他脚本读取。

---

## 4. 错误文案与权限引导

错误文案要把“发生了什么”和“下一步怎么做”分开。

### 模板

```text
ERROR: 无法读取 Reminders 列表：AppleScript timeout

可能原因：Reminders 权限弹窗未确认，或 Reminders 数据库暂时不可读。
下一步：
1. 打开 Reminders.app
2. 打开 系统设置 → 隐私与安全性 → 提醒事项
3. 允许当前终端/IDE/Python 访问 Reminders
4. 重新运行：nudge doctor
```

### 常见错误

| 错误 | 用户应该看到 |
|------|--------------|
| LLM key 缺失 | 设置 `DASHSCOPE_API_KEY` 或写入 secrets.yaml |
| Calendar 不存在 | 当前可见日历列表 + config.toml 中目标名称 |
| Reminders 权限 | Reminders 权限修复步骤 |
| LLM JSON 非法 | 说明模型返回格式不对，建议重试或切换模型 |
| 部分写入失败 | 明确成功数、失败项、非 0 返回码，并提醒不要整条重试 |
| Skill schema 错误 | path + message，例如 `metadata.title: required value is missing` |

---

## 5. Coach 语气

Nudge 不是冷冰冰的任务系统，也不是过度热情的聊天机器人。

### 语气标准

| 场景 | 语气 |
|------|------|
| briefing | 简短、有重点、像早上提醒你今天节奏的助理 |
| reminder | 轻推，不内疚羞辱 |
| check-in | 低摩擦，允许失败 |
| review | 诚实指出模式，但给下一步 |
| adapt | 推荐明确，先预览，保留用户确认，只自动执行 safe 项 |
| error | 冷静、具体、可修 |

briefing / review / adapt 的默认结尾应该是“一个具体下一步”，不是泛泛鼓励；允许指出跳过或未完成，但不能制造负罪感。

### 推荐表达

好：

```text
这周训练完成率 67%，主要卡在周三。建议下周把周三训练挪到周四早上，周三只保留 10 分钟拉伸。
```

不好：

```text
你又失败了，需要更自律。
```

好：

```text
今天只有一个重点：19:00 的训练。先完成这个，其他都可以降级。
```

不好：

```text
你今天有 12 个任务，请全部完成。
```

---

## 6. 未来 App / Bot 设计边界

v2 不马上设计完整 App，但保留未来原则。

### 跨设备同步设计边界

未来跨设备使用不要求手机、IM 或其他 App 直接连用户 Mac。用户感知上应该是：

```text
其他端发送指令
→ Cloud Relay 显示“已收到，等待设备执行”
→ Mac / iOS agent 在线后执行
→ 返回成功、失败或需要授权
```

交互要求：

- 如果设备离线，明确显示“等待 MacBook Pro 在线后写入”或“等待 iPhone 在线后执行”。
- 如果本机权限缺失，显示 `needs_permission`，引导用户回到对应设备处理授权。
- 如果云端已经排队但还没写入 Apple Apps，不能显示“已创建日历/提醒”。
- 如果 Mac 关机或 iOS 后台受限，要说明“已写入的 Apple 提醒会继续生效；新命令会等设备在线后执行”。
- 如果用户只登录 Apple ID / iCloud，要说明这只是同步，不等于授权 Nudge。
- 远程入口只能提交白名单命令，不提供“运行脚本”“执行 AppleScript”“读取文件”这类 UI。

### Bot 设计边界

Phase 2 如果启动 Bot，只做：

- briefing 推送。
- check-in / 反馈 inbox。
- 延期、太难、临时冲突等原因回收。
- 简单自然语言创建 action。
- 周报摘要和调整确认。
- 显示设备执行状态：queued / running / succeeded / failed / dead_letter / needs_permission。
- 本机设置入口应能展示 `nudge daemon health` 的核心结果：LaunchAgent 是否加载、队列是否堆积、是否存在 stale running / dead_letter，以及日志路径。
- `Nudge Daemon Health.app` 是当前最小图形化入口：点击后显示健康巡检结果，并提供打开日志、重启 daemon 两个操作。

不做：

- 复杂卡片系统。
- 多 Bot 平台同时适配。
- 完整 Skill Marketplace 浏览。
- 任意远程控制电脑。

### App 设计边界

Phase 3 如果启动 App，优先设计：

- Today：今天要做什么。
- Plan：当前计划和完成率。
- Review：本周模式和调整建议。
- Chat/Input：快速输入。
- Check-in：通知点开后一键反馈完成、延期、太难或跳过。
- Permission Center：解释 Calendar / Reminders / Notifications / App Intents 授权状态。

不优先设计：

- 创作者后台。
- 复杂社交功能。
- 支付和订阅页。
- 完整 Marketplace 首页。
- 伪装成 24 小时后台常驻 agent。

### Apple 生态入口

未来 App 应考虑：

- EventKit：原生日历/提醒写入。
- App Intents：让 Siri / Shortcuts 调用 Nudge action。
- UserNotifications / APNs：提醒和 check-in。

但这些都等 Phase 1.7 和 Phase 2 验证后再展开。

---

## 7. 设计检查清单

每次改用户可见行为，检查：

- 是否支持 dry-run first？
- 是否说明会写入哪个 Calendar / Reminder list？
- 失败时是否有可操作下一步？
- 是否能被其他项目脚本稳定调用？
- 是否符合 coach 语气？
- 是否更新 [CLI.md](CLI.md)？
- 是否更新测试？
