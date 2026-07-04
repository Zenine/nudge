# Skills 引擎接线主链路(runtime 三步)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已建成但孤立的 Skills 引擎接进 nudge 主链路:skill 实例落库(复用 plans/actions 表)、assessment 交互式评估、tracking 用真实打卡数据驱动 adaptation,并让 dry-run 支持 reminder 动作类型。

**Architecture:** 新增 `nudge/skills/runtime.py` 作为实例层(纯确定性、无 Apple 依赖、离线可测),复用 `state.create_plan/log_action`(实例 = `plans` 行,`config` JSON 标 `kind=skill_instance`;动作 = `actions` 行带 `plan_id`)。命令层在 `commands/skills.py` 新增 `start`/`status`/`adapt` 三个子命令,Apple 写入复用 `commands/do.execute_action` + `resolve_apple_backends`(与 `agent.py` 相同的既有复用模式)。`log`/`check-in` 增加 `--metric key=value` 直接打卡指标(`parse` 路径已有 metrics 管道,补齐直接路径)。

**Tech Stack:** Python ≥3.12、click、PyYAML、SQLite(全部已有,不新增依赖)。

## Global Constraints

- Python ≥ 3.12(`pyproject.toml` `requires-python = ">=3.12"`);依赖只允许现有四个:`anthropic`、`click`、`openai`、`PyYAML`,不新增。
- 所有新测试必须 public-safe(不含个人数据)、离线可跑(不调 LLM、不调 macOS/Apple,Apple 后端用 fake)、在 Linux 上可通过。
- 测试里操作 SQLite 前必须把 `nudge.state` 的 `STATE_DIR`/`DB_PATH`/`LEGACY_JSON` monkeypatch 到 `tmp_path`(既有模式,见 `tests/test_state.py:12-14`),防止污染真实状态库。
- 不改 Skill Spec `schema_version`(保持 `"0.1"`,本计划全部是向后兼容扩展;`plan_template` 内部字段 schema 本就不校验)。
- 用户可见文案沿用仓库现有风格:中文说明 + `PASS`/`DRY-RUN`/`WARN` 前缀;机器输出一律走 `versioned_payload`。
- 完整验证入口:`scripts/verify.sh`(pytest + compileall + CLI --help smoke + docs audit)。
- **提交边界(本机全局规则):`git commit` 需用户在执行会话中明确授权。执行者开工前先问一次"是否授权按任务逐个提交";未授权则跳过所有 Commit 步骤,任务末尾只汇报 `git status`。** 获授权后 commit message 末尾带 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 范围外(明确不做,防扩散):trainer 与 skills 的统一(后续单独计划)、skill 实例的完成/放弃生命周期命令、multi-instance 同 skill 并行去重、`schedule` 命令补全。

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `nudge/skills/dryrun.py` | 修改 | 候选动作支持 `reminder` 类型(session 级 `action_type` 字段) |
| `nudge/state.py` | 修改 | 新增 `get_plan`、`update_plan_config` 两个小助手(沿用 `_db()` 模式) |
| `nudge/skills/runtime.py` | 新建 | 实例层:实例配置构建/创建/列表/查询、进度游标、tracking context 构建;**不 import apple/click** |
| `nudge/commands/log.py` | 修改 | `log`/`check-in` 增加 `--metric key=value`(repeatable) |
| `nudge/commands/skills.py` | 修改 | 新增 `start`/`status`/`adapt` 子命令 + `_run_assessment` 交互 + `_materialize_actions` 写入助手 |
| `tests/test_skills_dryrun.py` | 新建 | dry-run reminder 类型 |
| `tests/test_state_plans.py` | 新建 | plan 助手 |
| `tests/test_skills_runtime.py` | 新建 | 实例层 + tracking context |
| `tests/test_commands_log_metric.py` | 新建 | `--metric` 打卡 |
| `tests/test_commands_skills_runtime.py` | 新建 | `start`/`status`/`adapt` 命令(fake Apple 后端) |
| `README.md`、`TODO.md` | 修改 | 收尾文档(Task 9) |

---

### Task 1: dry-run 支持 reminder 动作类型

**Files:**
- Modify: `nudge/skills/dryrun.py`
- Test: `tests/test_skills_dryrun.py`

**Interfaces:**
- Consumes: 无(纯函数模块)。
- Produces: `dry_run_skill(skill, context, weeks)` 的候选动作除 `type: "calendar_event"` 外新增 `type: "reminder"`(session 里写 `action_type: reminder`,或 `plan_template.defaults.action_type` 全局默认);reminder 候选额外带 `name`(= summary)与 `due_date`(= start,`"%Y-%m-%d %H:%M"`),与 `commands/do.execute_action` 的 reminder 契约对齐。不支持的 `action_type` 抛 `ValueError`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_skills_dryrun.py`:

```python
"""Public-safe tests for deterministic Skill dry-run action generation."""

import pytest

from nudge.skills.dryrun import dry_run_skill


def _minimal_skill(session_extra: dict | None = None, defaults_extra: dict | None = None) -> dict:
    session = {"id": "s1", "title": "测试会话", "duration_minutes": 30}
    session.update(session_extra or {})
    defaults = {
        "sessions_per_week": 1,
        "preferred_days": ["Monday"],
        "preferred_time": "08:00",
    }
    defaults.update(defaults_extra or {})
    return {
        "schema_version": "0.1",
        "kind": "skill",
        "metadata": {
            "id": "test-skill",
            "title": "测试 Skill",
            "version": "1.0.0",
            "creator": "tests",
            "category": "test",
        },
        "audience": {"goals": ["test"]},
        "assessment": [{"id": "q1", "question": "q?", "type": "boolean"}],
        "plan_template": {
            "defaults": defaults,
            "phases": [{"id": "p1", "title": "阶段一", "weeks": 1, "sessions": [session]}],
        },
        "tracking": {"metrics": [{"id": "session_completed", "type": "boolean"}]},
    }


_CONTEXT = {"profile": {"start_date": "2026-07-06"}}


def test_default_action_type_is_calendar_event():
    result = dry_run_skill(_minimal_skill(), _CONTEXT, weeks=1)
    assert [a["type"] for a in result.actions] == ["calendar_event"]


def test_session_action_type_reminder_emits_do_compatible_reminder():
    result = dry_run_skill(_minimal_skill({"action_type": "reminder"}), _CONTEXT, weeks=1)
    action = result.actions[0]
    assert action["type"] == "reminder"
    assert action["name"] == action["summary"]
    assert action["due_date"] == "2026-07-06 08:00"
    assert action["start"] == "2026-07-06 08:00"


def test_defaults_action_type_applies_to_all_sessions():
    result = dry_run_skill(
        _minimal_skill(defaults_extra={"action_type": "reminder"}), _CONTEXT, weeks=1
    )
    assert result.actions[0]["type"] == "reminder"


