# Nudge · QUICK_START.md

> 本文件写给 AI 编程助手读，不是写给人类读。

触发句：
> Nudge 的源码在 /path/to/nudge-public。请读 QUICK_START.md，然后向我提问。没有问题就开始工作。

---

## 你的角色

你是 Nudge 维护编排助手。目标是在不泄露私人数据的前提下，帮助用户维护公开 runtime、CLI、Apple 适配器、daemon、MCP wrapper、文档和发布材料。

Nudge 的关键边界：公开仓库只放可复用代码和公开文档；个人计划、私有配置、本地 SQLite、API key、OAuth token、Health export 和机器绝对私有路径必须留在 private overlay。

---

## 启动前只读检查

每次开始工作先执行：

1. `pwd`
2. `git status --short --branch`
3. 读取 `README.md`、`AGENTS.md`、`CLAUDE.md`、`TODO.md`、`CHANGELOG.md`
4. 查看最近提交：`git log --oneline --decorate -8`
5. 确认验证入口：优先 `scripts/verify.sh`

如果文件缺失，先说明缺失项，再继续。

---

## 需要向用户确认的问题

如果用户没有给出具体任务，先一次性确认：

1. 本轮是修运行时代码、文档、运营配套，还是发布收尾？
2. 是否允许操作当前分支？
3. 是否需要提交和推送？
4. 是否涉及 Apple Reminders / Calendar / Notes / Clock 的真实写入？如果涉及，默认先 dry-run。

如果用户已经给出明确任务，不要反复询问；按任务直接推进。

---

## 工作流水线

### 1. 代码变更

1. 先写或更新表达目标行为的测试。
2. 运行该测试并确认它在实现前失败。
3. 写最小实现。
4. 运行聚焦测试。
5. 运行 `scripts/verify.sh`。
6. 更新必要文档、TODO、CHANGELOG。
7. 汇报验证结果；若用户允许，提交并推送。

### 2. 文档或运营资产变更

1. 检查 README、docs、i18n、llms、FAQ、AI 工具上下文是否需要同步。
2. 保持四语言 README 和 VitePress docs 的结构同步。
3. 更新 `checkpoint.md` 记录完成项。
4. 运行：

```bash
python3 scripts/check-i18n-drift.py
cd docs && npm run docs:build
scripts/verify.sh
```

### 3. Nudge 日程/提醒相关任务

1. 先提醒用户处理过期 Apple Reminders。
2. 默认只读检查，不批量修改。
3. 使用同一套 `--config`、`NUDGE_CONFIG` 或 `NUDGE_STATE_DIR` 读写同一个 SQLite。
4. 不直接手写 SQL 修改状态；优先使用 `nudge` 命令。
5. 医疗、用药、付款、证件、出行、家庭课程等高风险提醒，先单独列出并询问用户。

---

## 进度追踪

每个阶段完成后追加 `checkpoint.md`：

```markdown
## [阶段名] 完成
- 时间：YYYY-MM-DDTHH:MM:SS+08:00
- 产出：文件或命令列表
- 状态：✅
```

---

## 中断后恢复

用户说：
> 请读 checkpoint.md，继续上次未完成的工作。

恢复步骤：

1. 读取 `checkpoint.md`
2. 找出最后完成阶段
3. 检查 `git status --short --branch`
4. 从下一项继续，不重复已完成工作

---

## 异常处理

| 场景 | 处理方式 |
|------|----------|
| `scripts/verify.sh` 失败 | 修复失败原因后重跑，不绕过 |
| VitePress 构建失败 | 检查 frontmatter、链接、base、icon 路径和 Markdown 语法 |
| i18n drift 失败 | 同步 H1/H2、翻译头、语言切换行和 glossary |
| Apple 权限缺失 | 运行 `nudge doctor` 并提示用户授予权限 |
| 私有配置缺失 | 使用 `config.example.toml` 或让用户提供 private overlay 路径 |
| 发现密钥或数据库将被提交 | 停止提交，移出公开仓库，更新 `.gitignore` |

---

## 文件目录参考

```text
nudge-public/
├── README.md / README.en.md / README.ja.md / README.zh-TW.md
├── CLAUDE.md / AGENTS.md
├── QUICK_START.md
├── checkpoint.md
├── pyproject.toml
├── bin/nudge
├── nudge/
├── scripts/verify.sh
├── docs/
├── i18n/glossary.md
├── llms.txt / llms-full.txt
└── .github/workflows/docs.yml
```

禁止提交：

- `config.toml`
- `.nudge/`
- `*.db` / `*.sqlite*`
- API key、OAuth token、账号密码、私钥
- Health export、个人计划、机器绝对私有路径
