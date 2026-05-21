# Nudge Skill Spec

> 版本：v0.1 草案  
> 状态：v0.1 静态验证器和确定性规则执行器已实现；Marketplace、创作者后台和真实订阅流程仍属后续阶段。

Skill 是 Nudge 的“可订阅计划模板”：创作者把自己的方法论写成结构化模板，用户完成测评后，Nudge 根据用户情况生成具体 action，并进入日历、提醒、打卡、复盘、调整的闭环。

本文回答 TODO 中的关键问题：**个性化规则是 AI 解释还是代码执行？**

## 设计结论

**结论：Skill 不执行任意代码。**

Nudge 采用“声明式 Skill + 确定性解释器 + AI 生成候选计划 + 代码校验”的混合模型：

1. 创作者提交 YAML Skill，不提交 Python/JavaScript/Shell。
2. 个性化规则使用受限 DSL 表达，由确定性解释器执行。
3. AI 可以生成草稿和解释规则，也可以把 Skill、测评结果和历史数据转成候选计划。
4. AI 不能绕过规则；最终 action 必须通过 schema、规则、时间、频率和安全校验。
5. 所有真实写入前都支持 dry-run，便于用户和测试先预览。

换句话说：

| 环节 | 谁负责 | 是否确定性 | 说明 |
|------|--------|------------|------|
| Skill 结构校验 | 代码 | 是 | 校验字段、类型、版本、必填项 |
| 测评答案归一化 | 代码 | 是 | 把用户答案映射到 `assessment.*` |
| 个性化规则匹配 | 确定性解释器 | 是 | 使用 JSONLogic 子集，不用 `eval` |
| 计划候选生成 | AI | 否 | 负责自然语言、排期建议和教练语气 |
| 候选计划校验 | 代码 | 是 | clamp 频率/时长/强度，禁止越界 |
| 写入日历/提醒 | 代码 | 是 | 走 Nudge 已有 Apple/未来 CalDAV 集成 |

## v0.1 本机实现

当前仓库已经提供本机只读 CLI，用于验证和执行 Skill 中的确定性规则：

```bash
nudge skills list
nudge skills show strength-basics-12w

nudge skills validate path/to/skill.yaml
nudge skills validate path/to/skill.yaml --json
nudge skills validate strength-basics-12w

nudge skills apply path/to/skill.yaml --context context.json
nudge skills apply path/to/skill.yaml --context context.json --json
nudge skills apply strength-basics-12w --context context.json --json

nudge skills dry-run path/to/skill.yaml --context context.json
nudge skills dry-run path/to/skill.yaml --context context.json --weeks 1 --json
nudge skills dry-run strength-basics-12w --context context.json --weeks 1 --json
```

- `list/show`：查看包内内置 Skill 样例。当前内置 `strength-basics-12w`、`deep-learning-sprint-4w`、`deep-work-weekly-rhythm`，分别覆盖训练、学习和工作效率。
- `validate`：加载 YAML/JSON，检查 v0.1 必填字段、JSONLogic 操作符白名单、patch op 白名单、危险 path 和代码执行字段。
- `apply`：读取 context JSON，依次执行命中的 `personalization` 和 `adaptation` 规则，输出变更后的 Skill/template。
- `dry-run`：在 `apply` 的基础上，从 `plan_template.phases[].sessions[]` 生成候选 Calendar action 预览；默认预览第 1 周。
- 这些命令都不会调用 LLM，不会写入 Apple Calendar / Reminders，也不会访问文件系统中 Skill 文件、内置样例和 context 之外的数据。

## v0.1 YAML 结构

v0.1 目标是先定义能覆盖“训练、学习、工作效率”三类 Skill 的最小公共格式。