def test_unsupported_action_type_raises():
    with pytest.raises(ValueError, match="unsupported plan_template action_type"):
        dry_run_skill(_minimal_skill({"action_type": "note"}), _CONTEXT, weeks=1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_skills_dryrun.py -v`(无 `.venv` 时用 `python3 -m pytest`)
Expected: `test_session_action_type_reminder_emits_do_compatible_reminder`、`test_defaults_action_type_applies_to_all_sessions`、`test_unsupported_action_type_raises` FAIL(动作里没有 `name`/`due_date`,不支持类型也不报错);第一个用例应 PASS(基线行为)。

- [ ] **Step 3: 最小实现**

在 `nudge/skills/dryrun.py` 模块顶部常量区(`_DAY_INDEX` 之后)加:

```python
_SUPPORTED_ACTION_TYPES = {"calendar_event", "reminder"}
```

把 `_generate_actions` 中 `actions.append({...})` 一段(`dryrun.py:103-117`)替换为:

```python
            action_type = str(
                session.get("action_type") or defaults.get("action_type") or "calendar_event"
            )
            if action_type not in _SUPPORTED_ACTION_TYPES:
                raise ValueError(f"unsupported plan_template action_type: {action_type}")
            summary = _summary(metadata, session)
            action = {
                "type": action_type,
                "source": "skill_dry_run",
                "skill_id": metadata.get("id", "unknown"),
                "skill_title": metadata.get("title", "Untitled Skill"),
                "week": week,
                "phase_id": phase.get("id"),
                "phase_title": phase.get("title"),
                "session_id": session.get("id"),
                "summary": summary,
                "scheduled_date": scheduled_date.isoformat(),
                "start": start_dt.strftime("%Y-%m-%d %H:%M"),
                "end": end_dt.strftime("%Y-%m-%d %H:%M"),
                "duration_minutes": duration,
            }
            if action_type == "reminder":
                action["name"] = summary
                action["due_date"] = action["start"]
            actions.append(action)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_skills_dryrun.py -v`
Expected: 4 passed。

- [ ] **Step 5: Commit(需已获用户授权,见 Global Constraints)**

```bash
git add nudge/skills/dryrun.py tests/test_skills_dryrun.py
git commit -m "feat(skills): dry-run 候选动作支持 reminder 类型

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: state 层 plan 助手

**Files:**
- Modify: `nudge/state.py`(插在 `get_plans` 之后,`state.py:555` 附近)
- Test: `tests/test_state_plans.py`

**Interfaces:**
- Consumes: `state._db()`、既有 `plans` 表(无表结构变更)。
- Produces: `get_plan(plan_id: str) -> dict | None`;`update_plan_config(plan_id: str, config: dict) -> None`(整体替换 `plans.config` JSON)。Task 3 的 runtime 层依赖这两个函数。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_state_plans.py`:

```python
"""Public-safe tests for plan helper functions in the state layer."""

import json


def _isolate_state(monkeypatch, tmp_path):
    import nudge.state as state

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")
    return state


def test_get_plan_returns_row_or_none(monkeypatch, tmp_path):
    state = _isolate_state(monkeypatch, tmp_path)
    plan_id = state.create_plan("测试目标", config={"kind": "skill_instance"})

    plan = state.get_plan(plan_id)
    assert plan is not None
    assert plan["goal"] == "测试目标"
    assert json.loads(plan["config"])["kind"] == "skill_instance"

    assert state.get_plan("missing") is None
    assert state.get_plan("") is None


def test_update_plan_config_replaces_config_json(monkeypatch, tmp_path):
    state = _isolate_state(monkeypatch, tmp_path)
    plan_id = state.create_plan("测试目标", config={"week": 1})

    state.update_plan_config(plan_id, {"week": 2, "extra": "值"})

    stored = json.loads(state.get_plan(plan_id)["config"])
    assert stored == {"week": 2, "extra": "值"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_state_plans.py -v`
Expected: FAIL,`AttributeError: module 'nudge.state' has no attribute 'get_plan'`。

- [ ] **Step 3: 最小实现**

在 `nudge/state.py` 的 `get_plans` 函数后追加:

```python
def get_plan(plan_id: str) -> dict | None:
    """Return one plan by id."""
    if not plan_id:
        return None
    with _db() as conn:
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return dict(row) if row else None


def update_plan_config(plan_id: str, config: dict) -> None:
    """Replace one plan's config JSON."""
    config_json = json.dumps(config, ensure_ascii=False)
    with _db() as conn:
        conn.execute("UPDATE plans SET config = ? WHERE id = ?", (config_json, plan_id))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_state_plans.py tests/test_state.py -v`
Expected: 3 passed(含既有 state 竞态用例不回归)。

- [ ] **Step 5: Commit(需已获用户授权)**

```bash
git add nudge/state.py tests/test_state_plans.py
git commit -m "feat(state): 增加 get_plan / update_plan_config 助手

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: skills runtime 实例层

**Files:**
- Create: `nudge/skills/runtime.py`
- Test: `tests/test_skills_runtime.py`

**Interfaces:**
- Consumes: `nudge.state` 的 `create_plan(goal, config)`、`get_plan(plan_id)`、`get_plans(status)`、`update_plan_config(plan_id, config)`、`get_actions(plan_id=...)`(Task 2 产物 + 既有函数)。
- Produces(Task 6-8 命令层依赖,签名固定):
  - `SKILL_INSTANCE_KIND = "skill_instance"`
  - `create_skill_instance(skill: dict, context: dict, *, start_date: str, weeks_total: int | None, materialized_through_week: int, personalization_applied: list[str]) -> str`(返回 plan_id)
  - `list_skill_instances(status: str = "active") -> list[dict]`
  - `get_skill_instance(plan_id: str) -> dict | None`(实例 dict 含 `plan_id`/`goal`/`status`/`created_at` + config 全部字段)
  - `record_materialized_week(plan_id: str, week: int) -> None`(游标只增不减;实例不存在抛 `ValueError`)
  - `skill_weeks_total(skill: dict) -> int | None`(各 phase `weeks` 求和,0 视为 None)
  - `numeric_metric_ids(skill: dict) -> list[str]`(`tracking.metrics` 里 `type == "number"` 的 id)

- [ ] **Step 1: 写失败测试**

创建 `tests/test_skills_runtime.py`(本任务先写实例层部分;Task 4 再往同文件追加 tracking 用例):

```python
"""Public-safe tests for the Skill instance runtime layer."""


def _isolate_state(monkeypatch, tmp_path):
    import nudge.state as state

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")
    return state


_SKILL = {
    "schema_version": "0.1",
    "kind": "skill",
    "metadata": {
        "id": "test-skill",
        "title": "测试 Skill",
        "version": "1.0.0",
        "creator": "tests",
        "category": "test",
    },
    "audience": {"goals": ["test"]},
    "assessment": [{"id": "q1", "question": "q?", "type": "boolean"}],
    "plan_template": {
        "defaults": {"sessions_per_week": 1},
        "phases": [
            {"id": "p1", "title": "一", "weeks": 4, "sessions": [{"id": "s1", "title": "会话"}]},
            {"id": "p2", "title": "二", "weeks": 8, "sessions": [{"id": "s2", "title": "会话"}]},
        ],
    },
    "tracking": {
        "metrics": [
            {"id": "session_completed", "type": "boolean"},
            {"id": "effort", "type": "number"},
        ]
    },
}


def test_instance_roundtrip(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    from nudge.skills import runtime

    plan_id = runtime.create_skill_instance(
        _SKILL,
        {"assessment": {"q1": True}},
        start_date="2026-07-06",
        weeks_total=12,
        materialized_through_week=1,
        personalization_applied=["rule-a"],
    )

    instance = runtime.get_skill_instance(plan_id)
    assert instance["plan_id"] == plan_id
    assert instance["kind"] == runtime.SKILL_INSTANCE_KIND
    assert instance["skill_id"] == "test-skill"
    assert instance["skill_version"] == "1.0.0"
    assert instance["context"] == {"assessment": {"q1": True}}
    assert instance["start_date"] == "2026-07-06"
    assert instance["weeks_total"] == 12
    assert instance["materialized_through_week"] == 1
    assert instance["personalization_applied"] == ["rule-a"]
    assert instance["status"] == "active"

    listed = runtime.list_skill_instances()
    assert [item["plan_id"] for item in listed] == [plan_id]


def test_list_skips_non_skill_plans(monkeypatch, tmp_path):
    state = _isolate_state(monkeypatch, tmp_path)
    from nudge.skills import runtime

    state.create_plan("普通计划", config={"anything": 1})
    state.create_plan("无配置计划")
    assert runtime.list_skill_instances() == []
    assert runtime.get_skill_instance("missing") is None


def test_record_materialized_week_only_moves_forward(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    from nudge.skills import runtime

    plan_id = runtime.create_skill_instance(
        _SKILL, {}, start_date="2026-07-06", weeks_total=12,
        materialized_through_week=1, personalization_applied=[],
    )
    runtime.record_materialized_week(plan_id, 3)
    assert runtime.get_skill_instance(plan_id)["materialized_through_week"] == 3
    runtime.record_materialized_week(plan_id, 2)
    assert runtime.get_skill_instance(plan_id)["materialized_through_week"] == 3

    import pytest

    with pytest.raises(ValueError):
        runtime.record_materialized_week("missing", 1)


def test_skill_helpers():
    from nudge.skills import runtime

    assert runtime.skill_weeks_total(_SKILL) == 12
    assert runtime.skill_weeks_total({"plan_template": {}}) is None
    assert runtime.numeric_metric_ids(_SKILL) == ["effort"]
    assert runtime.numeric_metric_ids({}) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_skills_runtime.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'nudge.skills.runtime'`。

- [ ] **Step 3: 最小实现**

创建 `nudge/skills/runtime.py`:

```python
"""Skill instance runtime: local persistence, progress cursor, tracking context.

This layer is deterministic and Apple-free: it only touches local SQLite via
`nudge.state`, so it stays testable offline and on non-macOS platforms.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, timedelta

from nudge.state import create_plan, get_actions, get_plan, get_plans, update_plan_config

SKILL_INSTANCE_KIND = "skill_instance"

_COMPLETED_STATUSES = {"done"}
_PARTIAL_STATUSES = {"partial"}
_SKIPPED_STATUSES = {"skipped"}
_INSTANCE_ROW_KEYS = {"plan_id", "goal", "status", "created_at"}


def skill_weeks_total(skill: dict) -> int | None:
    """Total weeks declared by plan_template phases, or None when absent."""
    phases = (skill.get("plan_template") or {}).get("phases") or []
    total = sum(int(phase.get("weeks") or 0) for phase in phases)
    return total or None


def numeric_metric_ids(skill: dict) -> list[str]:
    """Ids of tracking metrics with numeric samples."""
    metrics = (skill.get("tracking") or {}).get("metrics") or []
    return [str(m["id"]) for m in metrics if m.get("type") == "number" and m.get("id")]


def create_skill_instance(
    skill: dict,
    context: dict,
    *,
    start_date: str,
    weeks_total: int | None,
    materialized_through_week: int,
    personalization_applied: list[str],
) -> str:
    """Persist one Skill instance as a plans row. Returns plan_id."""
    metadata = skill.get("metadata", {})
    goal = f"Skill: {metadata.get('title') or metadata.get('id') or 'unknown'}"
    config = {
        "kind": SKILL_INSTANCE_KIND,
        "skill_id": metadata.get("id"),
        "skill_version": metadata.get("version"),
        "context": deepcopy(dict(context)),
        "start_date": start_date,
        "weeks_total": weeks_total,
        "materialized_through_week": int(materialized_through_week),
        "personalization_applied": list(personalization_applied),
    }
    return create_plan(goal, config=config)


def _instance_from_plan(plan: dict) -> dict | None:
    try:
        config = json.loads(plan.get("config") or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(config, dict) or config.get("kind") != SKILL_INSTANCE_KIND:
        return None
    instance = dict(config)
    instance["plan_id"] = plan["id"]
    instance["goal"] = plan["goal"]
    instance["status"] = plan["status"]
    instance["created_at"] = plan.get("created_at")
    return instance


def list_skill_instances(status: str = "active") -> list[dict]:
    """Return Skill instances (plans tagged skill_instance) by status."""
    instances = []
    for plan in get_plans(status=status):
        instance = _instance_from_plan(plan)
        if instance:
            instances.append(instance)
    return instances


def get_skill_instance(plan_id: str) -> dict | None:
    """Return one Skill instance by plan id, or None."""
    plan = get_plan(plan_id)
    if not plan:
        return None
    return _instance_from_plan(plan)


def record_materialized_week(plan_id: str, week: int) -> None:
    """Advance the materialized-week cursor (never moves backwards)."""
    instance = get_skill_instance(plan_id)
    if not instance:
        raise ValueError(f"skill instance not found: {plan_id}")
    config = {k: v for k, v in instance.items() if k not in _INSTANCE_ROW_KEYS}
    current = int(config.get("materialized_through_week") or 0)
    config["materialized_through_week"] = max(current, int(week))
    update_plan_config(plan_id, config)
```

（`get_actions`、`date`、`timedelta`、`_COMPLETED_STATUSES` 等此时暂未使用,Task 4 使用;若 lint 报 unused 可先移到 Task 4 再引入 —— 推荐 Task 3 就按上文写全,Task 4 直接追加函数。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_skills_runtime.py -v`
Expected: 4 passed。

- [ ] **Step 5: Commit(需已获用户授权)**

```bash
git add nudge/skills/runtime.py tests/test_skills_runtime.py
git commit -m "feat(skills): 实例层落库(复用 plans/actions 表)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: tracking context 构建(真实数据 → adaptation 变量)

**Files:**
- Modify: `nudge/skills/runtime.py`
- Test: `tests/test_skills_runtime.py`(追加)

**Interfaces:**
- Consumes: `state.get_actions(plan_id=...)`(行含 `status`/`scheduled_at`/`feedback` JSON 文本);`feedback["metrics"]` 字典(`nudge/feedback.py:56-57` 既有约定)。
- Produces: `build_tracking_context(plan_id: str, metric_ids: list[str] | tuple = (), *, today: date | None = None) -> dict`,返回 `{"history": {...}}`。history 键(7d/14d 两窗,窗口含 today 往前 N-1 天,按 `scheduled_at` 日期归窗):`sessions_total_{N}d`、`sessions_completed_{N}d`(status=done)、`sessions_partial_{N}d`、`sessions_skipped_{N}d`、`completion_rate_{N}d`(done/total,4 位小数,total=0 时为 0.0);每个 metric_id 若窗口内(done/partial 的 feedback.metrics)有数值样本则给 `{metric_id}_avg_{N}d`(2 位小数),**无样本则省略键**(配合 JsonLogic `missing` 语义)。

- [ ] **Step 1: 写失败测试**

在 `tests/test_skills_runtime.py` 末尾追加:

```python
def _log_action_at(state, plan_id, scheduled_at, status, metrics=None):
    action_id = state.log_action(
        "calendar_event", "测试会话", scheduled_at=scheduled_at, plan_id=plan_id
    )
    feedback = {"metrics": metrics} if metrics else None
    if status == "done":
        state.complete_action(action_id, feedback=feedback)
    elif status == "skipped":
        state.skip_action(action_id, feedback=feedback)
    elif status == "partial":
        state.partial_action(action_id, feedback=feedback)
    return action_id


def test_build_tracking_context_windows_and_metrics(monkeypatch, tmp_path):
    state = _isolate_state(monkeypatch, tmp_path)
    from datetime import date

    from nudge.skills import runtime

    plan_id = runtime.create_skill_instance(
        _SKILL, {}, start_date="2026-06-22", weeks_total=12,
        materialized_through_week=2, personalization_applied=[],
    )
    today = date(2026, 7, 4)
    # 7 天窗内（06-28 起）：done×2（effort 9/8）、skipped×1、partial×1（effort 6）
    _log_action_at(state, plan_id, "2026-07-01 07:30", "done", {"effort": 9})
    _log_action_at(state, plan_id, "2026-07-03 07:30", "done", {"effort": 8})
    _log_action_at(state, plan_id, "2026-07-02 07:30", "skipped")
    _log_action_at(state, plan_id, "2026-06-29 07:30", "partial", {"effort": 6})
    # 14 天窗内、7 天窗外：done×1（effort 3）
    _log_action_at(state, plan_id, "2026-06-24 07:30", "done", {"effort": 3})
    # 窗外与无排期的不计入
    _log_action_at(state, plan_id, "2026-06-01 07:30", "done", {"effort": 1})
    _log_action_at(state, plan_id, None, "done", {"effort": 1})
    # 其它 plan 的不计入
    other = runtime.create_skill_instance(
        _SKILL, {}, start_date="2026-06-22", weeks_total=12,
        materialized_through_week=1, personalization_applied=[],
    )
    _log_action_at(state, other, "2026-07-01 07:30", "done", {"effort": 10})

    history = runtime.build_tracking_context(plan_id, ["effort"], today=today)["history"]

    assert history["sessions_total_7d"] == 4
    assert history["sessions_completed_7d"] == 2
    assert history["sessions_partial_7d"] == 1
    assert history["sessions_skipped_7d"] == 1
    assert history["completion_rate_7d"] == 0.5
    assert history["effort_avg_7d"] == round((9 + 8 + 6) / 3, 2)
    assert history["sessions_total_14d"] == 5
    assert history["sessions_completed_14d"] == 3
    assert history["effort_avg_14d"] == round((9 + 8 + 6 + 3) / 4, 2)


def test_build_tracking_context_empty_plan_omits_metric_keys(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    from datetime import date

    from nudge.skills import runtime

    plan_id = runtime.create_skill_instance(
        _SKILL, {}, start_date="2026-07-06", weeks_total=12,
        materialized_through_week=1, personalization_applied=[],
    )
    history = runtime.build_tracking_context(plan_id, ["effort"], today=date(2026, 7, 4))["history"]
    assert history["sessions_total_7d"] == 0
    assert history["completion_rate_7d"] == 0.0
    assert "effort_avg_7d" not in history
    assert "effort_avg_14d" not in history
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_skills_runtime.py -v`
Expected: 新增 2 个用例 FAIL(`AttributeError: ... no attribute 'build_tracking_context'`),原 4 个 PASS。

- [ ] **Step 3: 最小实现**

在 `nudge/skills/runtime.py` 末尾追加:

```python
def build_tracking_context(
    plan_id: str,
    metric_ids: list[str] | tuple = (),
    *,
    today: date | None = None,
) -> dict:
    """Deterministic history variables for adaptation rules, from logged actions.

    Metric averages are omitted (not None) when a window has no samples so
    JsonLogic `missing` semantics keep working.
    """
    current = today or date.today()
    actions = get_actions(plan_id=plan_id)
    history: dict[str, object] = {}

    for days in (7, 14):
        window_start = (current - timedelta(days=days - 1)).isoformat()
        window_end = current.isoformat()
        in_window = []
        for action in actions:
            scheduled = str(action.get("scheduled_at") or "")[:10]
            if len(scheduled) == 10 and window_start <= scheduled <= window_end:
                in_window.append(action)

        done = [a for a in in_window if a.get("status") in _COMPLETED_STATUSES]
        partial = [a for a in in_window if a.get("status") in _PARTIAL_STATUSES]
        skipped = [a for a in in_window if a.get("status") in _SKIPPED_STATUSES]
        history[f"sessions_total_{days}d"] = len(in_window)
        history[f"sessions_completed_{days}d"] = len(done)
        history[f"sessions_partial_{days}d"] = len(partial)
        history[f"sessions_skipped_{days}d"] = len(skipped)
        history[f"completion_rate_{days}d"] = (
            round(len(done) / len(in_window), 4) if in_window else 0.0
        )

        for metric_id in metric_ids:
            samples = []
            for action in done + partial:
                feedback = _parse_feedback(action.get("feedback"))
                value = (feedback.get("metrics") or {}).get(metric_id)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    samples.append(float(value))
            if samples:
                history[f"{metric_id}_avg_{days}d"] = round(sum(samples) / len(samples), 2)

    return {"history": history}


def _parse_feedback(feedback_value: object) -> dict:
    if isinstance(feedback_value, dict):
        return feedback_value
    if not feedback_value:
        return {}
    try:
        parsed = json.loads(str(feedback_value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_skills_runtime.py -v`
Expected: 6 passed。

- [ ] **Step 5: Commit(需已获用户授权)**

```bash
git add nudge/skills/runtime.py tests/test_skills_runtime.py
git commit -m "feat(skills): 真实打卡数据构建 tracking context

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `log` / `check-in` 增加 `--metric`

**Files:**
- Modify: `nudge/commands/log.py`
- Test: `tests/test_commands_log_metric.py`

**Interfaces:**
- Consumes: `_run_check_in(..., metrics: dict | None)`(既有,`log.py:181-194`;metrics 经 `build_feedback` 存进 `feedback["metrics"]`)。
- Produces: `nudge log <status> --metric effort=8 --metric rpe=7`(repeatable,`check-in` 同步);新增模块级 `_parse_metric_pairs(pairs: tuple[str, ...]) -> dict[str, float] | None`(格式错误抛 `click.ClickException`)。`parse` 子路径不接 `--metric`(LLM 解析已产出 metrics),传了则报错提示。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_commands_log_metric.py`:

```python
"""Public-safe tests for `nudge log --metric` numeric check-in metrics."""

import json

from click.testing import CliRunner


def _isolate_state(monkeypatch, tmp_path):
    import nudge.state as state

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")
    return state


def test_log_done_with_metric_stores_feedback_metrics(monkeypatch, tmp_path):
    state = _isolate_state(monkeypatch, tmp_path)
    from nudge.commands.log import log_command

    action_id = state.log_action("calendar_event", "力量训练", scheduled_at="2026-07-04 07:30")
    runner = CliRunner()
    result = runner.invoke(
        log_command,
        ["done", "--id", action_id, "--metric", "effort=8", "--metric", "rpe=7.5", "--json"],
    )

    assert result.exit_code == 0, result.output
    stored = state.get_action(action_id)
    assert stored["status"] == "done"
    feedback = json.loads(stored["feedback"])
    assert feedback["metrics"] == {"effort": 8.0, "rpe": 7.5}


def test_log_metric_rejects_bad_pairs(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    from nudge.commands.log import log_command

    runner = CliRunner()
    for bad in ("effort", "=8", "effort=high"):
        result = runner.invoke(log_command, ["done", "--metric", bad])
        assert result.exit_code != 0
        assert "--metric" in result.output


def test_log_parse_rejects_metric_flag(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    from nudge.commands.log import log_command

    runner = CliRunner()
    result = runner.invoke(log_command, ["parse", "做完了", "--metric", "effort=8"])
    assert result.exit_code != 0
    assert "parse" in result.output
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_commands_log_metric.py -v`
Expected: FAIL,`Error: No such option: --metric`(3 个用例都失败)。

- [ ] **Step 3: 最小实现**

`nudge/commands/log.py` 改三处。

(a) 在 `_STATUS_LABELS` 定义后加解析函数:

```python
def _parse_metric_pairs(pairs: tuple[str, ...]) -> dict[str, float] | None:
    """Parse repeatable --metric key=value flags into a numeric metrics dict."""
    if not pairs:
        return None
    metrics: dict[str, float] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        key = key.strip()
        if not sep or not key:
            raise click.ClickException(f"--metric 需要 key=value 形式: {pair!r}")
        try:
            metrics[key] = float(value.strip())
        except ValueError:
            raise click.ClickException(f"--metric 的值必须是数字: {pair!r}")
    return metrics
```

(b) `log_command`(`log.py:36-78`):在 `--dry-run` option 之前加一行 option,函数签名与两条调用路径同步:

```python
@click.option("--metric", "metric_pairs", multiple=True, help="数值指标 key=value，可重复（如 --metric effort=8）")
```

```python
def log_command(
    status: str,
    note_words: tuple[str, ...],
    action_id: str | None,
    match_text: str | None,
    reason: str | None,
    next_action: str | None,
    metric_pairs: tuple[str, ...],
    dry_run: bool,
    json_output: bool,
):
    """Quickly mark the latest pending action as done/skipped/partial."""
    if status == "parse":
        if metric_pairs:
            raise click.ClickException("`log parse` 不支持 --metric（自然语言解析会自动提取指标）")
        _run_parse_check_in(
            " ".join(note_words),
            action_id=action_id,
            match_text=match_text,
            reason=reason,
            next_action=next_action,
            dry_run=dry_run,
            json_output=json_output,
            source="nudge log parse",
        )
        return
    _run_check_in(
        status,
        " ".join(note_words),
        action_id,
        match_text,
        reason=reason,
        next_action=next_action,
        source="nudge log",
        dry_run=dry_run,
        json_output=json_output,
        metrics=_parse_metric_pairs(metric_pairs),
    )
```

(c) `check_in_command`(`log.py:81-123`)做完全相同的修改(加同一 option、同一签名参数、parse 分支同样拒绝、非 parse 分支传 `metrics=_parse_metric_pairs(metric_pairs)`,`source` 保持 `"nudge check-in"`)。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_commands_log_metric.py -v`
Expected: 3 passed。

- [ ] **Step 5: Commit(需已获用户授权)**

```bash
git add nudge/commands/log.py tests/test_commands_log_metric.py
git commit -m "feat(log): 打卡支持 --metric 数值指标

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: `nudge skills start`(assessment 交互 + 实例落库 + Apple 写入)

**Files:**
- Modify: `nudge/commands/skills.py`
- Test: `tests/test_commands_skills_runtime.py`

**Interfaces:**
- Consumes: `dry_run_skill`(Task 1 扩展后)、`runtime.create_skill_instance/skill_weeks_total`(Task 3)、`state.configure_state/log_action`、`config.load_config/get_defaults/get_family_aliases`、`do.execute_action(action, alias_map, defaults, quiet, apple_backends)`、`adapters.resolve_apple_backends(config)`(与 `agent.py:21` 相同的既有跨模块复用;正式化提升是 TODO 里的独立重构,不在本计划做)。
- Produces:
  - 子命令 `skills start <skill_source>`,flags:`--context FILE`(跳过交互评估)、`--weeks 1..12`(首次落地周数,默认 1)、`--start-date YYYY-MM-DD`、`--dry-run/-n`、`--yes/-y`、`--config/-c`、`--json`。`--json` 必须配 `--context`(机器模式无交互),且跳过确认。
  - 模块级 `_run_assessment(skill: dict) -> dict`(按 `ASSESSMENT_TYPES` 逐题 prompt,返回 answers dict)。
  - 模块级 `_materialize_actions(actions: list[dict], *, plan_id: str, config: dict) -> tuple[list[dict], list[dict]]`(返回 (created, failed);成功项 `log_action(..., plan_id=...)`,Task 8 复用)。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_commands_skills_runtime.py`(本任务先写 start 部分;Task 7/8 追加):

```python
"""Public-safe tests for skills start/status/adapt runtime commands."""

import json

from click.testing import CliRunner

from nudge.apple.adapters import AppleBackends, WriteResult


def _isolate_state(monkeypatch, tmp_path):
    import nudge.state as state

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "DB_PATH", tmp_path / "nudge.db")
    monkeypatch.setattr(state, "LEGACY_JSON", tmp_path / "state.json")
    return state


class _FakeCalendar:
    name = "fake"

    def __init__(self):
        self.created = []

    def list_calendars(self):
        return True, ["Personal"]

    def create_event(self, **kwargs):
        self.created.append(kwargs)
        return WriteResult(ok=True, message="ok", external_id=f"cal-{len(self.created)}")


class _FakeReminders:
    name = "fake"

    def list_lists(self):
        return True, ["Reminders"]

    def probe_read(self, list_name=None):
        return True, "ok"

    def create_reminder(self, **kwargs):
        return WriteResult(ok=True, message="ok", external_id="rem-1")


class _FakeClock:
    name = "fake"
    shortcut_name = "Fake"

    def check(self):
        return True, "ok"

    def create_alarm(self, **kwargs):
        return WriteResult(ok=True, message="ok", external_id="alarm-1")


class _FakeNotes:
    name = "fake"

    def list_folders(self):
        return True, ["Nudge"]

    def create_note(self, **kwargs):
        return WriteResult(ok=True, message="ok", external_id=None)


def _wire_command_env(monkeypatch, tmp_path):
    """Isolate state, config, and Apple backends for skills command tests."""
    state = _isolate_state(monkeypatch, tmp_path)
    import nudge.commands.skills as skills_cmd

    calendar = _FakeCalendar()
    backends = AppleBackends(
        calendar=calendar, reminders=_FakeReminders(), notes=_FakeNotes(), clock=_FakeClock()
    )
    monkeypatch.setattr(skills_cmd, "load_config", lambda path=None: {})
    monkeypatch.setattr(skills_cmd, "configure_state", lambda config=None: tmp_path)
    monkeypatch.setattr(skills_cmd, "resolve_apple_backends", lambda config: backends)
    return state, skills_cmd, calendar


def _context_file(tmp_path, data):
    path = tmp_path / "context.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_skills_start_json_creates_instance_and_actions(monkeypatch, tmp_path):
    state, skills_cmd, calendar = _wire_command_env(monkeypatch, tmp_path)
    from nudge.skills.runtime import list_skill_instances

    context = _context_file(
        tmp_path,
        {
            "assessment": {"current_frequency": "never", "preferred_session_length": 45},
            "profile": {"start_date": "2026-07-06"},
        },
    )
    runner = CliRunner()
    result = runner.invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--context", context, "--weeks", "1", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    plan_id = payload["plan_id"]
    # personalization: current_frequency=never → sessions_per_week=3
    assert len(payload["created"]) == 3
    assert len(calendar.created) == 3

    instances = list_skill_instances()
    assert [i["plan_id"] for i in instances] == [plan_id]
    assert instances[0]["skill_id"] == "strength-basics-12w"
    assert instances[0]["materialized_through_week"] == 1
    assert instances[0]["weeks_total"] == 12

    actions = state.get_actions(plan_id=plan_id)
    assert len(actions) == 3
    assert all(a["external_id"] for a in actions)
    assert all(a["status"] == "created" for a in actions)


def test_skills_start_dry_run_writes_nothing(monkeypatch, tmp_path):
    state, skills_cmd, calendar = _wire_command_env(monkeypatch, tmp_path)
    from nudge.skills.runtime import list_skill_instances

    context = _context_file(tmp_path, {"profile": {"start_date": "2026-07-06"}})
    runner = CliRunner()
    result = runner.invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--context", context, "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["dry_run"] is True
    assert calendar.created == []
    assert list_skill_instances() == []
    assert state.get_actions() == []


def test_skills_start_json_requires_context(monkeypatch, tmp_path):
    _, skills_cmd, _ = _wire_command_env(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(skills_cmd.skills_command, ["start", "strength-basics-12w", "--json"])
    assert result.exit_code != 0
    assert "--context" in result.output


def test_skills_start_interactive_assessment(monkeypatch, tmp_path):
    state, skills_cmd, calendar = _wire_command_env(monkeypatch, tmp_path)
    runner = CliRunner()
    # 交互输入：single_choice 选 1（never）→ number 输入 45 → 确认 y
    result = runner.invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--start-date", "2026-07-06"],
        input="1\n45\ny\n",
    )
    assert result.exit_code == 0, result.output
    assert len(calendar.created) == 3

    from nudge.skills.runtime import list_skill_instances

    instance = list_skill_instances()[0]
    assert instance["context"]["assessment"] == {
        "current_frequency": "never",
        "preferred_session_length": 45.0,
    }
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_commands_skills_runtime.py -v`
Expected: FAIL,`Error: No such command 'start'.`(以及 monkeypatch 目标 `load_config` 不存在时的 `AttributeError` —— 先加 import 后重跑仍应因缺 `start` 失败)。

- [ ] **Step 3: 实现**

`nudge/commands/skills.py` 改两处。

(a) 文件头部 import 区追加(放在既有 import 之后):

```python
from copy import deepcopy
from datetime import date

from nudge.apple.adapters import resolve_apple_backends
from nudge.commands.do import execute_action
from nudge.config import get_defaults, get_family_aliases, load_config
from nudge.skills.runtime import (
    build_tracking_context,
    create_skill_instance,
    get_skill_instance,
    list_skill_instances,
    numeric_metric_ids,
    record_materialized_week,
    skill_weeks_total,
)
from nudge.state import configure_state, get_actions, log_action
```

（`deepcopy`/`build_tracking_context`/`get_skill_instance`/`numeric_metric_ids`/`record_materialized_week`/`get_actions` 供 Task 7/8 使用,一次引齐。）

(b) 文件末尾追加:

```python
def _run_assessment(skill: dict) -> dict:
    """Interactively collect assessment answers defined by the Skill."""
    answers: dict[str, object] = {}
    for item in skill.get("assessment") or []:
        qid = str(item["id"])
        qtype = item["type"]
        question = str(item["question"])
        if qtype in {"single_choice", "multi_choice"}:
            options = item["options"]
            click.echo(question)
            for index, option in enumerate(options, 1):
                click.echo(f"  {index}. {option.get('label') or option.get('id')}")
            if qtype == "single_choice":
                choice = click.prompt("选择编号", type=click.IntRange(1, len(options)))
                answers[qid] = str(options[choice - 1].get("id"))
            else:
                raw = click.prompt("选择编号（逗号分隔）", default="", show_default=False)
                picked = []
                for part in raw.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    try:
                        index = int(part)
                    except ValueError:
                        raise click.ClickException(f"选项编号必须是数字: {part!r}")
                    if not 1 <= index <= len(options):
                        raise click.ClickException(f"选项编号超出范围: {index}")
                    picked.append(str(options[index - 1].get("id")))
                answers[qid] = picked
        elif qtype == "number":
            answers[qid] = click.prompt(question, type=float)
        elif qtype == "boolean":
            answers[qid] = click.confirm(question)
        else:
            answers[qid] = click.prompt(question, default="", show_default=False)
    return answers


def _materialize_actions(actions: list[dict], *, plan_id: str, config: dict) -> tuple[list[dict], list[dict]]:
    """Write candidate actions to Apple and log successes into SQLite."""
    backends = resolve_apple_backends(config)
    defaults = get_defaults(config)
    alias_map = get_family_aliases(config)
    created: list[dict] = []
    failed: list[dict] = []
    for candidate in actions:
        action = dict(candidate)
        ok = execute_action(action, alias_map, defaults, quiet=False, apple_backends=backends)
        if ok:
            action_id = log_action(
                action["type"],
                action["summary"],
                scheduled_at=action.get("start"),
                external_id=action.get("_external_id"),
                plan_id=plan_id,
            )
            created.append({
                "action_id": action_id,
                "type": candidate.get("type"),
                "summary": candidate.get("summary"),
                "start": candidate.get("start"),
                "week": candidate.get("week"),
            })
        else:
            error = action.get("_error")
            failed.append({
                "summary": candidate.get("summary"),
                "week": candidate.get("week"),
                "error": getattr(error, "title", None) or str(error or "unknown error"),
            })
    return created, failed


def _echo_action_preview(actions: list[dict]) -> None:
    for action in actions:
        click.echo(
            f"  - W{action['week']} {action['start']} → {action['end']}  [{action['type']}] {action['summary']}"
        )


@skills_command.command("start")
@click.argument("skill_source")
@click.option("--context", "context_file", type=click.Path(exists=True, dir_okay=False), default=None, help="Context JSON（提供则跳过交互式评估）")
@click.option("--weeks", default=1, type=click.IntRange(1, 12), help="首次落地的周数")
@click.option("--start-date", "start_date_text", default=None, help="开始日期 YYYY-MM-DD，默认今天")
@click.option("--dry-run", "-n", is_flag=True, help="只预览，不写 Apple / SQLite")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="跳过确认")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON（需配合 --context）")
def start_command(skill_source, context_file, weeks, start_date_text, dry_run, assume_yes, config_path, json_output):
    """Start a Skill：评估 → 个性化 → 确认 → 写 Apple 并登记本地实例。"""
    config = load_config(config_path) if config_path else load_config()
    configure_state(config)
    try:
        skill = validate_skill(load_skill_source(skill_source))
        if context_file:
            context = _load_context(context_file)
        elif json_output:
            raise click.ClickException("--json 模式必须提供 --context（无交互评估）")
        else:
            context = {"assessment": _run_assessment(skill)}
        profile = dict(context.get("profile") or {})
        start_date = str(start_date_text or profile.get("start_date") or date.today().isoformat())
        date.fromisoformat(start_date)
        profile["start_date"] = start_date
        context["profile"] = profile
        result = dry_run_skill(skill, context, weeks=weeks)
    except SkillValidationError as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "issues": _issue_payload(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))
    except click.ClickException:
        raise
    except Exception as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "error": str(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))

    if not result.actions:
        raise click.ClickException("Skill 没有生成任何候选动作，请检查 plan_template。")

    if not json_output:
        click.echo(f"Skill 启动预览: {_metadata_label(result.skill)}")
        click.echo(
            "Personalization: "
            + (", ".join(result.personalization_applied) if result.personalization_applied else "none")
        )
        _echo_action_preview(result.actions)

    if dry_run:
        if json_output:
            click.echo(json.dumps(versioned_payload({
                "ok": True,
                "dry_run": True,
                "actions": result.actions,
                "personalization_applied": result.personalization_applied,
            }), ensure_ascii=False))
        else:
            click.echo("DRY-RUN：未写入 Apple / SQLite。")
        return

    if not assume_yes and not json_output:
        if not click.confirm(f"确认写入 {len(result.actions)} 个动作到 Apple 并登记本地实例？"):
            click.echo("已取消。")
            return

    plan_id = create_skill_instance(
        result.skill,
        context,
        start_date=start_date,
        weeks_total=skill_weeks_total(result.skill),
        materialized_through_week=weeks,
        personalization_applied=result.personalization_applied,
    )
    created, failed = _materialize_actions(result.actions, plan_id=plan_id, config=config)
    payload = {
        "ok": not failed,
        "plan_id": plan_id,
        "created": created,
        "failed": failed,
        "personalization_applied": result.personalization_applied,
    }
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        if failed:
            raise click.exceptions.Exit(1)
        return
    click.echo(f"PASS Skill 实例已创建: {plan_id}（写入 {len(created)} 个动作，失败 {len(failed)} 个）")
    click.echo("进度: nudge skills status；打卡: nudge log done --metric effort=8；下周: nudge skills adapt " + plan_id)
    if failed:
        raise click.exceptions.Exit(1)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_commands_skills_runtime.py -v`
Expected: 4 passed。

- [ ] **Step 5: 回归既有 skills/agent 测试**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部通过(重点确认 `test_commands_agent.py` 不受 `commands/do` import 链影响)。

- [ ] **Step 6: Commit(需已获用户授权)**

```bash
git add nudge/commands/skills.py tests/test_commands_skills_runtime.py
git commit -m "feat(skills): start 子命令——评估交互、实例落库、写入 Apple

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: `nudge skills status`

