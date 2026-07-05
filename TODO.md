# Nudge TODO

## 代码审查发现(2026-06-20:安全/性能/功能)

> 来源:对 `nudge` 仓库的只读代码审查(本地优先 macOS CLI,Python 3.12+)。
> 严重程度分级:高 / 中 / 低。本节由自动化审查生成,落地前请人工复核,避免与既有计划重复。


### 已完成记录(降噪汇总)

以下事项已由后续实现或文档补齐,保留为历史事实,不再作为优先待办推荐:

- 2026-07-04:Health XML 安全解析、XML entry size 上限、SQLite schema 初始化缓存、actions 常用索引、LLM JSON fence/说明文字解析、开源基础设施、命令参考。
- 2026-07-05:MCP/agent 本地 token auth、legacy `state.json` 迁移归档、HMAC secret 原子创建、AppleScript escape 契约测试、Skills runtime 接线、trainer 默认统一到 Skill runtime、配置文档、架构文档、示例库、CHANGELOG。


### 安全

- ~~**[中] MCP / agent 写入入口无身份认证,任何能写入 stdin / 调用 CLI 的进程都能改写 Apple 数据**~~
  - 位置:`nudge/commands/mcp.py:46`(`serve_command` 直接信任 stdin JSON-RPC)、`nudge/commands/agent.py:74`(`apply_command` 信任 stdin / 文件)。
  - 影响:本地任何进程或被诱导的 MCP client 都可发起 `apply_apple_actions` 写日历/提醒/备忘录/闹钟。`require_confirmation`、`request_id` 幂等、HMAC dry-run token 只防“误写/重复写”,不防“恶意调用方”。
  - 建议:文档已声明本地优先模型,可在 README/AGENTS 明确威胁模型边界;若要更严,考虑对 MCP serve 增加可选的本地 token / 调用方白名单,并在 `_tool_annotations` 注释外再加一层服务端校验说明。
  - 备注:这是设计取舍,需人工确认是否接受现状,不要静默当成 bug 修。
  - 状态:2026-07-05 已完成可选本地 token auth: `[security.local_auth]` 默认关闭;启用后保护 `agent apply/status`、MCP `apply_apple_actions/report_action_status` 与 daemon 队列执行路径。

- ~~**[中] Apple Health 导出 XML 解析使用 `xml.etree.ElementTree.iterparse`,对不可信 zip 存在 XXE / 实体膨胀(billion laughs)风险**~~
  - 位置:`nudge/health.py:7`(`import xml.etree.ElementTree as ET`)、`nudge/health.py:137`(`ET.iterparse`)。
  - 影响:虽然导出文件通常来自用户自己的 Apple Health,但若导入来源不可信的 `export.zip`,标准库默认会处理实体引用,可能触发实体膨胀拒绝服务或本地文件读取。
  - 建议:对外部输入改用 `defusedxml`(或显式关闭实体解析的自定义 parser);至少在文档中限定只导入用户本人可信导出。
  - 备注:`requirements.txt` 未含 `defusedxml`,引入需评估“纯标准库”约定。
  - 状态:2026-07-04 已完成 defusedxml 解析与 XML 大小上限防护。

- ~~**[低] Health 导入 zip 仅按名读取条目,未做 zip-slip / 超大解压防护**~~
  - 位置:`nudge/health.py:131-136`、`nudge/health.py:496-504`(`ZipFile` + `zf.open`/`namelist`/`infolist`)。
  - 影响:当前只 `open` 读流、未 `extractall`,zip-slip 风险较低;但未限制单个 XML 解压大小,异常超大导出可能耗尽内存(配合上一条)。
  - 建议:对候选 XML 读取设大小上限,或流式解析时限制累计字节。
  - 状态:2026-07-04 已完成 XML entry size 上限防护;zip-slip 仍因不 `extractall` 保持低风险。

- ~~**[低] AppleScript 转义函数静默丢弃换行/制表符,且为各 adapter 共用唯一防注入屏障**~~
  - 位置:`nudge/apple/common.py:7`(`escape`)。被 `reminders.py` / `calendar.py` / `notes.py` 大量内插到双引号 AppleScript 字符串。
  - 影响:`escape` 仅处理 `\` `"` 与空白,双引号转义可阻断常规注入;但把 `\n`/`\t` 替换成空格会静默改写用户文本(数据完整性问题),且所有注入安全都集中依赖这一个函数,改动风险高。
  - 状态:2026-07-05 已完成测试覆盖:新增 `tests/test_apple_escape.py`,固定双引号/反斜杠转义、换行/回车/制表符替换为空格、组合注入 payload 不保留原始换行或未转义双引号的当前契约。Notes 适配的正文路径已用离线测试确认先将原始多行正文转换为 HTML 结构再嵌入 AppleScript,不是把原始正文直接交给 `escape` 丢换行;本次未改变生产语义。

- ~~**[低] 确认 token HMAC 密钥文件创建有 TOCTOU 与并发写竞态**~~
  - 位置:`nudge/commands/agent.py`(`_confirmation_secret`,确认 token HMAC 密钥)。
  - 影响:多个进程并发首次写入时可能互相覆盖密钥,导致已发出的 dry-run token 失效;`chmod 0o600` 在写入之后,存在极短窗口文件权限默认更宽。
  - 状态:2026-07-05 已完成:改为 `O_CREAT|O_EXCL` 原子创建,创建 mode 传入 `0o600`;若并发创建输掉竞态则读取已存在 secret,不覆盖。

