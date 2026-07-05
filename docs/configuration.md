# 配置参考

Nudge 默认读取仓库根目录的 `config.toml`。首次使用可复制公开安全的示例文件：

```bash
cp config.example.toml config.toml
nudge doctor
```

`config.toml` 是本机文件，通常不应提交。公开仓库文档和示例只使用占位符；API key、OAuth token、真实家庭成员姓名、真实日历/提醒事项列表名、个人健康资料和本机私有路径都应留在本机私有配置或环境变量中。

## 哪些配置会影响真实 Apple 写入

以下配置会改变 `nudge`、`nudge do`、`nudge agent apply`、`nudge skills start`、`nudge skills adapt --apply`、`nudge trainer plan --yes` 等真实写入命令的落点或后端：

- `[general].default_calendar`：未指定目标日历时，日历事件写入的默认日历。
- `[general].default_reminder_list`：未指定目标列表时，提醒事项写入的默认列表。
- `[apple.calendar]`、`[apple.reminders]`、`[apple.notes]`、`[apple.clock]`：决定 Calendar / Reminders / Notes / Clock 使用的本机后端。
- `[family]` 成员里的 `calendar`、`reminder_list`：家庭路由展开后，每个成员的事件或提醒写入目标。
- `[family.routing]`：决定“全家/家庭组”等消息如何拆分到成员；配置错误可能导致写给错误成员或被安全检查拦截。
- `[calendars]`：影响 schedule、briefing、trainer 等读取忙闲上下文时查询哪些日历；间接影响后续写入建议。
- `[reminders]`：为习惯、训练或其它场景保留的提醒列表映射；已被使用的命令会把它作为目标列表候选。

安全建议：先运行 `nudge --dry-run "..."`、`nudge agent apply --dry-run` 或不带 `--apply` 的预览命令，确认 JSON 和目标列表后再真实写入。

## `[general]`

通用默认值。

```toml
[general]
default_calendar = "Personal"
default_reminder_list = "Tasks"
locale = "zh-CN"
```

- `default_calendar`：默认 Apple Calendar 名称。必须与本机 Calendar 里的日历名一致。
- `default_reminder_list`：默认 Apple Reminders 列表名。必须与本机 Reminders 里的列表名一致。
- `locale`：解析、展示和提示用的地区语言偏好；不包含隐私数据。

## `[state]`

本机 SQLite、运行状态和幂等记录的位置。

```toml
[state]
dir = "~/.local/share/nudge"
```

- `dir`：状态目录。可以使用 `~`，也可以用相对路径；相对路径会按项目根目录解析。
- 环境变量 `NUDGE_STATE_DIR` 优先级高于 `[state].dir`。
- 状态目录可能包含个人计划、执行历史和 Apple 外部 ID，不应提交。

## `[llm]` 与 `[llm.models]`

LLM provider、密钥读取方式和模型分层。

```toml
[llm]
provider = "qwen"
# 不要把真实 key 写进公开仓库。优先使用环境变量或 secrets_path。
# api_key = "YOUR_PROVIDER_API_KEY"
secrets_path = "~/.config/nudge/secrets.yaml"

[llm.models]
fast = "qwen-plus"
default = "qwen-plus"
strong = "qwen-plus"
```

- `provider`：当前 LLM 提供方。常见值包括 `qwen`、`openai`、`anthropic`、`ollama`；实际可用性取决于本机依赖和命令路径。
- `api_key`：仅用于本机私有配置；公开示例只能保留占位符或注释。
- `secrets_path`：私有 secrets 文件路径示例。建议使用通用路径如 `~/.config/nudge/secrets.yaml`，不要写入个人机器的私有绝对路径。
- `models.fast`：低延迟任务使用的模型。
- `models.default`：常规解析、计划和聊天使用的模型。
- `models.strong`：复杂规划、复盘或需要更强推理时使用的模型。
- 若使用本地推理，可设置 `provider = "ollama"`，并把模型名改成本机已安装的 Ollama 模型。

## Apple backend

Apple 后端决定 Nudge 如何读写 macOS 应用。

```toml
[apple.calendar]
backend = "native"

[apple.reminders]
backend = "native"

[apple.notes]
backend = "native"

[apple.clock]
backend = "shortcuts"
shortcut_name = "Nudge Create Alarm"
```

