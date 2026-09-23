# 私有 fork 升级说明（公开库为代码真源）

本文替代此前的「私有仓库 → 公开仓库导出」流程。自 2026-09-22 起方向反转：

- **本公开仓库是代码的唯一真源**：`nudge/` 包、`tests/`、`scripts/`、打包配置与通用文档都在这里演进。
- **私有 fork 只承载个人内容**：本机 `config.toml`、本地 SQLite 状态、个人计划与健康文档、LaunchAgent plist、静态站点内容。
- 私有侧**不再保留一份平行的代码副本**，改为以可编辑安装的方式依赖本公开库；此前的一次性导出脚本、导出回归测试与「Public / Private Split」规则文档随之作废。

这样做的原因：两边各自演进后会出现双向漂移（同名文件内容不同、能力各有独占），而漂移一旦发生，导出脚本既不能安全覆盖，也无法判断谁是权威版本。单向依赖把「谁是真源」这个问题一次性消掉。

## 1. 目录角色

| 位置 | 放什么 | 不放什么 |
| --- | --- | --- |
| 公开库（本仓库） | 可复用 runtime、CLI、Apple adapters、daemon、MCP wrapper、Skills/trainer runtime、测试、通用文档、安装与验证脚本 | 个人配置、真实日历/提醒内容、健康导出、API key、个人计划文档、站点内容 |
| 私有 fork | `config.toml`、本机状态目录、个人计划与复盘文档、站点内容与其测试、私有自动化（plist / cron）、只对本人有意义的 TODO 与 CHANGELOG 条目 | `nudge/` 包源码、公开测试套件、`pyproject.toml`、打包配置 |

判断口径：**一段内容如果删掉本人语境后对任何使用者都成立，它属于公开库；否则属于私有 fork。**

## 2. 私有 fork 如何依赖公开库

推荐以可编辑安装（editable install）方式引用本地的公开库检出，这样公开库一有更新，私有侧立即生效，不需要复制文件。

```bash
# 1) 检出公开库（位置任意，下面用 <公开库路径> 指代）
git clone https://github.com/Zenine/nudge.git <公开库路径>

# 2) 在私有 fork 的虚拟环境里，以可编辑方式安装公开库
cd <私有库路径>
python3 -m venv .venv                      # 若尚未创建
.venv/bin/python -m pip install -e <公开库路径>

# 3) 验证装的是哪一份代码
.venv/bin/python -c "import nudge, pathlib; print(pathlib.Path(nudge.__file__).resolve())"
.venv/bin/nudge --help
```

要点：

- `pip install -e` 只在私有环境里注册一个指向公开库检出的链接，**不会复制源码**；私有库里不应再出现 `nudge/` 包目录。
- 私有侧的配置与状态仍由 `NUDGE_CONFIG` / `NUDGE_STATE_DIR` 或 `config.toml [state].dir` 指定，与代码位置无关。状态目录未配置时 CLI 会 fail-closed 报错，不会回退到源码树下的 `.nudge/`。
- 如果私有 fork 需要自建 LaunchAgent 或包装脚本，让它们调用私有环境里的 `nudge` 入口，不要硬编码公开库内部的模块路径。
- 密钥只走环境变量或 `config.toml [llm].secrets_path` 指向的仓库外私有文件，两个仓库都不提交密钥。

## 3. 升级步骤

每次想吃到公开库的新版本时：

```bash
# 1) 先备份私有状态库（涉及 schema 变更时这是硬前置）
nudge db backup

# 2) 更新公开库检出
cd <公开库路径>
git pull --ff-only
bash scripts/verify.sh            # 公开库自身必须全绿

# 3) 同步依赖（公开库新增第三方依赖时才需要）
cd <私有库路径>
.venv/bin/python -m pip install -e <公开库路径>

# 4) 私有侧冒烟
.venv/bin/nudge doctor --json
.venv/bin/nudge docs audit --json
```

`pip install -e` 建立链接后，日常只要 `git pull` 公开库即可，无需重装；只有依赖清单变化或入口点变化时才重跑第 3 步。

## 4. schema 迁移：先备份

本项目的本地 SQLite schema 会随版本演进（新增列、`state_migrations` 记录表、legacy JSON 归档等）。升级到带 schema 变更的版本时：

1. **先 `nudge db backup`**，确认备份文件已生成且非空，再运行任何会打开状态库的命令。
2. 在承载真实数据的那台机器上执行首次升级后的命令（本项目的真实写入面是 macOS 的 Apple 应用与本机状态库）。
3. 首次运行选一个会读取 SQLite 的命令触发迁移与自检，例如 `nudge skills status --json`；`nudge doctor` 只检查配置与 Apple 权限，不保证打开状态库。确认无报错并核对关键记录数后再跑会写入的命令。
4. 迁移失败或结果不符合预期时，用 `nudge db restore` 回到备份，不要在半迁移状态上继续写入。

`nudge db backup` 现在不会先初始化或迁移源库；源库不存在、存在非空 WAL / rollback journal、或读取期间发生变化时会失败。不要跳过备份直接升级：迁移是就地改写本地状态库，没有第二份权威副本。

## 5. 私有 fork 的验证入口

私有 fork 不再复制公开测试套件。它的验证入口只需覆盖自己真正拥有的东西：

- 个人文档与站点内容的结构性测试（例如静态页渲染、文档格式约定）。
- 本机配置能否被正确加载：`nudge doctor --json`。
- 文档审计：`nudge docs audit --json`。

代码层面的回归由公开库的 `scripts/verify.sh` 负责；私有侧若发现代码缺陷，**改在公开库并补公开测试**，不要在私有侧打补丁，否则漂移会重新长出来。

## 6. 已作废的机制

| 机制 | 状态 | 说明 |
| --- | --- | --- |
| `scripts/export_public.sh`（私有侧一次性导出脚本） | 作废 | 方向反转后不再需要「私有 → 公开」的导出；公开库不提供替代脚本 |
| `tests/test_public_export.py`（导出回归与隐私扫描测试） | 作废 | 它断言的是导出产物形态，而导出流程已取消；隐私边界改由「私有 fork 不放代码、公开库不放个人数据」的目录角色保证 |
| `docs/PUBLIC_REPO_SPLIT.md`（私有 → 公开切分规则） | 由本文替代 | 规则方向相反，不做保留式改写 |
| `.nudge-public-export`（导出标记文件） | 已删除 | 该标记声明「本仓库由私有仓库导出生成」，与当前方针矛盾 |

上述三个文件位于私有 fork，本次变更只在公开库侧删除已失效的 `.nudge-public-export` 标记并发布本文；私有侧的清理在私有库自行完成。