### 性能

- ~~**[中] 每次状态操作都新建 SQLite 连接并重跑建表/迁移,daemon 循环下放大开销**~~
  - 位置:`nudge/state.py:74-93`(`_get_conn` / `_db`),每次调用都 `_ensure_migrated` + `connect` + `PRAGMA journal_mode=WAL` + `_init_tables`(`executescript` 全部 `CREATE TABLE/INDEX IF NOT EXISTS`)。
  - 影响:`nudge/commands/daemon.py:1052` 的 `run` 循环每条命令会触发多次状态读写,每次都重新建表/设 PRAGMA;agent apply 单请求也多次开关连接。高频场景下是明显的重复初始化成本。
  - 建议:把建表/迁移收敛为“进程内只跑一次”(已有 `_migrated` 标志,可同样缓存“已初始化”状态),或复用一个长连接 / 连接缓存;`PRAGMA` 与 `_init_tables` 不必每次执行。
  - 状态:2026-07-04 已完成小范围优化:按 `DB_PATH` 缓存 schema 初始化,`configure_state()` 重置缓存,迁移改用 raw connection 避免 `_get_conn()` 递归耦合;仍保留每次 `_db()` 打开/关闭连接。

- ~~**[中] `actions` 表缺少查询列索引,周期报表/状态过滤走全表扫描**~~
  - 位置:`nudge/state.py:107-118`(`actions` 表无 `status`/`scheduled_at`/`completed_at`/`plan_id`/`created_at` 索引);`nudge/state.py:469-521`(`get_actions` 用复杂 OR 时间条件查询)。
  - 影响:`review` / `daily sync` / 自动跳过睡眠提醒(`skip_later_sleep_reminders_after_completion` → `get_actions(since, until)`)在 actions 增长后会变慢。
  - 建议:为 `actions(status)`、`actions(scheduled_at)`、`actions(completed_at)`、`actions(plan_id)` 增加索引;或加 `created_at` 复合索引。
  - 状态:2026-07-04 已完成:新增 `idx_actions_status`、`idx_actions_plan_id`、`idx_actions_scheduled_at`、`idx_actions_completed_at`、`idx_actions_created_at`。

- ~~**[低] 完成一个睡眠相关 action 会触发额外区间查询 + 逐条更新**~~
  - 位置:`nudge/state.py:377-422`(`skip_later_sleep_reminders_after_completion` 调 `get_actions` 再循环 `update_action_status`,每次 `update_action_status` 又各开一次连接)。
  - 影响:每次 `complete_action` 都附带一次范围查询和 N 次单独写连接,放大上面的连接开销问题。
  - 建议:在同一连接/事务内批量更新;与连接复用一起优化。
  - 状态:2026-07-05 已完成:睡眠 auto-skip 改为在同一 `_db()` 连接/事务内查询 completed action、查询区间 actions,并用 `executemany` 批量更新后续睡眠提醒;新增回归测试确认只进入一次状态连接且行为不变。

- **[低] `get_habit_streaks` 用相关子查询取每习惯最新日期**
  - 位置:`nudge/state.py:315-332`。
  - 影响:`habit_logs(habit_name,date)` 有 UNIQUE 索引可支撑,数据量小一般无碍;习惯/历史变大后 `(col,col) IN (SELECT MAX...)` 仍可能不够优。
  - 建议:必要时改写为窗口函数或按 habit 分组取 max 的 join;低优先。

### 功能缺陷与提升

