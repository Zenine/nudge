# 部署前检查清单

本文用于判断 Nudge 是否可以在本机进入可用部署状态。当前项目的部署目标是 Mac 本机 CLI + daemon / LaunchAgent + Apple Calendar、Reminders、Notes、Mail、Shortcuts 等本地集成；外部用户试点和 Cloud Relay 仍以 `TODO.md` 和阶段门槛为准。

## 1. 基础环境

- [ ] 进入项目目录：`cd <repo>`
- [ ] 确认 Git 工作区没有意外改动：`git status --short`
- [ ] 确认 Python 版本满足项目要求：`python3 --version`，需要 `>= 3.12`
- [ ] 安装依赖：`python3 -m pip install -r requirements.txt`
- [ ] 安装 CLI 入口：`scripts/install_cli.sh`
- [ ] 确认 `nudge` 或固定路径 wrapper 可执行：`<repo>/bin/nudge --help`

## 2. 验证与冒烟

部署前必须优先运行项目自带验证入口：

```bash
scripts/verify.sh
```

通过标准：

- [ ] pytest 全部通过
- [ ] CLI smoke checks 全部通过
- [ ] 没有失败的 pre-commit / verify / 测试项

如果验证失败，不要继续部署；先修复失败原因。除非明确记录失败原因并由用户要求临时紧急绕过，否则不得绕过失败的验证或钩子。

## 3. 配置、密钥与本机权限

- [ ] `config.toml` 能正常加载：`nudge doctor --json`
- [ ] LLM provider、model、base URL 和 API key 配置可用
- [ ] 长期密钥没有写入仓库；本机密钥应放在仓库外的私有 `secrets.yaml`，并通过环境变量或本机忽略配置注入
- [ ] Calendar 权限正常
- [ ] Reminders 权限正常
- [ ] Notes 权限正常，如启用 Notes 写入或标题列表
- [ ] Mail 权限正常，如启用 briefing 中的邮件摘要
- [ ] Notifications 权限正常，如启用 `--notify`
- [ ] Automation 权限正常，允许当前 Terminal / IDE / Python 控制 Calendar、Reminders、Mail 等 Apple app

建议先手动打开一次 Calendar、Reminders、Notes 和 Mail，再到 **系统设置 → 隐私与安全性** 确认权限。

`nudge doctor --json` 的目标状态：核心能力无 `FAIL`；如果 Reminders 有 `WARN`，应先解决后再把 Reminders 相关能力视为可部署。

## 4. daemon / LaunchAgent

部署本机无头 daemon：

```bash
nudge daemon launchd install
nudge daemon launchd start
nudge daemon launchd status --json
nudge daemon health --json
```

通过标准：

- [ ] `plist_exists: true`
- [ ] `loaded: true`
- [ ] `state_hint` 不再是 `not_loaded`
- [ ] `daemon health` 没有 `LAUNCHD_PLIST_MISSING`
- [ ] `daemon health` 没有 `LAUNCHD_NOT_LOADED`
- [ ] 没有 stale `running` 任务
- [ ] 没有 `dead_letter` 任务，或已经按 `docs/daemon-runbook.md` 完成人工处理

如需图形化控制入口，可选安装：

```bash
nudge daemon app install --login-item
```

## 5. 可选自动化

### 自动维护定时任务

如需早晚自动 briefing、每日 sync 和无头 daemon：

```bash
scripts/bootstrap_launchd.sh
scripts/bootstrap_launchd.sh status
```

确认四类定时任务已加载，并检查对应日志没有持续错误：

- `com.nudge.morning`
- `com.nudge.daily-sync`
- `com.nudge.evening`
- `com.nudge.agent`

`com.nudge.daily-sync` 默认每天 07:15 执行 `nudge daily sync --apply --json`，会同步 Reminders / Health，并运行 docs audit；如发现文档维护债，只创建本地 maintenance action，不直接改文档。

### Clock / Shortcuts

默认部署可把 `[apple.clock] backend = "disabled"`，表示当前不写真实 Clock 闹钟，`nudge doctor --json` 应显示 Clock `PASS backend=disabled`。

如果需要真实写入 Clock 闹钟：

- [ ] 将 `[apple.clock] backend` 改为 `shortcuts`。
- [ ] 在 Shortcuts.app 创建名为 `Nudge Create Alarm` 的快捷指令。
- [ ] 快捷指令能读取输入 JSON 中的 `time` / `label`。
- [ ] 快捷指令能调用 Clock 创建闹钟。
- [ ] `nudge doctor --json` 不再提示 Clock shortcut 缺失。

如果当前不使用真实 Clock 闹钟，应明确禁用 backend，而不是长期保留 Clock `WARN`。

## 6. 部署后最小验收

完成安装和权限处理后，执行以下最小验收：

```bash
nudge --help
nudge doctor
nudge daemon health
nudge daemon queue --json
```

再做一次不会写入 Apple app 的 dry-run：

```bash
nudge do --json --dry-run "明天上午 9 点提醒我检查 Nudge daemon 状态"
```

如果 dry-run 正常，再执行一次小范围真实写入，并人工确认：

- [ ] Calendar 或 Reminders 中出现对应项
- [ ] 本地 SQLite 能记录 action
- [ ] `nudge log done` 或 `nudge check-in` 能写回完成状态
- [ ] `nudge daily sync` 可运行

## 7. 当前阶段判断口径

- **本机自用 / Phase 1.7 dogfood**：代码验证通过、核心权限正常、daemon health 正常后即可部署。
- **外部用户试点 / Phase 2**：不只看部署脚本是否可用，还必须满足 `TODO.md` 中的阶段门槛，包括连续 dogfood、完成率、Reminders 权限策略、外部 onboarding、失败指标等。
- **Cloud Relay / iOS App / Marketplace**：仍属于后续阶段，不应因为本机底座可部署就提前启动。

## 8. 常见阻塞与处理

| 阻塞 | 处理 |
| --- | --- |
| `scripts/verify.sh` 失败 | 停止部署，先修测试或 CLI smoke 失败项 |
| `LAUNCHD_PLIST_MISSING` | 运行 `nudge daemon launchd install` |
| `LAUNCHD_NOT_LOADED` | 运行 `nudge daemon launchd start` 或重新 install |
| Reminders 连接无效 / 权限 WARN | 打开 Reminders；在系统设置中授权当前 Terminal / IDE / Python 访问提醒事项和自动化 |
| Clock shortcut 缺失 | 如需闹钟则创建 `Nudge Create Alarm`；否则把 `[apple.clock] backend` 设为 `disabled` |
| `dead_letter` 队列不为空 | 按 `docs/daemon-runbook.md` 检查幂等性后逐条 retry 或归档 |
