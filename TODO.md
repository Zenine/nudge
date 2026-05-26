# TODO

## 高优先级

- 为 `nudge do` 增加不依赖真实 LLM 的解析/校验测试，覆盖坏 JSON、缺字段、结束时间早于开始时间、family group 展开。

## 中优先级

- 收敛 `README.md` 和 `README.zh-CN.md`：把长篇配置、命令和排障细节进一步下沉到 `docs/`，让 `DOCS_LONG_ENTRYPOINT` suggestion 归零。
- 将 `nudge docs audit` 的 suggestion 跟进策略产品化：明确哪些 suggestion 只提示、哪些进入 `daily sync` maintenance action，以及是否需要单独的 `docs fix` 工作流。
- 拆分 `nudge/state.py`：schema/migration、action 查询、health persistence、daemon queue 分到更小模块。
- 拆分 `nudge/commands/daemon.py`：launchd 控制、queue worker、命令执行、状态查询分层。
- 拆分 `nudge/commands/agent.py`：请求归一化、确认 token、执行 payload、status update 分层。

## 低优先级

- 观察 runtime log 长期部署后的实际体量；如 3 份轮转仍不足，再评估是否需要压缩归档。
- 继续收敛实现层调优默认值：daemon retry、queue depth、Apple read timeout 等目前仍分散在各自模块。
- 给 AppleScript/EventKit 适配层补充 mock backend 示例，方便非 macOS 环境测试。
