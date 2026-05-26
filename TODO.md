# TODO

## 中优先级

- 将 `nudge docs audit` 的 suggestion 跟进策略产品化：明确哪些 suggestion 只提示、哪些进入 `daily sync` maintenance action，以及是否需要单独的 `docs fix` 工作流。
- 拆分 `nudge/state.py`：schema/migration、action 查询、health persistence、daemon queue 分到更小模块。
- 拆分 `nudge/commands/daemon.py`：launchd 控制、queue worker、命令执行、状态查询分层。
- 拆分 `nudge/commands/agent.py`：请求归一化、确认 token、执行 payload、status update 分层。

## 低优先级

- 观察 runtime log 长期部署后的实际体量；如 3 份轮转仍不足，再评估是否需要压缩归档。
- 继续收敛实现层调优默认值：daemon retry、queue depth、Apple read timeout 等目前仍分散在各自模块。