- ~~**[中] LLM 输出 JSON 解析对 markdown fence 处理过于脆弱**~~
  - 位置:`nudge/brain.py:232-237`(`_parse_json`:仅当首行以 ``` 开头时,按“去掉首行、若末行是 ``` 再去末行”切片)。
  - 影响:模型在 fence 前后加说明文字、用 ```json 带语言标记换行不规范、或返回前导空白时,`raw.startswith("```")` 判断失败或切片错位,直接 `json.JSONDecodeError`。多个调用方(check-in、家庭路由等)依赖它。
  - 建议:改为正则提取第一个 ```...``` 代码块或第一个 `{`/`[` 到匹配结尾的子串;并对解析失败统一回退/重试。
  - 状态:2026-07-04 已完成:支持 fenced JSON、前后说明文字、正文内首个 JSON object/list 提取,并新增 `tests/test_brain_json_parse.py` 回归测试。

- ~~**[中] `_migrate_from_json` 迁移与重命名非原子,且未用统一连接管理**~~
  - 位置:`nudge/state.py:248-282`。
  - 影响:迁移过程中(写 habit_logs 后、`rename` 前)若进程崩溃,下次再进会因 `count > 0` 跳过迁移但旧 `state.json` 仍在,残留歧义;且这里手工 `conn.close()` 而非 `_db()` 上下文,异常路径可能漏关。
  - 建议:迁移放进单事务,成功提交后再 rename;或 rename 失败时记录告警。
  - 状态:2026-07-05 已完成:迁移写入使用单事务,提交后再归档 legacy JSON;归档失败会记录 `state_migrations=archive_pending` 并在下次状态初始化重试,不再静默跳过。

- ~~**[低] `complete_reminder` 等按“精确标题”匹配,可能批量误操作同名提醒**~~
  - 位置:`nudge/apple/reminders.py:456-495`(AppleScript 回退 `every reminder whose name is "..."` 全部置完成)、`delete_reminder` 同理(552-567,删除所有同名)。
  - 影响:EventKit 路径有 external_id/due_date 精确匹配,但 AppleScript 回退按标题批量改/删,存在误伤同名提醒风险。
  - 状态:2026-07-05 已完成:AppleScript fallback 改为先收集候选并计数,仅唯一匹配时 complete/delete;有 due_date 时用精确 due date/time 缩小匹配,同名多条或无法唯一定位时返回明确失败,不再批量操作。

- **[低] daemon `run` 循环用固定 `sleep_ms` 轮询队列,无事件唤醒**
  - 位置:`nudge/commands/daemon.py:1052-1061`。
  - 影响:空队列时固定睡眠,既有延迟又有空转;不是 bug,但可提升响应性/能耗。
  - 建议:可选指数退避或基于通知/文件监听唤醒。

- ~~**[低] 健康每日汇总累加字段缺少异常值/单位校验**~~
  - 位置:`nudge/health.py:60-105`(`_DailyAccumulator` 直接累加 steps/距离/能量等)。
  - 影响:多来源(Apple + 第三方 App)同日数据可能重复计数或单位不一致,导致汇总偏大;`state.py` 的 `_merge_*` 取 max 缓解了一部分,但解析阶段仍可能重复累加同一来源。
  - 建议:解析阶段按来源/样本去重或加合理上限校验;补充测试。
  - 状态:2026-07-05 已完成:Health XML 解析按稳定 record key 去重;steps/距离/能量/运动/站立/睡眠等每日累加字段跳过负值、明显异常值与未知单位;新增公开合成测试覆盖。

- ~~**[低] `skills/jsonlogic` 仍缺针对性单测**~~
  - 位置:`nudge/skills/jsonlogic.py`。
  - 背景:`brain._parse_json`、`apple/common.escape`、Health 解析已补回归测试;原“核心解析与 Apple 适配缺直接单测”条目已大幅降噪。
  - 影响:Skills 条件判断是计划模板适配的关键纯函数,缺少边界测试会增加后续 skill schema 扩展风险。
  - 建议:为 jsonlogic 常用操作符、缺失字段、类型不匹配、嵌套表达式补离线单测。
  - 状态:2026-07-05 已完成:新增 `tests/test_skills_jsonlogic.py`,覆盖常用操作符、缺失字段、类型不匹配、嵌套表达式、危险路径与 invalid missing 参数校验。

### 最严重(优先处理)

当前本小节只保留仍需要优先处理的未完成项;已完成的安全/迁移项移入下方“已完成记录”。

1. ~~**[低] 完成一个睡眠相关 action 会触发额外区间查询 + 逐条更新**~~:2026-07-05 已完成,同一连接/事务内批量查询与更新。
2. ~~**[低] 健康每日汇总累加字段缺少异常值/单位校验**~~:2026-07-05 已完成;Health XML 解析按稳定 record key 去重,每日累加字段跳过负值、明显异常值与未知单位,并补充合成测试。
3. ~~**[低] `complete_reminder` 等按“精确标题”匹配,可能批量误操作同名提醒**~~:2026-07-05 已完成;AppleScript fallback 仅唯一匹配时写入,同名多条失败。

#### 已完成记录

- ~~**[低] 健康每日汇总累加字段缺少异常值/单位校验**~~:2026-07-05 已完成 Health XML record 去重、每日累加字段异常值/单位校验与合成测试。
- ~~**[中] Health XML 解析无 XXE/实体膨胀防护**~~:2026-07-04 已完成 defusedxml 解析与 XML 大小上限防护。
- ~~**[中] `_migrate_from_json` 迁移与重命名非原子**~~:2026-07-05 已完成事务迁移、归档失败记录与重试。
- ~~**[中] MCP / agent 写入入口无身份认证**~~:2026-07-05 已完成可选本地 token auth。

## 产品与商业价值评审(2026-06-20:目标闭环/更优实现/商业价值/功能遗漏)

> 视角:对照仓库自己文档(README)宣称的目标做产品评审,不重复 2026-06-20 代码审查章节的 bug/安全/性能项。
> 仓库定位(以 README 为准):AGPL-3.0 开源、本地优先的 macOS CLI 底座,把结构化或自然语言计划转成 Apple 日历/提醒/备忘录/时钟动作;公开仓库只含运行时/CLI/Apple 适配/daemon/MCP 包装/安装脚本,不含个人数据(个人数据与 PRD 在私有仓库 nudge-private)。

### D1 目标实现与闭环(发现→安装→上手→贡献)

评级:**半闭环**。代码运行时层面完整可用,但作为"可被他人复用的开源框架"的采用闭环存在多处断点。

- 安装→上手:基本通。`scripts/bootstrap_mac.sh` 一键建 venv、写 config、装 CLI、自检,README Quick Start 与之对应,上手路径清晰。这是当前最完整的一环。
- 发现(断点):仓库无项目主页/徽章/截图/演示,README 仅 57 行;`pyproject.toml` 名为 `nudge-ai-life-coach` 但**未发布到 PyPI**,唯一安装方式是 git clone + 软链。外部用户难以"发现"并低成本试用。
- 上手(断点):README "Recommended Flow" 只覆盖约 7 条命令,但 CLI 实际注册了 **21 个子命令**(agent/mcp/schedule/habits/health/daily/review/skills/daemon/trainer/dogfood/failures/briefing/chat/db/docs/log/check-in/reminders/do/doctor)。绝大多数命令**没有任何面向用户的文档**,任务背景里提到的"命令参考/架构"文档在仓库中**并不存在**(无 `docs/` 目录)。用户只能靠 `--help` 自行摸索。
- 贡献(断点,最弱一环):**完全没有** `CONTRIBUTING`、`CODE_OF_CONDUCT`、`SECURITY.md`、`CHANGELOG`、`.github/`(无 issue/PR 模板、无 CI workflow)。`scripts/verify.sh` 存在且可用,但**没有 CI 在 PR 上自动跑**,外部贡献者无标准入口,维护者无法规模化接收贡献。
- 跨平台(结构性断点):核心价值绑定 Apple(AppleScript/EventKit/Shortcuts),**仅 macOS** 可用真实写入。非 Mac 用户连"试一下"都做不到,严重限制可复用人群。
- 闭环判断:运行时"能跑通"但"难被他人发现、难自学全部能力、难规范贡献",故评半闭环;补齐贡献/文档/分发即可升到"基本完整"。

### D2 更优实现(现状→建议→收益)

- 分发方式
  - 现状:只能 git clone + `install_cli.sh` 软链到 `~/.local/bin`,无 PyPI、无 Homebrew tap。
  - 建议:发布到 PyPI(`pip install` / `pipx install nudge-ai-life-coach`),并提供 Homebrew tap;Quick Start 增加一行 `pipx` 安装。
  - 收益:把"发现→试用"成本从"读脚本+克隆"降到一行命令,是采用率最直接的杠杆。
- 文档结构
  - 现状:单文件 57 行 README,21 命令仅 7 个被提到,无命令参考、无架构图、无配置项说明(`config.example.toml` 各字段无解释)。
  - 建议:新建 `docs/`,至少含命令参考(每个子命令一段:用途/示例/是否写 Apple)、架构概览(brain→json_contract→apple adapters→state 数据流)、配置参考、LLM provider 选择(qwen/ollama/anthropic/openai)指南。
  - 收益:把"靠 --help 逆向"变成可检索文档,显著降低上手与贡献门槛。
- 示例与插件机制
  - 现状:`nudge/skills/builtins/` 仅 3 个 YAML(deep-work / strength / deep-learning),既是能力也是唯一隐式示例;无 `examples/`,无"如何写自定义 skill"的说明。
  - 建议:新建 `examples/`(自然语言输入样例、自定义 skill YAML 模板、MCP 调用样例);为 skills schema 写一页作者指南(`nudge/skills/schema.py` 即契约,需文档化)。
  - 收益:skills 是该项目最具"框架可复用性"的扩展点,文档化后可让社区贡献 skill 而非改核心代码。
- 开源-私有切分
  - 现状:`.nudge-public-export` 声明"从私有仓库生成、已过隐私扫描",`.gitignore` 排除 config/db/zip,README "Private Data" 一节列了边界。切分**意图清晰且基本到位**。
  - 建议:补一段"公开仓库与私有数据的边界说明 + 公开导出流程"到 docs(不泄露 nudge-private 路径),并把隐私扫描脚本化/可复现,供二次开发者放心 fork。
  - 收益:增强外部 fork 者对"我自己的私有数据不会进公开仓库"的信任,这是个人助理类工具被采用的前提。
- CLI 入口体验
  - 现状:`NudgeGroup` 把未知首参当作 `do` 的消息,设计巧妙;但 README 未解释这一隐式行为。
  - 建议:文档明确"`nudge "自然语言"` 等价于 `nudge do`",并说明保留子命令名冲突时的行为。
  - 收益:减少新用户对"为什么裸文本也能跑"的困惑。

### D3 商业价值

评级:**低(纯开源直接商业价值低/接近无;但有社区价值与 open-core 潜在路径)**。

- 诚实评估:这是 AGPL-3.0、本地优先、单平台(macOS)、社区驱动、无任何收费/托管入口的个人生产力 CLI。直接商业变现路径几乎为零;AGPL 强 copyleft 还会劝退想闭源集成的商业方。
- 社区价值(真实存在):本地优先 + 自带 MCP 包装 + Apple 原生写入 + 自然语言→结构化动作的契约层,对"想要可审计、数据不出本机的 AI 助理"人群有吸引力,适合做口碑型开源项目积累 star/贡献者/信任。
- open-core / 双轨潜在路径(仅作战略参考,非当前建议落地):
  1. 开源保留 CLI/runtime/Apple 适配;闭源/订阅做"云同步、跨设备、团队/家庭共享计划、托管 LLM 网关";
  2. 把 skills 做成市场/模板生态,核心免费、精选 skill 包或教练内容付费;
  3. 面向开发者的"个人数据 MCP 服务"托管版(本地优先仍是卖点,托管解决可达性)。
  - 任一路径都需先解决跨平台与分发(见 D4),否则用户基数撑不起商业层。
- 当前阶段结论:不建议为"直接商业"投入;若要投入,先用开源把采用闭环做完整、把社区做起来,再评估 open-core,而非过早加商业模块。

### D4 功能遗漏与提升(按 价值×成本 标 P0/P1/P2)

聚焦"易被采用的开源工具"所缺的关键内容,与代码审查章节不重复(那里是 bug/安全/性能)。

- ~~**[P0] 缺贡献与社区基础设施**~~:无 `CONTRIBUTING` / `CODE_OF_CONDUCT` / `SECURITY.md` / `.github` issue+PR 模板 / CI。建议新增,并把 `scripts/verify.sh` 接入 GitHub Actions(macOS runner 跑 Apple 相关,Linux runner 跑纯逻辑测试)。价值高、成本低,是开源可持续的地基。
  - 状态:2026-07-04 已完成:新增 `CONTRIBUTING.md`、`SECURITY.md`、`CODE_OF_CONDUCT.md`、GitHub Actions verify workflow、issue/PR 模板。
- ~~**[P0] 缺命令参考文档**~~:21 个命令里大部分无文档。建议新建 `docs/commands.md`(或每命令一节),标注哪些会真实写 Apple、哪些只读。价值高、成本中。
  - 状态:2026-07-04 已完成:新增 `docs/commands.md`,覆盖主要 CLI 命令、Apple/SQLite 写入范围与 macOS 权限说明。
- **[P1] 缺一键可试用的分发渠道**:无 PyPI/Homebrew。建议先发 PyPI(已有 `pyproject.toml`,接近可发)。价值高、成本中。
  - 状态:2026-07-05 已完成 PyPI 发布准备:新增发布 checklist、离线 packaging 验证入口、README 安装路径区分与包内容检查;pyproject 补齐 `classifiers` 与 `[project.urls]`。
  - 本地预演已通过(2026-07-05):`scripts/verify.sh`(3.12)全绿、`twine check dist/*` PASSED、从本地 wheel 干净装入隔离 3.12 venv 验证 console script 与打包数据(builtins/swift)可用。
  - **仍待人工完成**:TestPyPI 预演上传(需维护者 token,`0.5.1` 若已占用则用 `0.5.1.post1`)→ 正式 PyPI 上传(独立 token)→ Homebrew tap。上传是不可逆外发,须维护者手动执行,见 `docs/releasing.md`。
- ~~**[P1] 缺架构与数据流文档**~~:`brain`/`json_contract`/`apple adapters`/`state`/`skills` 之间关系无说明,贡献者难快速理解。建议 `docs/architecture.md` + 一张数据流图。价值中高、成本中。
  - 状态:2026-07-05 已完成:新增 `docs/architecture.md`,覆盖 local-first runtime、自然语言/agent/MCP/daemon/Skills/Health/daily/review 数据流、SQLite/Apple adapter/安全边界与贡献者模块导航。
- ~~**[P1] 跨平台缺口**~~:核心写入仅 macOS。建议至少提供"非 Mac 上的 dry-run / 解析-only 模式"文档与可运行示例(纯逻辑路径已跨平台,verify.sh 在 Linux 也能跑测试),让非 Mac 用户能评估解析能力。价值高、成本中高(完整跨平台写入成本极高,先做"可评估"即可)。
  - 状态:2026-07-05 已完成:新增 `docs/non-macos.md`,说明非 macOS 环境可运行 docs audit、测试、JSON/YAML 示例解析、skills validate/dry-run、agent/MCP dry-run 与 LLM 配置后的自然语言 dry-run,并列出真实 Apple 写入不可用边界。
- ~~**[P1] 缺示例库**~~:无 `examples/`。建议补自然语言输入样例、自定义 skill 模板、MCP 客户端调用样例。价值中、成本低。
  - 状态:2026-07-05 阶段完成:新增 `examples/` 索引、自然语言 dry-run 样例、自定义 Skill YAML 模板、MCP JSON-RPC dry-run 样例和 agent apply dry-run 请求;后续若 schema/工具扩展,需同步更新示例。
- ~~**[P2] 缺 CHANGELOG / 版本发布说明**~~:`pyproject` 已到 0.5.1 但无变更记录。建议补 `CHANGELOG.md` 并在发版时维护。价值中、成本低。
  - 状态:2026-07-05 已完成:新增 `CHANGELOG.md`,从 0.5.1 起记录公开 runtime、文档、测试和安全边界变更;历史版本仅保留概览。
- ~~**[P2] 缺 LLM provider 选择指南**~~:`config.example.toml` 默认 qwen,提到 ollama 本地推理,但无"如何选 provider / 各自隐私与成本权衡"说明。建议 `docs/llm.md`。价值中、成本低。
  - 状态:2026-07-05 已完成:新增 `docs/llm.md`,覆盖 qwen/dashscope、openai、anthropic、deepseek、ollama/local 的隐私/成本/延迟/质量/离线权衡,并说明 fast/default/strong 模型分层和密钥安全配置。
- **[P2] 缺截图/演示/快速演示 GIF**:README 无任何可视化,降低"发现"转化。建议加一段终端录屏 GIF 或 asciinema。价值中、成本低。
- ~~**[P2] 配置项无文档**~~:`config.example.toml` 各字段(默认日历/列表、state.dir、apple backend=native/shortcuts)无解释。建议 `docs/configuration.md`。价值中、成本低。
  - 状态:2026-07-05 已完成:新增 `docs/configuration.md`,并补充 `config.example.toml` 的脱敏示例和注释;覆盖 `[general]`、`[state]`、`[llm]`/`[llm.models]`、Apple backend、`[family]`、`[user]`/`[user.fitness]`、`[calendars]`、`[reminders]`。

## 架构与产品审阅补充(2026-07-04:接线缺口/隐藏能力/商业闭环)

> 来源:全库架构梳理 + 21 个顶层命令逐一盘点(只读,含子代理并行勘查)。与 2026-06-20 两节不重复;有关联处做交叉引用。

### 已建成但未接线 / 未曝光(本次核心发现)

- ~~**[高] Skills 引擎完整建成但与主链路零集成**~~
  - 位置:`nudge/skills/`(schema/jsonlogic/patch/engine/dryrun 五模块 + 3 个内置 skill + `commands/skills.py` 9 个子命令)。
  - 事实:除 `commands/skills.py` 外,`do`/`agent`/`chat`/`brain`/`trainer` 没有任何一处 import 或调用 skills;`dry_run_skill` 只预览、不写 Apple、不落库。它是自成体系的孤岛。
  - 建议:设计"skill → plan 实例化 → actions 落库"的桥,优先让 `trainer` 跑在 skill 引擎之上(内置已有 `strength-basics-12w`)。这是差异化与 open-core 的核心资产,不接线则价值为零。
  - 状态:2026-07-04 已完成 runtime 接线(start/status/adapt + log --metric + dry-run reminder 类型),见 docs/superpowers/plans/2026-07-04-skills-runtime-wiring.md;剩余:trainer 统一(见下一条)。
- ~~**[中] `trainer` 与 `skills` 双轨计划机制重叠**~~
  - 位置:`nudge/brain.py`(`generate_workout_plan`,LLM 生成)vs `nudge/skills/dryrun.py`(确定性模板)。
  - 建议:统一为"skill 模板打底 + LLM 个性化微调",消除并行机制。
  - 状态:2026-07-04 已完成默认路径统一:`trainer plan/status` 默认走 `strength-basics-12w` Skill runtime,旧 LLM 周计划保留为 `trainer plan --legacy-llm`;剩余:评估是否删除旧 LLM planner 与 `trainer log` 自然语言解析。
- ~~**[中] `schedule` 命令是半成品**~~
  - 位置:`nudge/commands/schedule.py`。
  - 状态:2026-07-05 已完成阶段 1+2:支持从请求或 `--duration` 解析/指定最小时长,过滤本周空档;新增 `--json`;新增 `--book --slot N --title ...` 闭环创建 Calendar event,`--dry-run` 预览不写 Apple,真实写入需显式 slot/确认并记录 SQLite action。
- ~~**[中] 四个配置区块被代码读取但示例配置完全缺失**~~
  - 位置:`[family]`(`config.py:61/99/119`,家庭组路由)、`[user]`(`config.py:161`,trainer/schedule/habits 依赖)、`[calendars]`(`config.py:166`)、`[reminders]`(`config.py:199`,定义后几乎无消费方)。
  - 影响:家庭路由这一差异化功能对外部用户不可发现。与 2026-06-20 D4"[P2] 配置项无文档"相关,本条指出具体缺失区块;`config.example.toml` 补脱敏示例即可。
  - 状态:2026-07-05 已完成:公开示例已补 `[family]`、`[user]`/`[user.fitness]`、`[calendars]`、`[reminders]` 脱敏配置;配置参考文档说明真实 Apple 写入影响。
- **[低] launchd 双管理入口重叠**
  - 位置:`scripts/bootstrap_launchd.sh`(管 4 个 LaunchAgent)与 `nudge daemon launchd install`(只管 `com.nudge.agent`)各自生成/加载 plist。
  - 影响:两处安装同名 agent 可能状态不一致。建议收敛为单一入口(脚本调用 CLI 或反之)。
- ~~**[低] README 只覆盖约 1/3 能力(具体清单)**~~
  - 未提及:`chat`、`trainer`、`habits`、`health`、`schedule`、`briefing`、`failures`、`dogfood`、`skills` 全套、`db`、`reminders`、`check-in`、`daemon app`/`daemon launchd`,以及 MCP 的 `report_action_status`/`doctor_status`/`list_nudge_notes` 三个 tool;`nudge <裸文本>` 自动路由到 `do`(`cli.py:37`)的隐式行为也未说明。
  - 归属:落地时并入 2026-06-20 D4 的 [P0] 命令参考文档,本条作为具体清单。
  - 状态:2026-07-05 已完成:README 新增 Capability Map,覆盖自然语言/日程、reminders/log/check-in、health/habits/daily/review、skills/trainer、agent/MCP、daemon/db/docs/doctor,并说明 `nudge <text>` 自动路由到 `do`。

### 架构债务(补充 2026-06-20 代码审查,不重复)

- **[中] `agent.py` 复用 `do.py` 下划线私有函数,形成隐式紧耦合深链**
  - 位置:`nudge/commands/agent.py:21`(import `_action_schema_problems`/`execute_action`);依赖链 `mcp/daemon → agent → do → brain/apple/state`。
  - 建议:把两个函数提升为正式公共 API(如挪到独立 `actions_core` 模块),再动 `do.py` 重构。
- **[中] 三个超大模块职责过载**
  - `nudge/state.py` 1442 行(2026-07-05 复核,原 1277,仍在增长;动作/习惯/健康/队列/幂等键/daemon runs/legacy JSON 迁移 8 个领域一个文件)、`nudge/commands/daemon.py` 1142 行(队列循环+launchd+图形 app+告警)、`nudge/commands/do.py` 807 行(家庭路由逻辑未下沉到已有的 `family_routing.py`)。
  - 建议:按领域拆分;与 2026-06-20 性能①(连接复用)一起动 state 层最划算。
- **[低] 模块级可变全局状态非线程安全**
  - 位置:`brain._provider/_llm_config`、`state.STATE_DIR/DB_PATH`、`agent.STATE_DIR` 等,靠 `configure_*` 重绑定。
  - 影响:daemon 常驻 + 未来多配置场景有隐患;与"每次操作重连重建表"同根,宜一并修。
  - 具体 foot-gun(2026-07-05 复核):`trainer log`/`status`/`_legacy_llm_plan` 未调 `configure_state`,自定义 `--config`(非默认 state 目录)时读写默认库,check-in 落回"请用通用打卡"。默认配置不触发;是全局态设计的直接后果,修 `configure_state` 缺调即可临时止血,根治需消除 import 即读盘。

### 架构债务(补充 2026-07-05 四维度审阅,与上不重复)

> 来源:2026-07-04/05 六提交 + 未提交工作区的四维度并行只读审阅(安全/正确性/架构/打包)。仅登记架构与可发布性债务;发现的运行期 bug(MCP 非 ASCII token DoS、Health JSON 路径缺范围校验等)不在本节。

- ~~**[高·发布阻塞] pip 安装后默认 config/state 路径落进包安装目录(`site-packages`)**~~
  - 位置:`config.py:25` `PROJECT_ROOT = parents[1]` 为锚;`load_config` 默认找 `PROJECT_ROOT/config.toml`,`resolve_state_dir` 无 env/config 时回退 `PROJECT_ROOT/.nudge`;`state.py` 在 import 时即据此设 `DB_PATH`。
  - 影响:wheel 安装后、用户尚无 `config.toml` 时,SQLite 会写进 `site-packages/nudge/../.nudge`;`config.example.toml` 里的 `~/.local/share/nudge` 只在用户手建 config 后生效,默认值本身不符合可发布 runtime。与正在推进的 PyPI 发布(见"商业闭环缺口 1"/D4 P1)直接冲突,应作为发布前置。
  - 状态:2026-07-05 已完成:`resolve_state_dir` 无 env/config 时,存在源码树 `.nudge` 则沿用(向后兼容),否则默认 `$XDG_DATA_HOME/nudge`(回退 `~/.local/share/nudge`);`load_config` 默认搜索源码树 `config.toml` 后回退 `$XDG_CONFIG_HOME/nudge/config.toml`。新增 `tests/test_config.py` 两个回归(XDG 默认、存量 `.nudge` 兼容),完整 `scripts/verify.sh`(3.12)通过。
- **[中] 命令层私有函数互相 import,形成隐式耦合网(扩大 2026-07-04"agent 复用 do"一条)**
  - 位置:除已记的 `agent.py → do._action_schema_problems/execute_action` 外,`mcp.py:22`、`daemon.py:24`、`skills.py:14`(`do.execute_action`)、`trainer.py:11`(import 私有 `skills._materialize_actions`)均从兄弟命令模块取函数;`review.py:31`、`chat.py:86` 用函数体内延迟 import 规避 `briefing`/`do` 的循环依赖(import cycle 信号)。
  - 影响:`execute_action`/`_action_schema_problems`/`_materialize_actions`/`_rewrite_family_group_actions` 这些真正的执行/校验核心逻辑住在 Click 命令模块内;任何 `do.py`/`agent.py` 重构会波及 mcp/daemon/trainer/skills,单测难隔离。
  - 建议:抽 `nudge/actions_core.py`(或 `runtime/`)承载 execute_action、schema 校验、family 改写、materialize;命令模块只做参数解析与输出。这是其它拆分的前置项(与上面"三个超大模块"联动)。
- **[中] CLI JSON 序列化重复,`json_contract.py` 过度贫血**
  - 位置:`_error_to_json` 有 3 份(`do.py:362`/`agent.py:1017`/`mcp.py:571`,字段已开始 drift);`_action_to_json`(`do.py:442`/`agent.py:881`)、`_failure_to_json`(`do.py:472`/`agent.py:905`)、`_scheduled_at`/`_summary`/target 序列化均 do 与 agent 各一份近似副本;而 `nudge/json_contract.py` 仅 11 行(只有 `versioned_payload`)。
  - 建议:把 action/target/failure/error 的 JSON 序列化统一进 `json_contract.py` 作单一对外契约源。可独立交付、低风险,建议优先。
- **[中] trainer 双 legacy 路径长期技术债(与本文件 2026-07-04 trainer 统一条的"剩余项"同源)**
  - 位置:`trainer.py` `_legacy_llm_plan`(`--legacy-llm`)、`_legacy_workout_status`(status 回退查旧 `weekly_workout`)、`trainer log` 命中 Skill 实例即提示改用 `nudge log done`(半废弃)。
  - 建议:定移除里程碑——确认 legacy `weekly_workout` 无存量数据后,删 `_legacy_*` 与其对 `brain.generate_workout_plan`/`parse_workout_log` 的依赖,trainer 收敛为 Skill runtime 薄壳。
- **[低] `errors.py` `render()` 带写日志副作用**
  - 位置:`errors.py:22`,`ErrorReport.render()` 内部调 `log_error_report(...)`;"结构体渲染成字符串"这个纯操作产生落盘副作用,每 render 一次落一条 error 日志,测试/预览难以无副作用格式化。建议把日志移到实际"发生错误并上报"的调用点。
- **[低] `requirements.txt` 混入测试依赖 `pytest`**
  - 建议:运行时/测试依赖分离,`pytest` 移到 `pyproject.toml` 的 `[project.optional-dependencies].test`,保持"纯运行时依赖"清爽。

### 商业闭环缺口(按漏斗排序,补充 2026-06-20 D3)

1. **第一优先:可发现、可试用**——PyPI/Homebrew 分发、截图/演示、非 Mac 的 dry-run 评估路径(与 D4 P1 重叠;提级理由:用户基数为零时其余环节全部空转)。
2. ~~**第二优先:skills 接线激活**~~——2026-07-04 已完成 Skills runtime 接线与 trainer 默认统一到 Skill runtime;后续仅保留 skill 作者生态/测试等增量。
3. ~~**前提项:MCP 调用方认证**~~——2026-07-05 已完成可选本地 token auth。
4. **留存基础**:正式 PyPI/Homebrew 发布仍未完成;issue 模板/CI 已完成。

## 运行期 bug 与正确性(2026-07-05 四维度审阅)

> 来源:同 2026-07-05 架构债务小节的四维度只读审阅(安全/正确性/架构/打包)。本节只列可复现的运行期缺陷,与架构债务分开。落地前先写回归测试再修(项目 TDD 约定),验证入口 `scripts/verify.sh`(3.12 `.venv`)。

- ~~**[中·已复核·建议发布前修] 非 ASCII `auth_token` 打崩 MCP 长驻服务(DoS)**~~
  - 位置:`nudge/commands/agent.py:405` `hmac.compare_digest(provided, expected)` 两侧为 `str`,`provided` 来自请求 JSON 完全可控;Python `compare_digest` 对含非 ASCII 的 `str` 抛 `TypeError`。`nudge/commands/mcp.py:57` 的 `for raw_line in sys.stdin` 主循环无 try/except(`_handle_line` 的 try 只包 `json.loads`),异常冒泡打死进程。
  - 触发:`[security.local_auth].enabled=true` 时,一条 `{"auth_token":"café",...}` 的 tools/call(无需正确 token)即崩服务,后续全部请求失效——安全特性自身引入 DoS。
  - 状态:2026-07-05 已完成:`check_local_auth` 改按 bytes `compare_digest`(仍恒定时间);`_handle_line` 对 `_handle_message` 加每请求异常隔离,返回 JSON-RPC internal error(-32603)不中断服务。新增 `tests/test_local_auth.py` 两个回归(非 ASCII token 拒绝不崩、单请求异常不打死循环),完整 `scripts/verify.sh`(3.12)通过。
- **[低] 确认密钥文件崩溃残留空文件 → 空 HMAC 密钥**
  - 位置:`agent.py` `_confirmation_secret`(`O_CREAT|O_EXCL`,0o600)。创建成功、`write` 之前进程被杀会残留空文件;后续读到空串直接以 `b""` 当 HMAC 密钥,dry-run→apply 确认 token 可离线复算。
  - 定级:本地信任模型下能读该文件者本有等价能力,故低;仍建议修。
  - 修:读取后校验非空,为空视同缺失并重建;或先写临时文件再 `os.rename` 原子替换。
- **[低] Health JSON 导入路径 weight/body_fat 无范围校验,与 XML 路径不一致**
  - 位置:`health.py` JSON 体重 277-279、体脂 290-292 无 `_valid_range`;XML 路径体重 427(1.0–500.0)、体脂 434(0.0–100.0)有。
  - 影响:异常值(0/99999/体脂>100)经 JSON 导入原样写入 `health_daily_summary`,同值经 XML 会被丢弃;数据质量不一致,不崩溃。
  - 修:JSON 路径复用同阈值 `_valid_range`。
- **[低] dryrun `preferred_days` 数量 < `sessions_per_week` 时生成同日同时段重叠动作**
  - 位置:`skills/dryrun.py:97` `preferred_days[slot % len(preferred_days)]` + 99-102 统一 `preferred_time`。
  - 触发:显式配置 `preferred_days=["monday"]` 且 `sessions_per_week=3` → 3 个 session 全落周一同一时刻,materialize 出 3 个起止相同的事件/提醒;默认回退分支不触发。
  - 修:`sessions_per_week > len(preferred_days)` 时同日多 session 错开时段,或校验层拒绝该组合。
- **[信息·行为变化,非 bug] `complete_reminder` 改精确 `due_date` 匹配,漂移时合规完成可能失败**
  - 位置:`commands/reminders.py:610` 传 `due_date=scheduled_at`;`apple/reminders.py:489` `if due date of r = targetDueDate` 精确等值。
  - 说明:本次"拒绝仅按标题模糊批量匹配"安全收紧的预期副作用——用户在 Apple 端改过到期时间、或 `scheduled_at` 与实际 due date 分钟级不一致时,两条路径都可能匹配不到而报错。列此仅供回归观察 check-in 完成成功率,非缺陷。
- 另:`trainer --config` 读写错库(非默认 state 目录时)是同批审阅发现的正确性 bug,已归档在架构债务"模块级可变全局"条下(全局态设计的直接后果),不在此重列。
