# 自然语言输入样例

Nudge 支持把自然语言计划解析为 Apple Calendar、Reminders、Notes 或 Clock 动作。建议所有新输入先走 dry-run：它用于预览解析结果，不应写入 Apple 应用。

> 说明：自然语言解析可能受 LLM provider、配置、当前日期和时区影响。下面示例展示推荐输入形态，不承诺真实 JSON 输出逐字固定。

## CLI dry-run

```bash
nudge --dry-run "明天 15:00 在 Personal 日历安排 30 分钟项目同步"
```

可尝试的安全样例：

```bash
nudge --dry-run "下周一上午 9 点提醒我在 Tasks 列表整理本周计划"
nudge --dry-run "今天 18:30 建一个 10 分钟闹钟，标签是 站起来活动"
nudge --dry-run "创建一条备忘录，标题是 Demo Note，内容是 这是 dry-run 示例"
```

## 裸文本入口

仓库的 CLI 会把非子命令的首个参数当作自然语言请求处理。因此：

```bash
nudge --dry-run "明天 10:00 提醒我检查项目状态"
```

和显式使用对应自然语言命令的效果类似。真实写入时去掉 `--dry-run`，但只有在你确认解析计划无误、且运行在已授权的 macOS 环境时才这样做。

## 非 Mac 用户如何评估

非 Mac 用户无法真实写入 Apple 应用，但仍可：

- 阅读本目录的 JSON/YAML 示例，理解调用契约。
- 运行项目里的纯逻辑测试或文档审计，例如 `bin/nudge docs audit --json`。
- 在具备 LLM 配置的环境中尝试 dry-run/解析-only 流程，观察 Nudge 生成的结构化计划；不要期待 Calendar/Reminders/Notes/Clock 写入成功。

## 不要放入公开示例的信息

- 真实 token、API key、OAuth 凭证。
- 真实家庭成员、健康数据、工作客户信息。
- 本机绝对路径或私有数据目录。
- 真实日历、提醒事项列表、备忘录文件夹名称；公开示例使用 `Personal`、`Tasks` 等占位符即可。
