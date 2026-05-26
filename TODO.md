# TODO

## 中优先级

- 子代理 A：拆分 `nudge/commands/agent.py` 的 request normalization。只新增 `agent_normalize.py` 一类小模块并保留现有 JSON contract；不碰 execution、status、payload。
- 子代理 B：拆分 `nudge/commands/daemon.py` 的 launchd 控制层。只搬 label/path/domain/service/status/plist render/write/load/start/stop；不碰 queue worker、run loop、health。
- 子代理 C：拆分 `nudge/state.py` 的 schema/migration。只搬 schema 初始化和迁移 helper，保留现有 public API/re-export。
- 子代理 D：收敛 Apple timeout 默认值。只处理 `nudge/apple/*` read/write timeout 常量和对应测试/文档。
- 后续小刀：继续拆 `nudge/commands/agent.py` 的 execution payload、status update。
- 后续小刀：继续拆 `nudge/state.py` 的 action 查询、health persistence、daemon queue。
- 后续小刀：继续拆 `nudge/commands/daemon.py` 的 queue worker、命令执行、状态查询。

## 低优先级

- 观察 runtime log 长期部署后的实际体量；如 3 份轮转仍不足，再评估是否需要压缩归档。
- 继续收敛 docs audit stale-days、daily sync lookback/overdue 等非 Apple 调优默认值。
