# Nudge TODO

> 最后更新：2026-09-22。本文件只登记未落地的增量待办；已交付事实记在 `CHANGELOG.md`，2026-06-20 / 07-04 / 07-05 三批历史审查脉络已迁至 `docs/archive/reviews-2026-06-20-to-2026-07-05.md`。
>
> 本轮来源：2026-09-04 与 2026-09-05 两次独立只读审阅的发现，经 2026-09-08 复核逐条去重与再验证后合并至此。写法约定：待办统一用 `- [ ]`，不在本文件写完成态标记（`docs audit` 的 `DOCS_TODO_HISTORY` 规则会据此告警）。

## 2026-09-08 复核基线（证据）

以下数字来自本轮实际运行的命令，用于判断后续条目是否仍成立：

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 测试套件 | `pytest tests/ -q` | 365 passed |
| 文档审计 | `bin/nudge docs audit` | errors 0 / warnings 5 |
| 完整验证 | `scripts/verify.sh` | `Nudge public verification passed` |
| 未配置状态目录 | `env -u NUDGE_STATE_DIR -u NUDGE_CONFIG bin/nudge --help` | exit 0，无 traceback |
| git | `status --short` / `rev-list --left-right --count main...origin/main` | 干净，0/0 齐平 |
| 版本 | `pyproject.toml` | `0.5.1`，最后一次提交 2026-08-08 |

代码本身状态良好，结论是「接近稳定但发布线与验证入口停摆」，不是代码腐坏。

> 2026-09-22 合流后，上表的测试数量、文档审计 warning 数与版本状态需要重新采样；判断后续条目是否成立时以本轮实际运行输出为准，不要直接引用 09-08 的数字。

## P0 阻塞

当前无 P0 阻塞。公私两库关系已于 2026-09-22 裁决并合流：代码真源只在本公开仓库，承载个人数据的私有 fork 改为以可编辑安装依赖本库，导出机制作废。合流范围与裁决要点记在 `CHANGELOG.md`，长期规则见 `docs/PRIVATE_FORK_UPGRADE.md`。

## P1 重要

- [ ] **`log done` 的 Apple 镜像完成应使用 action 所属列表**：`nudge/commands/log.py` 的 `_sync_apple_reminder_completion()` 当前取全局默认列表，未优先使用 action 的 `reminder_list`；非默认列表的已知外部 ID 会因此查错列表。下一步在 `tests/test_commands_log.py` 补跨列表回归测试，再修正列表选择，使用隔离状态目录验证；验证前不要用该命令代替明确指定列表的 Apple 完成操作。

- [ ] **Apple 适配层与若干模块无直接测试**：`tests/` 对 `apple/calendar.py`、`clock.py`、`mail.py`、`notifications.py` 零引用（`notes`/`reminders`/`common` 各 1、`adapters` 4）；`llm.py`、`family_routing.py`、`adapt.py`、`runtime_log.py`、`daemon_control_app.py`、`patch.py`、`skills/engine.py`、`skills/schema.py` 同样无直接测试。Apple 写入是本项目唯一不可逆的副作用面，恰好是覆盖最薄的一层，AppleScript 拼接的注入防线只有 `common.escape` 有测试。
  - 建议动作：先给 `notifications.py`、`family_routing.py`、`adapt.py` 补纯逻辑离线单测；再给 `calendar.py`、`notes.py`、`clock.py` 的脚本生成路径补「生成的 AppleScript 文本」快照测试。把 `coverage` 加入 `requirements-dev.txt` 以便量化（当前无法量化，缺口是按静态 import 统计，可能低估 CliRunner 间接覆盖）。
  - 测试盘子本身健康：35 个测试文件 / 270 个 `def test_`（参数化后 353 用例），零 skip、零 xfail、零无断言测试——这部分不要动。