- `native`：使用项目内本机适配层，适合 Calendar、Reminders、Notes 的默认路径。
- `shortcuts`：通过 Apple Shortcuts 执行动作；Clock/闹钟默认使用此方式。
- `shortcut_name`：Shortcuts 里的快捷指令名称。只写通用名称，不写个人信息。
- 这些配置直接影响真实 Apple 写入使用的机制。`nudge doctor` 会检查后端可用性和常见权限问题。

## `[family]`

家庭成员和“全家/家庭组”路由配置。公开示例必须使用占位符，不要写真实姓名、关系、生日、邮箱或健康信息。

```toml
[family.member_a]
display_name = "家庭成员A"
role = "adult"
aliases = ["成员A", "家人A"]
calendar = "Family"
reminder_list = "Family Tasks"

[family.member_b]
display_name = "家庭成员B"
role = "child"
aliases = ["成员B", "家人B"]
calendar = "Family"
reminder_list = "Family Tasks"

[family.routing]
default = "all"
llm_fallback = false
llm_confidence_threshold = 0.65

[family.routing.display]
title_prefix = true
body_assignee_note = false

[[family.routing.rules]]
match = "作业"
assignees = ["member_b"]
```

- 成员表名（如 `member_a`）是稳定 key，`routing.rules.assignees` 引用这些 key。
- `display_name` 和 `aliases` 供自然语言解析和展示使用。
- `calendar` / `reminder_list` 是该成员的 Apple 写入目标。
- `routing.default = "all"` 表示未匹配规则时发给全部成员；也可填某个成员 key。
- `llm_fallback` 开启后，规则无法判断时可请求 LLM 辅助路由；需要有效 `[llm]` 配置。
- `llm_confidence_threshold` 控制 LLM 路由置信度下限。
- `display.title_prefix` 会在拆分后的标题中增加成员前缀；`body_assignee_note` 会在正文中记录分配说明。
- `rules` 是确定性路由规则，建议优先使用，不依赖 LLM。

## `[user]` 与 `[user.fitness]`

用户资料供 trainer、schedule、habits 等命令生成更贴合的计划。公开仓库只放脱敏、泛化示例。

```toml
[user]
timezone = "America/Los_Angeles"
wake_time = "07:00"
sleep_time = "23:00"

[user.fitness]
level = "beginner"
goal = "general_strength"
equipment = ["dumbbells", "yoga_mat"]
session_minutes = 45
days_per_week = 3
constraints = ["low_impact"]
```

- `[user]`：通用偏好。避免写具体家庭住址、公司、医疗记录等敏感信息。
- `[user.fitness]`：训练计划上下文；`trainer plan` 和相关 Skill 会读取它。
- `equipment`、`constraints` 使用泛化描述即可；不要写入诊断记录或可识别的健康细节。

## `[calendars]`

日历用途映射。用于限定查询范围，减少读取无关日历。

```toml
[calendars]
personal = "Personal"
work = "Work"
family = "Family"
workout = "Fitness"
```

- key 是 Nudge 内部用途名，value 是 Apple Calendar 里的真实日历名。
- schedule、briefing、trainer 等需要忙闲上下文的命令会优先读取这里和 `[general]` / `[family]` 配置过的日历。
- 这里通常影响读取范围；当某个命令把用途映射作为目标时，也会间接影响写入落点。

## `[reminders]`

提醒事项列表用途映射。

```toml
[reminders]
default = "Tasks"
habits = "Habits"
workout = "Fitness Tasks"
family = "Family Tasks"
```

- key 是 Nudge 内部用途名，value 是 Apple Reminders 里的列表名。
- `[general].default_reminder_list` 仍是缺省写入列表。
- 已支持用途映射的命令会使用这里的列表；未支持的路径会回退到默认列表。

## 最小安全配置

如果只想先试用解析和 dry-run，可以从最小配置开始：

```toml
[general]
default_calendar = "Personal"
default_reminder_list = "Tasks"
locale = "zh-CN"

[state]
dir = "~/.local/share/nudge"

[llm]
provider = "ollama"

[llm.models]
fast = "llama3.1"
default = "llama3.1"
strong = "llama3.1"

[apple.calendar]
backend = "native"

[apple.reminders]
backend = "native"

[apple.notes]
backend = "native"

[apple.clock]
backend = "shortcuts"
shortcut_name = "Nudge Create Alarm"
```

真实写入前请运行：

```bash
nudge doctor
nudge --dry-run "明天下午三点项目同步"
```