**Files:**
- Modify: `nudge/commands/skills.py`
- Test: `tests/test_commands_skills_runtime.py`(追加)

**Interfaces:**
- Consumes: `list_skill_instances()`、`build_tracking_context(plan_id, ())`、`state.get_actions(plan_id=...)`(import 已在 Task 6 备齐)。
- Produces: 子命令 `skills status`,flags `--config/-c`、`--json`。JSON 输出 `{"ok": true, "instances": [{plan_id, skill_id, goal, start_date, weeks_total, materialized_through_week, actions_total, actions_done, completion_rate_7d}]}`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_commands_skills_runtime.py` 末尾追加:

```python
def test_skills_status_lists_instances_with_progress(monkeypatch, tmp_path):
    state, skills_cmd, _ = _wire_command_env(monkeypatch, tmp_path)
    context = _context_file(tmp_path, {"profile": {"start_date": "2026-07-06"}})
    runner = CliRunner()
    start = runner.invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--context", context, "--json"],
    )
    plan_id = json.loads(start.output)["plan_id"]
    actions = state.get_actions(plan_id=plan_id)
    state.complete_action(actions[0]["id"])

    result = runner.invoke(skills_cmd.skills_command, ["status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    row = payload["instances"][0]
    assert row["plan_id"] == plan_id
    assert row["skill_id"] == "strength-basics-12w"
    assert row["actions_total"] == 4
    assert row["actions_done"] == 1
    assert row["materialized_through_week"] == 1
    assert row["weeks_total"] == 12


def test_skills_status_empty(monkeypatch, tmp_path):
    _, skills_cmd, _ = _wire_command_env(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(skills_cmd.skills_command, ["status"])
    assert result.exit_code == 0
    assert "没有进行中的 Skill 实例" in result.output
```

注意:该用例不传 `--weeks`(默认 1),且 context 无 assessment → personalization 不触发 → 默认 `sessions_per_week: 4`,故 `actions_total == 4`。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_commands_skills_runtime.py -v`
Expected: 新增 2 个用例 FAIL(`No such command 'status'.`),其余通过。

- [ ] **Step 3: 实现**

`nudge/commands/skills.py` 末尾追加:

```python
@skills_command.command("status")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def status_command(config_path, json_output):
    """Show active Skill instances and completion progress."""
    config = load_config(config_path) if config_path else load_config()
    configure_state(config)
    rows = []
    for instance in list_skill_instances():
        plan_id = instance["plan_id"]
        actions = get_actions(plan_id=plan_id)
        history = build_tracking_context(plan_id, ())["history"]
        rows.append({
            "plan_id": plan_id,
            "skill_id": instance.get("skill_id"),
            "goal": instance.get("goal"),
            "start_date": instance.get("start_date"),
            "weeks_total": instance.get("weeks_total"),
            "materialized_through_week": instance.get("materialized_through_week"),
            "actions_total": len(actions),
            "actions_done": sum(1 for a in actions if a.get("status") == "done"),
            "completion_rate_7d": history.get("completion_rate_7d"),
        })

    if json_output:
        click.echo(json.dumps(versioned_payload({"ok": True, "instances": rows}), ensure_ascii=False))
        return

    if not rows:
        click.echo("没有进行中的 Skill 实例。用 `nudge skills start <skill-id>` 开始。")
        return
    for row in rows:
        weeks_total = row["weeks_total"] or "?"
        click.echo(
            f"  - {row['plan_id']}  {row['goal']}  "
            f"W{row['materialized_through_week']}/{weeks_total}  "
            f"done {row['actions_done']}/{row['actions_total']}  "
            f"近7天完成率 {row['completion_rate_7d']}"
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_commands_skills_runtime.py -v`
Expected: 6 passed。

- [ ] **Step 5: Commit(需已获用户授权)**

```bash
git add nudge/commands/skills.py tests/test_commands_skills_runtime.py
git commit -m "feat(skills): status 子命令展示实例进度

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: `nudge skills adapt`(数据驱动的下周落地)

**Files:**
- Modify: `nudge/commands/skills.py`
- Test: `tests/test_commands_skills_runtime.py`(追加)

**Interfaces:**
- Consumes: `get_skill_instance`、`build_tracking_context(plan_id, numeric_metric_ids(skill))`、`record_materialized_week`、`_materialize_actions`(Task 6)、`dry_run_skill`、`load_skill_source`。
- Produces: 子命令 `skills adapt <plan_id>`,flags `--weeks 1..4`(默认 1)、`--apply`(默认只预览)、`--config/-c`、`--json`。行为:取 `materialized_through_week+1` 起 N 周的候选动作(生成 1..to_week 后按 `week >= from_week` 过滤);context = 实例 context + 实时 `history`;`--apply` 时写 Apple + 落库 + 前移游标;skill 版本与实例记录不一致时输出 `WARN`(stderr),超出 `weeks_total` 时同样 `WARN` 但不阻断。

- [ ] **Step 1: 写失败测试**

在 `tests/test_commands_skills_runtime.py` 末尾追加:

```python
def _start_instance(skills_cmd, state, tmp_path, runner):
    """Start a builtin skill instance and return its plan_id."""
    from datetime import date, timedelta

    start_date = (date.today() - timedelta(days=3)).isoformat()
    context = _context_file(tmp_path, {"profile": {"start_date": start_date}})
    result = runner.invoke(
        skills_cmd.skills_command,
        ["start", "strength-basics-12w", "--context", context, "--json"],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["plan_id"]


def test_skills_adapt_preview_uses_history_and_does_not_write(monkeypatch, tmp_path):
    state, skills_cmd, calendar = _wire_command_env(monkeypatch, tmp_path)
    runner = CliRunner()
    plan_id = _start_instance(skills_cmd, state, tmp_path, runner)
    writes_before = len(calendar.created)

    # 高 effort 打卡 → adaptation `too_hard_deload`（effort_avg_7d > 8）应触发 session_minutes clamp ≤ 35
    for action in state.get_actions(plan_id=plan_id):
        state.complete_action(action["id"], feedback={"metrics": {"effort": 9}})

    result = runner.invoke(skills_cmd.skills_command, ["adapt", plan_id, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["applied"] is False
    assert "too_hard_deload" in payload["adaptation_applied"]
    assert payload["from_week"] == 2
    assert all(a["week"] == 2 for a in payload["actions"])
    assert all(a["duration_minutes"] <= 35 for a in payload["actions"])
    assert payload["history"]["effort_avg_7d"] == 9.0
    # 预览不写入
    assert len(calendar.created) == writes_before
    from nudge.skills.runtime import get_skill_instance

    assert get_skill_instance(plan_id)["materialized_through_week"] == 1


def test_skills_adapt_apply_materializes_next_week(monkeypatch, tmp_path):
    state, skills_cmd, calendar = _wire_command_env(monkeypatch, tmp_path)
    runner = CliRunner()
    plan_id = _start_instance(skills_cmd, state, tmp_path, runner)
    writes_before = len(calendar.created)
    actions_before = len(state.get_actions(plan_id=plan_id))

    result = runner.invoke(skills_cmd.skills_command, ["adapt", plan_id, "--apply", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["applied"] is True
    assert len(payload["created"]) == 4  # 无 assessment → 默认 4 sessions/week
    assert len(calendar.created) == writes_before + 4
    assert len(state.get_actions(plan_id=plan_id)) == actions_before + 4

    from nudge.skills.runtime import get_skill_instance

    assert get_skill_instance(plan_id)["materialized_through_week"] == 2


def test_skills_adapt_unknown_instance_fails(monkeypatch, tmp_path):
    _, skills_cmd, _ = _wire_command_env(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(skills_cmd.skills_command, ["adapt", "missing"])
    assert result.exit_code != 0
    assert "找不到 Skill 实例" in result.output
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_commands_skills_runtime.py -v`
Expected: 新增 3 个用例 FAIL(`No such command 'adapt'.`),其余通过。

- [ ] **Step 3: 实现**

`nudge/commands/skills.py` 末尾追加:

```python
@skills_command.command("adapt")
@click.argument("plan_id")
@click.option("--weeks", default=1, type=click.IntRange(1, 4), help="向后落地的周数")
@click.option("--apply", "apply_changes", is_flag=True, help="确认写入（默认只预览）")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
def adapt_command(plan_id, weeks, apply_changes, config_path, json_output):
    """用真实打卡数据做 adaptation，预览/落地下一周动作。"""
    config = load_config(config_path) if config_path else load_config()
    configure_state(config)
    instance = get_skill_instance(plan_id)
    if not instance:
        raise click.ClickException(f"找不到 Skill 实例: {plan_id}")

    try:
        skill = validate_skill(load_skill_source(str(instance.get("skill_id"))))
    except SkillValidationError as exc:
        raise click.ClickException(f"无法加载 Skill {instance.get('skill_id')}: {exc}")

    current_version = str(skill.get("metadata", {}).get("version"))
    if current_version != str(instance.get("skill_version")):
        click.echo(
            f"WARN Skill 版本变化: 实例 {instance.get('skill_version')} → 当前 {current_version}",
            err=True,
        )

    context = deepcopy(instance.get("context") or {})
    history = build_tracking_context(plan_id, numeric_metric_ids(skill))["history"]
    context["history"] = history

    from_week = int(instance.get("materialized_through_week") or 0) + 1
    to_week = from_week + weeks - 1
    weeks_total = instance.get("weeks_total")
    if weeks_total and to_week > int(weeks_total):
        click.echo(f"WARN 已超出计划总周数 {weeks_total}（目标 W{to_week}）", err=True)

    try:
        result = dry_run_skill(skill, context, weeks=to_week)
    except SkillValidationError as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "issues": _issue_payload(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))
    except Exception as exc:
        if json_output:
            click.echo(json.dumps(versioned_payload({"ok": False, "error": str(exc)}), ensure_ascii=False))
            raise click.exceptions.Exit(1)
        raise click.ClickException(str(exc))

    next_actions = [a for a in result.actions if int(a["week"]) >= from_week]

    if not json_output:
        click.echo(f"Skill adaptation: {_metadata_label(result.skill)}  W{from_week}..W{to_week}")
        click.echo(
            "Adaptation: "
            + (", ".join(result.adaptation_applied) if result.adaptation_applied else "none")
        )
        click.echo(f"History: {json.dumps(history, ensure_ascii=False)}")
        _echo_action_preview(next_actions)

    if not apply_changes:
        if json_output:
            click.echo(json.dumps(versioned_payload({
                "ok": True,
                "applied": False,
                "plan_id": plan_id,
                "from_week": from_week,
                "to_week": to_week,
                "adaptation_applied": result.adaptation_applied,
                "history": history,
                "actions": next_actions,
            }), ensure_ascii=False))
        else:
            click.echo("预览模式：加 --apply 才会写入 Apple 并登记动作。")
        return

    created, failed = _materialize_actions(next_actions, plan_id=plan_id, config=config)
    if created:
        record_materialized_week(plan_id, to_week)
    payload = {
        "ok": not failed,
        "applied": True,
        "plan_id": plan_id,
        "from_week": from_week,
        "to_week": to_week,
        "adaptation_applied": result.adaptation_applied,
        "history": history,
        "created": created,
        "failed": failed,
    }
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        if failed:
            raise click.exceptions.Exit(1)
        return
    click.echo(f"PASS 已落地 W{from_week}..W{to_week}: 写入 {len(created)} 个动作，失败 {len(failed)} 个")
    if failed:
        raise click.exceptions.Exit(1)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_commands_skills_runtime.py -v`
Expected: 9 passed。

- [ ] **Step 5: Commit(需已获用户授权)**

```bash
git add nudge/commands/skills.py tests/test_commands_skills_runtime.py
git commit -m "feat(skills): adapt 子命令——打卡数据驱动下周落地

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: 文档收尾 + 全量验证

**Files:**
- Modify: `README.md`(Recommended Flow 一节)
- Modify: `TODO.md`(2026-07-04 审阅补充一节)

**Interfaces:**
- Consumes: Task 1-8 全部产物。
- Produces: 用户可见文档与 TODO 状态同步;`scripts/verify.sh` 全绿。

- [ ] **Step 1: 更新 README**

在 `README.md` 的 "Recommended Flow" 列表(第 7 条之后)追加一条,并在 "Maintenance" 之前插入新小节:

```markdown
8. `nudge skills start <skill-id>` runs the skill assessment, personalizes the plan, and writes the first week into Calendar/Reminders; `nudge skills adapt <plan-id> --apply` materializes the next week using your real check-in data.

## Skills Lifecycle

```bash
nudge skills list
nudge skills start strength-basics-12w
nudge log done --metric effort=8
nudge skills status
nudge skills adapt <plan-id>            # preview next week with data-driven adaptation
nudge skills adapt <plan-id> --apply    # write next week
```

Skill instances are stored locally (plans/actions in SQLite). `skills start --dry-run` and `skills adapt` without `--apply` never write to Apple apps.
```

- [ ] **Step 2: 更新 TODO.md**

「架构与产品审阅补充(2026-07-04)」一节中:
- **[高] Skills 引擎完整建成但与主链路零集成** 条目下追加一行:`  - 状态:2026-07-XX 已完成 runtime 接线(start/status/adapt + log --metric + dry-run reminder 类型),见 docs/superpowers/plans/2026-07-04-skills-runtime-wiring.md;剩余:trainer 统一(见下一条)。`(XX 填实际完成日期)
- **[中] trainer 与 skills 双轨计划机制重叠** 保留不动(明确为后续计划)。

- [ ] **Step 3: 全量验证**

Run: `scripts/verify.sh`
Expected: pytest 全部通过、compileall 通过、7 个 CLI --help smoke 通过、docs audit 正常输出。若 docs audit 对新计划文档报 warning(如陈旧阈值/内链),按其提示修复(通常无需处理,该命令只读不阻断)。

- [ ] **Step 4: 手动 smoke(Linux 上可跑的离线路径)**

```bash
.venv/bin/python -m nudge.cli skills list 2>/dev/null || bin/nudge skills list
bin/nudge skills dry-run strength-basics-12w --context /tmp/ctx.json --weeks 1
```
（`/tmp/ctx.json` 内容 `{"profile": {"start_date": "2026-07-06"}}`。）
Expected: list 输出 3 个内置 skill;dry-run 输出 4 条 W1 候选动作。`skills start` 的真实 Apple 写入只能在 macOS 上人工验证,交付说明中列为"未验证项"。

- [ ] **Step 5: Commit(需已获用户授权)+ 汇报**

```bash
git add README.md TODO.md docs/superpowers/plans/2026-07-04-skills-runtime-wiring.md
git commit -m "docs: skills 生命周期文档与 TODO 收尾

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

交付说明必须列出:完成项(Task 1-9)、验证命令与结果(verify.sh 输出摘要)、未验证项(macOS 真实 Apple 写入、交互式 assessment 的终端体验)、留在 TODO 的后续项(trainer 统一、do/agent 公共 API 提升重构)。

---

## Self-Review 记录

1. **范围覆盖**:实例化落库(Task 2+3+6)、assessment 交互(Task 6 `_run_assessment`)、tracking 闭环(Task 4+5+8)、reminder 类型扩展(Task 1)——四点全部有任务承接;trainer 统一显式列为范围外。
2. **占位符扫描**:全部步骤含完整代码/命令/预期输出;无 TBD/"补充测试"类占位。
3. **类型一致性**:`build_tracking_context(plan_id, metric_ids, *, today)` 在 Task 4 定义、Task 7(`()`)与 Task 8(`numeric_metric_ids(skill)`)按同签名消费;`_materialize_actions` Task 6 定义、Task 8 复用;`record_materialized_week`/`get_skill_instance`/`create_skill_instance`/`skill_weeks_total` 签名在 Task 3 与 Task 6/8 一致;dry-run 动作字段(`week`/`start`/`end`/`type`/`summary`/`duration_minutes`)与 Task 1 产出一致。
4. **已知风险**:`skills.py` import `commands.do` 沿用 agent.py 既有模式(隐式耦合债务已在 TODO 记录,不在本计划扩散);测试依赖内置 skill `strength-basics-12w` 的 personalization 规则(`never → 3 sessions/week`),若内置 skill 改动需同步测试。