```yaml
schema_version: "0.1"
kind: "skill"

metadata:
  id: "strength-basics-12w"
  title: "12 周力量基础"
  version: "1.0.0"
  creator: "张教练"
  category: "fitness"          # fitness / study / work / lifestyle / family
  language: "zh-CN"
  description: "给零基础用户的 12 周力量训练入门计划"
  license: "creator-owned"

audience:
  goals:
    - "建立每周稳定训练习惯"
    - "掌握基础动作模式"
  prerequisites:
    - "无严重伤病"
  contraindications:
    - "急性腰伤"
    - "医生明确禁止力量训练"

assessment:
  - id: "current_frequency"
    question: "你目前每周训练几次？"
    type: "single_choice"
    required: true
    options:
      - id: "never"
        label: "从不"
      - id: "one_two"
        label: "1-2 次/周"
      - id: "three_plus"
        label: "3 次以上/周"
  - id: "injuries"
    question: "有哪些需要避开的伤病？"
    type: "multi_choice"
    required: false
    options:
      - id: "none"
        label: "无"
      - id: "lower_back"
        label: "腰椎"
      - id: "knee"
        label: "膝盖"

personalization:
  - id: "beginner_frequency"
    when:
      "==":
        - {var: "assessment.current_frequency"}
        - "never"
    apply:
      - op: "set"
        path: "plan.defaults.sessions_per_week"
        value: 3
      - op: "tag"
        value: "beginner"

  - id: "lower_back_safe_substitution"
    when:
      in:
        - "lower_back"
        - {var: "assessment.injuries"}
    apply:
      - op: "replace"
        path: "plan_template.phases[].sessions[].exercises[]"
        where:
          "==":
            - {var: "item.name"}
            - "硬拉"
        value:
          name: "哑铃罗马尼亚硬拉"
          note: "降低腰椎负担，保持髋铰链训练"

plan_template:
  timezone_policy: "user_local"
  defaults:
    sessions_per_week: 4
    session_minutes: 45
    preferred_days: ["Tuesday", "Thursday", "Saturday", "Sunday"]
  phases:
    - id: "foundation"
      title: "基础期"
      weeks: 4
      sessions:
        - id: "upper_a"
          focus: "upper_body"
          duration_minutes: 45
          exercises:
            - name: "哑铃推举"
              sets: 4
              reps: 12
              rest_seconds: 60
        - id: "lower_a"
          focus: "lower_body"
          duration_minutes: 45
          exercises:
            - name: "高脚杯深蹲"
              sets: 4
              reps: 10
              rest_seconds: 90

tracking:
  metrics:
    - id: "session_completed"
      type: "boolean"
      prompt: "这次训练完成了吗？"
    - id: "subjective_effort"
      type: "scale"
      min: 1
      max: 10
      prompt: "主观强度 1-10 分是多少？"

adaptation:
  - id: "too_hard_deload"
    trigger:
      ">":
        - {var: "history.effort_avg_7d"}
        - 8
    apply:
      - op: "insert"
        path: "plan.weeks"
        position: "next"
        value:
          kind: "deload"
          intensity_multiplier: 0.75
      - op: "clamp"
        path: "plan.defaults.session_minutes"
        max: 40

safety:
  requires_medical_disclaimer: true
  max_sessions_per_week: 6
  max_session_minutes: 90
  forbidden_actions:
    - "在疼痛状态下继续训练"
```

## 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `schema_version` | 是 | 当前为 `0.1`；后续破坏性变更必须升级 |
| `kind` | 是 | 固定为 `skill` |
| `metadata` | 是 | 展示、搜索、版本、创作者和分类信息 |
| `audience` | 是 | 目标、适用前提和禁忌，用于上架审核和安全提示 |
| `assessment` | 是 | 用户订阅时的摸底测评 |
| `personalization` | 否 | 根据测评和历史数据修改模板 |
| `plan_template` | 是 | 可生成 action 的计划结构 |
| `tracking` | 是 | 执行后要追踪的指标 |
| `adaptation` | 否 | 根据执行数据自动调整计划 |
| `safety` | 否 | 频率、时长、禁忌、免责声明等硬约束 |

## 个性化规则 DSL

v0.1 使用 **JSONLogic 子集** 作为条件表达式，不使用 Python `eval`、JavaScript `Function` 或 shell。

### 可读取的数据

规则只能读取白名单上下文：

- `assessment.*`：用户测评答案。
- `profile.*`：用户基础信息，如时区、可用时间偏好。
- `history.*`：聚合后的执行历史，如完成率、连续跳过次数、近 7 天主观强度。
- `plan.*` / `plan_template.*`：当前候选计划。
- `item.*`：在 `replace` / `remove` 等列表操作中指向当前元素。

规则不能读取密钥、环境变量、文件系统、浏览器 cookie、邮件正文或未授权的个人数据。

### 条件操作符

允许的 JSONLogic 操作符：

- 比较：`==`、`!=`、`>`、`>=`、`<`、`<=`
- 逻辑：`and`、`or`、`!`
- 集合：`in`
- 取值：`var`
- 默认值：`missing`、`missing_some`

禁止的能力：

- 任意代码执行。
- 正则灾难性回溯。
- 网络请求。
- 文件读写。
- 动态导入。

### apply 操作

`apply` 是确定性解释器执行的 patch 列表。

| op | 作用 | 示例 |
|----|------|------|
| `set` | 设置 path 的值 | 把 `sessions_per_week` 设为 3 |
| `add` | 数值加法 | 每周学习时长 +2 小时 |
| `multiply` | 数值倍率 | 强度乘以 0.8 |
| `clamp` | 限制上下界 | session 不超过 90 分钟 |
| `replace` | 替换列表元素 | 腰伤用户把硬拉替换为替代动作 |
| `remove` | 删除列表元素 | 删除不适合用户的训练 |
| `insert` | 插入新元素 | 插入 deload 周或复习周 |
| `tag` | 给生成上下文打标签 | 标记为 `beginner` |
| `validate` | 添加必须满足的断言 | 确认每周至少 1 天休息 |

