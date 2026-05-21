# TODO

## 高优先级

- 为 `nudge do` 增加不依赖真实 LLM 的解析/校验测试，覆盖坏 JSON、缺字段、结束时间早于开始时间、family group 展开。
- 为 `nudge agent apply` 增加 dry-run token、plan-driven confirmation、批量上限和部分失败的回归测试。
- 为 MCP stdio 增加 JSON-RPC initialize、tools/list、tools/call、错误响应测试。
- 为 runtime log 增加轮转/压缩策略，避免长期 daemon 部署日志无限增长。

## 中优先级

- 拆分 `nudge/state.py`：schema/migration、action 查询、health persistence、daemon queue 分到更小模块。
- 拆分 `nudge/commands/daemon.py`：launchd 控制、queue worker、命令执行、状态查询分层。
- 拆分 `nudge/commands/agent.py`：请求归一化、确认 token、执行 payload、status update 分层。

## 低优先级

- 继续收敛实现层调优默认值：daemon retry、queue depth、Apple read timeout 等目前仍分散在各自模块。
- 给 AppleScript/EventKit 适配层补充 mock backend 示例，方便非 macOS 环境测试。