- [ ] **发布线停摆，版本号与 CHANGELOG 脱节**：`pyproject.toml` 仍是 `0.5.1`（2026-07-05），而 `CHANGELOG.md` 的 `[Unreleased]` 已积压 Added 2 / Changed 8 / Fixed 15 条，时间跨度到 2026-08-08。外部用户无法通过版本号判断拿到哪一批修复，README 里 pipx 安装的承诺已挂两个月。
  - 建议动作：决定是否切 `0.6.0`（有 `reminders reconcile-missing`、`backfill-lists`、`feedback interview` 等新命令，属 minor），切版时同步版本号与 CHANGELOG 段落标题日期，按 `docs/releasing.md` 走；若明确暂不发布，在本文件写清阻塞原因与触发条件，不要悬着。

- [ ] **依赖无版本约束、无锁文件**：`requirements.txt` / `pyproject.toml` 的 5 个依赖全部无上下界，仓库无锁文件。工程侧曾有 `click<8.2` 的约定，但本仓库任何文件都没有这条记录，而当前环境实际是 click 8.4.2 且测试全绿；合流时并入的 `_runner()` 兼容函数已让测试同时适配 click 8.1 / 8.2+ 的 `mix_stderr` 差异，该约定可视为不再成立。依赖清单一致性现已有 `tests/test_requirements.py` 约束（运行依赖覆盖实际 import、不含 `playwright`、dev 依赖覆盖打包检查、pyproject 与 requirements 同集合），但仍缺版本区间与锁文件。
  - 建议动作：二选一并写进仓库。(a) 约定仍成立 → 在 `requirements.txt` 与 `pyproject.toml` 写死上界，并补一条断言上界存在的测试；(b) 约定已作废（本轮证据倾向于此）→ 显式作废并引入 `requirements.lock` 固定 CI 环境。无论哪条，都在 `CONTRIBUTING.md` 或 `docs/` 留一句环境口径。

## P2 可选

- [ ] **裁定 `config.local.toml` 覆盖层：实现，还是宣告不存在**（2026-09-23 由私有库带出）。私有库 `nudge-private/.gitignore:12` 忽略 `config.local.toml` 并注释为「本机覆盖层」，读起来像本仓存在一套「基础配置 + 本机覆盖」机制；实测本仓 `nudge/config.py` 中 `config.local` / `local.toml` / overlay **零命中**，`load_config()` 只有「显式路径 → `NUDGE_CONFIG` → 源码树 `config.toml` → XDG」四级查找，**无任何合并逻辑**。
  - 背景：私有库 2026-09-23 裁决 `config.toml` 继续跟踪，而 Mac 与 Linux 两台机器共用该文件，机器差异当前靠 `NUDGE_STATE_DIR` 环境变量解决（`resolve_state_dir()` 第一优先读它，已验证可用、无需改代码）。
  - 选项 A（本仓实现）：`load_config()` 读到 `config.toml` 后，若同目录存在 `config.local.toml` 则浅合并，并补测试与文档。
  - 选项 B（不实现）：本仓明确该文件名无效，由私有库改 `.gitignore` 注释；机器差异一律走环境变量。
  - 在裁定前，**不得让文档或 agent 依赖 `config.local.toml` 生效**。对应条目见 `nudge-private/TODO.md` §3。

- [ ] **文档审计常年 5 条 warning，会持续生成维护 action**：当前 4 条 `DOCS_STALE_PLAN`（`docs/superpowers/plans/` 下 2026-07-04 ×2、07-05、07-19 四份计划）、1 条 `DOCS_ARCHIVE_CANDIDATE`（`docs/superpowers/specs/2026-07-19-reminder-list-backfill-design.md`），errors 0。`nudge/commands/daily.py` 约 324 行的触发条件是 `errors > 0 or warnings > 0`，于是 `daily sync --apply` 会一直维持一条关不掉的 docs 维护 action，属典型告警疲劳源。
  - 建议动作：把已落地的 4 份计划与 1 份 spec 归档到 `docs/superpowers/archive/`（审计对 `docs/**/archive/**` 免检），并考虑把维护 action 触发条件收紧到 `errors > 0`，warning 只在报告里展示。

- [ ] **`scripts/check_package.sh` 里还有第三份静默回落**：同构的 `-x "$ROOT/.venv/bin/python"` → `python3` 逻辑未改。日常由 `verify.sh` 调起、`NUDGE_PYTHON` 会继承下去所以不会走到坏分支，但单独执行该脚本时仍会静默回落。改为 source `scripts/lib/python_env.sh` 的 `nudge_resolve_python`。