所有 `path` 使用受限点路径语法，不允许 `..`、绝对路径、文件路径或对象原型字段。

## 运行流程

Skill Engine 的标准流程：

1. **Load**：读取 YAML，确认 `schema_version` 和 `kind`。
2. **Validate**：根据 schema 校验字段、类型、范围和安全约束。
3. **Assess**：收集用户测评答案，并标准化为 `assessment.*`。
4. **Personalize**：确定性解释器执行 `personalization`，得到个性化模板。
5. **Generate**：AI 读取个性化模板、用户日历空闲、历史执行数据，生成候选计划。
6. **Validate again**：代码执行 `safety`、`tracking`、`adaptation` 和 action schema 校验。
7. **Dry-run**：`nudge skills dry-run` 展示将写入的候选 Calendar action，不产生副作用；v0.1 确定性预览只读取 `plan_template.phases[].sessions[]`、`plan_template.defaults` 和 `context.profile.*`。
8. **Commit**：用户确认后写入日历、提醒事项和 Nudge state。
9. **Track**：按 `tracking.metrics` 收集完成情况。
10. **Adapt**：周期性执行 `adaptation` 规则，并让用户确认重要调整。

## 安全边界

Skill 是内容，不是插件。v0.1 明确禁止：

- 不能执行任意代码。
- 不能调用 shell。
- 不能读取密钥、token、OAuth 文件、环境变量或本机备份目录。
- 不能直接访问文件系统。
- 不能发网络请求或调用外部 API。
- 不能绕过用户确认真实写入日历、提醒事项或第三方应用。
- 不能隐藏医疗、财务、法律等高风险建议的免责声明。

创作者可以表达“该怎么计划”，但不能获得“在用户机器上执行代码”的能力。

## 示例

### 学习类 Skill：CPA 90 天冲刺

```yaml
schema_version: "0.1"
kind: "skill"

metadata:
  id: "cpa-accounting-90d"
  title: "CPA 会计 90 天冲刺"
  version: "1.0.0"
  creator: "李老师"
  category: "study"
  language: "zh-CN"

assessment:
  - id: "daily_available_minutes"
    question: "你每天可稳定学习多久？"
    type: "number"
    required: true
    min: 30
    max: 240
  - id: "baseline"
    question: "当前基础？"
    type: "single_choice"
    options:
      - id: "zero"
        label: "零基础"
      - id: "learned_once"
        label: "学过一轮"

personalization:
  - id: "zero_baseline_foundation"
    when:
      "==":
        - {var: "assessment.baseline"}
        - "zero"
    apply:
      - op: "set"
        path: "plan_template.phases[0].weeks"
        value: 4
      - op: "clamp"
        path: "plan.defaults.daily_minutes"
        max: 90
      - op: "tag"
        value: "needs_foundation"

plan_template:
  defaults:
    daily_minutes: 120
    rest_days_per_week: 1
  phases:
    - id: "foundation"
      title: "基础概念"
      weeks: 3
      sessions:
        - id: "lesson"
          focus: "教材 + 例题"
          duration_minutes: 60
        - id: "review"
          focus: "错题复盘"
          duration_minutes: 30

tracking:
  metrics:
    - id: "study_completed"
      type: "boolean"
    - id: "practice_accuracy"
      type: "percentage"

adaptation:
  - id: "accuracy_low_add_review"
    trigger:
      "<":
        - {var: "history.practice_accuracy_7d"}
        - 0.6
    apply:
      - op: "insert"
        path: "plan.next_week.sessions"
        value:
          id: "extra_review"
          focus: "错题专项复盘"
          duration_minutes: 45
```

## 后续实现计划

1. [x] 新增 `nudge/skills/schema.py`：定义 v0.1 schema 和验证错误。
2. [x] 新增 `nudge/skills/jsonlogic.py`：实现 JSONLogic 安全子集。
3. [x] 新增 `nudge/skills/patch.py`：实现 `set`、`clamp`、`replace`、`insert`、`validate` 等操作。
4. [x] 新增 `nudge skills validate <file>`：本地校验 Skill YAML/JSON。
5. [x] 新增 `nudge skills apply <file> --context context.json`：执行确定性 personalization / adaptation 规则并输出结果。
6. [x] 新增 `nudge skills dry-run <file>`：结合 mock profile / assessment 预览将要生成的候选 action，但仍不写入 Apple 应用。v0.1 不读取 Calendar，不调用 LLM；真实空闲时间排期是后续增强。
7. [x] 在 Phase 3 之前，用 2-3 个内置免费 Skill 验证格式是否足够表达真实计划：已内置训练、学习、工作效率 3 个样例，并支持 `nudge skills list/show`。

## 非目标

v0.1 暂不做：

- 完整 Marketplace API。
- 创作者收费、结算和审核后台。
- 第三方插件执行环境。
- 任意编程语言扩展。
- 自动发布到云端。

这些能力必须等 Skill Spec、验证器和安全模型稳定后再推进。