- [ ] **公开库缺 agent 规则文件**：仓库内没有 `AGENTS.md` / `CLAUDE.md`，agent 会话只能从 README/CONTRIBUTING 推断规则，拿不到「验证入口是 `scripts/verify.sh`、先写测试、不碰 Apple 真实写入、`.nudge/` 不入仓」这类硬约束。补一份精简公开版，只写可披露的工程边界，不引入本机绝对路径、内部邮箱或个人数据口径。

- [ ] **launchd 双管理入口重叠**：`scripts/bootstrap_launchd.sh` 管 4 个 LaunchAgent，`nudge daemon launchd install` 只管 `com.nudge.agent`，两处各自生成/加载 plist，先后安装同名 agent 时状态可能不一致。收敛为单一入口（脚本调 CLI，或 CLI 调脚本）。验证需 macOS。

- [ ] **命令层承载核心执行逻辑，模块持续变大**：`nudge/state.py` 1680 行、`commands/daemon.py` 1067、`agent.py` 966、`reminders.py` 948、`skills.py` 904；`agent.py` 仍从 `do.py` import 私有 `_action_schema_problems` 与 `execute_action`。真正的执行核心住在 Click 模块内，任何 `do.py` / `agent.py` 重构都会波及 mcp/daemon/trainer/skills，单测难隔离。
  - 建议动作：抽出 `nudge/actions_core.py` 承载 `execute_action`、schema 校验、family 改写、materialize，命令模块只做参数解析与输出。重构后 `verify.sh` 全绿且无行为变更。
  - 依赖：公私库裁决已于 2026-09-22 落地（真源只在公开库），漂移风险解除，可以开始；但建议排在发布线恢复之后。

- [ ] **README 无截图或演示**：无任何可视化材料，降低外部「发现→试用」转化。建议在切版发布时一并补 asciinema 或终端录屏 GIF；发布线未通时收益有限，排在发布之后。

- [ ] **确认 `origin/gh-pages` 分支是否还需要**：README 未提及任何 Pages 站点。注意 GitHub Pages 站点可能独立于仓库可见性对公网可达，删除前先确认该分支没有在对外提供内容。

## 长期增量

- [ ] 在真实 Dogfood 稳定后设计非 TTY 的结构化反馈客户端协议，供未来 IM / iOS 入口复用 `nudge.feedback.interview.v1`；首版不得扩大 Apple 读取或写入权限。

## 本轮复核判定为无需行动

- **抽跨库共享工具包**：核实过 nudge 与另外三个本机库在配置加载、日志、CLI 框架、日期处理上的「重复」，分属四种语言四种运行时，属伪重复，不可行。真实的跨库重复是 `scripts/verify.sh` 这套**约定文本模板**，不是代码。
- **消融 / 对照实验**：工具类项目，无模型、无可消融组件，不适用，不要硬凑。
- **状态目录耦合与路径硬编码**：全库源码零硬编码本机绝对路径，状态目录两级可配置（`NUDGE_STATE_DIR` > `[state].dir`），机制本身正确（表达方式问题见 P0）。
- **打包边界**：`scripts/check_package.sh` 对 wheel/sdist 双向校验（必须含包数据、禁止含 tests / `config.toml` / `.env` / `.db` / `.zip` / Health 片段），与 `MANIFEST.in` 一致。
- **`config.example.toml`**：全部为占位符，无真实姓名、健康细节或密钥。
- **异常静默吞掉**：全库 `except Exception` 42 处，直接 `pass` 仅 1 处（`commands/skills.py:173`），错误处理纪律良好。
- **CI 配置**：`.github/workflows/verify.yml` 锁定 Python 3.12、装 dev requirements、额外重复一遍运行时状态守卫，配置合理。
- **文档覆盖度**：`docs/commands.md`（2026-08-10）已收录 `reconcile-missing`、`backfill-lists`、`backfill-ids`、`feedback interview`、`daemon health`、`skills adapt`，与代码同步。
