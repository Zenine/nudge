# Legacy Reminder List Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增默认只读、确认后仅回填本地 `actions.reminder_list` 的 `nudge reminders backfill-lists`，用全局一对一唯一匹配收敛 legacy action 的多列表同步风险。

**Architecture:** 把列表配置解析、legacy action 选择和匹配规划放进新的纯函数模块 `nudge/reminder_lists.py`；EventKit 只增加按到期日读取已完成与未完成 Reminder 的模式；SQLite 通过快照校验和单事务条件更新写入。Click 命令放在独立模块中，负责查询编排、统一确认、自动备份和稳定输出，不持有 Apple mutation 能力。

**Tech Stack:** Python 3.12+、Click、SQLite、EventKit Swift helper、pytest、现有 `nudge.cli.v1` JSON 契约。

---

## 文件结构

- Create: `docs/superpowers/plans/2026-07-19-reminder-list-backfill.md` — 已批准设计的可执行 TDD 计划。
- Create: `nudge/reminder_lists.py` — 列表配置解析、legacy action 选择、全局一对一匹配规划。
- Create: `nudge/commands/reminder_list_backfill.py` — `backfill-lists` Click 命令、Apple 只读查询编排、确认、备份和输出。
- Create: `tests/test_reminder_list_backfill.py` — 纯选择器和匹配规划器测试。
- Create: `tests/test_commands_reminder_list_backfill.py` — CLI dry-run、确认、备份和错误码测试。
- Create: `tests/test_state_reminder_list_backfill.py` — SQLite 快照冲突与原子回滚测试。
- Modify: `nudge/apple/eventkit_reminders_due_today.swift` — 新增 `all-due` 只读模式。
- Modify: `nudge/apple/reminders.py` — 新增 `query_all_due_on_date()` Python 包装。
- Modify: `nudge/state.py` — 新增列表 backfill 冲突类型和原子写入函数。
- Modify: `nudge/commands/reminders.py` — 注册新命令，并从共享模块导入 `resolve_sync_lists()`。
- Modify: `nudge/commands/daily.py` — 改从共享模块导入 `resolve_sync_lists()`。
- Modify: `tests/test_commands_reminders_multi_list.py` — 锁定列表配置解析迁移后行为。
- Modify: `tests/test_apple_reminders_safety.py` — 锁定 `all-due` 只读参数和最小字段解析。
- Modify: `README.md`、`docs/commands.md`、`docs/configuration.md`、`CHANGELOG.md`、`TODO.md` — 对齐能力、边界和完成记录。
- Modify: `scripts/verify.sh`、`tests/test_verify_script.py` — 增加新命令 CLI smoke。
- Modify: `docs/superpowers/specs/2026-07-19-reminder-list-backfill-design.md` — 实施完成后把状态改为已实现并验证。

### Task 0: 固化已批准设计与实施计划

**Files:**
- Create: `docs/superpowers/plans/2026-07-19-reminder-list-backfill.md`
- Modify: `docs/superpowers/specs/2026-07-19-reminder-list-backfill-design.md:1-7`

- [x] **Step 1: 确认设计状态已进入待执行**

The design header must contain this exact status:

```markdown
- 状态：整体设计已批准，实施计划已完成，待执行
```

- [x] **Step 2: 运行文档审计和工作树 diff 检查**

Run: `bin/nudge docs audit --json && git diff --check`

Expected: docs audit has zero errors; the existing historical TODO warning may remain; diff check exits with code 0.

- [x] **Step 3: 暂存、检查 staged diff 并提交计划文档**

```bash
git add docs/superpowers/plans/2026-07-19-reminder-list-backfill.md docs/superpowers/specs/2026-07-19-reminder-list-backfill-design.md
git diff --cached --check
git commit -m "docs: plan reminder list ownership backfill"
```

### Task 1: 共享列表解析、候选选择与全局匹配规划

**Files:**
- Create: `nudge/reminder_lists.py`
- Create: `tests/test_reminder_list_backfill.py`
- Modify: `nudge/commands/reminders.py:18-103`
- Modify: `nudge/commands/daily.py:12-13`
- Modify: `tests/test_commands_reminders_multi_list.py:13-24`

- [ ] **Step 1: 写入配置解析和候选选择失败测试**

```python
# tests/test_reminder_list_backfill.py
from datetime import date

import pytest

from nudge.reminder_lists import resolve_sync_lists, select_list_backfill_actions


def test_resolve_sync_lists_prefers_explicit_names_and_deduplicates():
    config = {"reminders": {"sync_lists": ["Tasks", "Health"]}}

    assert resolve_sync_lists(("GPT", "Tasks", "GPT"), config) == ["GPT", "Tasks"]
    assert resolve_sync_lists((), config) == ["Tasks", "Health"]


def test_select_list_backfill_actions_keeps_only_open_null_list_actions():
    actions = [
        {"id": "a", "type": "reminder", "summary": "A", "scheduled_at": "2026-07-02 09:00", "status": "pending", "reminder_list": None},
        {"id": "b", "type": "reminder", "summary": "B", "scheduled_at": "2026-07-01 09:00", "status": "created", "reminder_list": None},
        {"id": "before", "type": "reminder", "summary": "Before", "scheduled_at": "2026-06-30 23:59", "status": "pending", "reminder_list": None},
        {"id": "at-to", "type": "reminder", "summary": "At to", "scheduled_at": "2026-08-01 00:00", "status": "pending", "reminder_list": None},
        {"id": "closed", "type": "reminder", "summary": "C", "scheduled_at": "2026-07-01 10:00", "status": "done", "reminder_list": None},
        {"id": "owned", "type": "reminder", "summary": "D", "scheduled_at": "2026-07-01 11:00", "status": "pending", "reminder_list": "Tasks"},
        {"id": "invalid", "type": "reminder", "summary": "", "scheduled_at": "bad", "status": "pending", "reminder_list": None},
    ]

    batch = select_list_backfill_actions(
        actions,
        date_from=date(2026, 7, 1),
        date_to=date(2026, 8, 1),
        limit=1,
    )

    assert [item["id"] for item in batch.actions] == ["b"]
    assert batch.query_dates == (date(2026, 7, 1),)
    assert batch.total_eligible == 2
    assert batch.remaining == 1
    assert [item["id"] for item in batch.invalid] == ["invalid"]


@pytest.mark.parametrize("limit", [0, 501, True])
def test_select_list_backfill_actions_rejects_invalid_limit(limit):
    with pytest.raises(ValueError, match="limit must be between 1 and 500"):
        select_list_backfill_actions([], date_from=None, date_to=None, limit=limit)


def test_select_list_backfill_actions_defaults_to_100_and_allows_500():
    actions = [
        {
            "id": f"a-{index:03d}",
            "type": "reminder",
            "summary": f"Task {index}",
            "scheduled_at": "2026-07-20 09:00",
            "status": "pending",
            "reminder_list": None,
        }
        for index in range(501)
    ]

    default_batch = select_list_backfill_actions(actions, date_from=None, date_to=None)
    max_batch = select_list_backfill_actions(actions, date_from=None, date_to=None, limit=500)

    assert len(default_batch.actions) == 100
    assert default_batch.remaining == 401
    assert len(max_batch.actions) == 500
    assert max_batch.remaining == 1


@pytest.mark.parametrize(
    "scheduled_at",
    [
        " 2026-07-20 09:00",
        "2026-07-20 09:00 ",
        "2026-07-20 09:00 trailing",
        "2026-07-20 09:00:00",
        "2026-07-20 09:00+08:00",
        "2026-07-20T09:00Z",
    ],
)
def test_select_list_backfill_actions_rejects_noncanonical_minutes(scheduled_at):
    action = {
        "id": "invalid-minute",
        "type": "reminder",
        "summary": "Legacy",
        "scheduled_at": scheduled_at,
        "status": "pending",
        "reminder_list": None,
    }

    batch = select_list_backfill_actions([action], date_from=None, date_to=None)

    assert batch.actions == []
    assert batch.query_dates == ()
    assert [item["id"] for item in batch.invalid] == ["invalid-minute"]
```

- [ ] **Step 2: 运行选择器测试并确认因模块不存在而失败**

Run: `python3 -m pytest tests/test_reminder_list_backfill.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'nudge.reminder_lists'`.

- [ ] **Step 3: 实现共享列表解析和候选选择**

```python
# nudge/reminder_lists.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from nudge.action_hygiene import normalize_reminder_title
from nudge.config import DEFAULT_REMINDER_LIST, get_defaults


@dataclass(frozen=True)
class ReminderListBackfillBatch:
    actions: list[dict[str, Any]]
    query_dates: tuple[date, ...]
    invalid: list[dict[str, Any]]
    total_eligible: int
    remaining: int


def resolve_sync_lists(explicit_names, config: dict) -> list[str]:
    configured = (config.get("reminders") or {}).get("sync_lists")
    if explicit_names:
        raw_names = list(explicit_names)
    elif configured is not None:
        if not isinstance(configured, list):
            raise ValueError("[reminders].sync_lists must be an array of list names")
        raw_names = configured
    else:
        raw_names = [get_defaults(config).get("default_reminder_list", DEFAULT_REMINDER_LIST)]

    result: list[str] = []
    for raw_name in raw_names:
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError("reminder list names must be non-empty strings")
        name = raw_name.strip()
        if name not in result:
            result.append(name)
    if not result:
        raise ValueError("at least one reminder list is required")
    return result


def select_list_backfill_actions(
    actions: Iterable[dict[str, Any]],
    *,
    date_from: date | None,
    date_to: date | None,
    limit: int = 100,
) -> ReminderListBackfillBatch:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if date_from and date_to and date_to <= date_from:
        raise ValueError("--to must be later than --from")

    eligible: list[tuple[datetime, dict[str, Any]]] = []
    invalid: list[dict[str, Any]] = []
    for raw in actions:
        if not isinstance(raw, dict) or raw.get("type") != "reminder":
            continue
        if raw.get("status") not in {"created", "pending"}:
            continue
        if raw.get("reminder_list") not in (None, ""):
            continue
        action = dict(raw)
        if action.get("reminder_list") == "":
            invalid.append(_invalid_item(action, "empty_reminder_list"))
            continue
        scheduled = parse_strict_minute(action.get("scheduled_at"))
        summary = action.get("summary")
        if scheduled is None or not isinstance(summary, str) or not summary.strip():
            invalid.append(_invalid_item(action, "invalid_summary_or_scheduled_at"))
            continue
        scheduled_date = scheduled.date()
        if date_from and scheduled_date < date_from:
            continue
        if date_to and scheduled_date >= date_to:
            continue
        eligible.append((scheduled, action))

    eligible.sort(key=lambda item: (item[0], str(item[1].get("id") or "")))
    selected = eligible[:limit]
    return ReminderListBackfillBatch(
        actions=[action for _, action in selected],
        query_dates=tuple(sorted({scheduled.date() for scheduled, _ in selected})),
        invalid=invalid,
        total_eligible=len(eligible),
        remaining=max(0, len(eligible) - limit),
    )


def _invalid_item(action: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "id": action.get("id"),
        "summary": action.get("summary"),
        "scheduled_at": action.get("scheduled_at"),
        "reason": reason,
    }


def parse_strict_minute(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) != 16:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return parsed if parsed.strftime("%Y-%m-%d %H:%M") == value else None
```

- [ ] **Step 4: 把现有调用方改为共享解析函数并删除命令层副本**

```python
# nudge/commands/reminders.py imports
from nudge.reminder_lists import resolve_sync_lists

# 删除原 resolve_sync_lists() 定义。

# nudge/commands/daily.py imports
from nudge.commands.reminders import sync_completed_for_date
from nudge.reminder_lists import resolve_sync_lists
```

- [ ] **Step 5: 运行选择器及现有多列表测试**

Run: `python3 -m pytest tests/test_reminder_list_backfill.py tests/test_commands_reminders_multi_list.py -q`

Expected: PASS.

- [ ] **Step 6: 写入全局匹配失败测试**

```python
# append to tests/test_reminder_list_backfill.py
from nudge.reminder_lists import plan_list_backfill


def _action(action_id: str, summary: str, at: str) -> dict:
    return {"id": action_id, "type": "reminder", "summary": summary, "scheduled_at": at, "status": "pending", "reminder_list": None}


def _apple(row_key: str, name: str, at: str, list_name: str) -> dict:
    return {"row_key": row_key, "name": name, "due_at": at, "due_time": at[11:16], "list": list_name}


def test_plan_list_backfill_accepts_exact_and_trailing_date_normalization():
    actions = [
        _action("exact", "Buy book", "2026-07-20 09:00"),
        _action("normalized", "Review plan 2026-07-20 10:00", "2026-07-20 10:00"),
    ]
    rows = [
        _apple("Tasks:0", "Buy book", "2026-07-20 09:00", "Tasks"),
        _apple("Health:0", "Review plan", "2026-07-20 10:00", "Health"),
    ]

    report = plan_list_backfill(actions, rows)

    assert [(item["id"], item["target_list"], item["match_type"]) for item in report["candidates"]] == [
        ("exact", "Tasks", "exact_title"),
        ("normalized", "Health", "normalized_trailing_date"),
    ]


def test_plan_list_backfill_marks_cross_list_duplicates_ambiguous():
    action = _action("a", "Same", "2026-07-20 09:00")
    rows = [
        _apple("Tasks:0", "Same", "2026-07-20 09:00", "Tasks"),
        _apple("Health:0", "Same", "2026-07-20 09:00", "Health"),
    ]

    report = plan_list_backfill([action], rows)

    assert report["candidates"] == []
    assert report["ambiguous"][0]["id"] == "a"
    assert report["ambiguous"][0]["matched_lists"] == ["Health", "Tasks"]


def test_plan_list_backfill_preserves_same_list_duplicate_rows():
    action = _action("a", "Same", "2026-07-20 09:00")
    rows = [
        _apple("Tasks:0", "Same", "2026-07-20 09:00", "Tasks"),
        _apple("Tasks:1", "Same", "2026-07-20 09:00", "Tasks"),
    ]

    report = plan_list_backfill([action], rows)

    assert report["candidates"] == []
    assert report["ambiguous"][0]["matches"] == 2


def test_plan_list_backfill_rejects_two_actions_claiming_one_apple_row():
    actions = [
        _action("a", "Same", "2026-07-20 09:00"),
        _action("b", "Same 2026-07-20 09:00", "2026-07-20 09:00"),
    ]
    report = plan_list_backfill(actions, [_apple("Tasks:0", "Same", "2026-07-20 09:00", "Tasks")])

    assert report["candidates"] == []
    assert {item["id"] for item in report["ambiguous"]} == {"a", "b"}


def test_plan_list_backfill_requires_exact_minute():
    report = plan_list_backfill(
        [_action("a", "Same", "2026-07-20 09:00")],
        [_apple("Tasks:0", "Same", "2026-07-20 09:01", "Tasks")],
    )

    assert report["candidates"] == []
    assert report["missing"][0]["id"] == "a"


@pytest.mark.parametrize(
    "noncanonical",
    [
        " 2026-07-20 09:00",
        "2026-07-20 09:00 ",
        "2026-07-20 09:00 trailing",
        "2026-07-20 09:00:00",
        "2026-07-20 09:00+08:00",
        "2026-07-20T09:00Z",
    ],
)
def test_plan_list_backfill_rejects_noncanonical_action_and_apple_minutes(noncanonical):
    canonical_action = _action("action", "Same", "2026-07-20 09:00")
    canonical_row = _apple("Tasks:0", "Same", "2026-07-20 09:00", "Tasks")

    bad_action = plan_list_backfill(
        [{**canonical_action, "scheduled_at": noncanonical}],
        [canonical_row],
    )
    bad_row = plan_list_backfill(
        [canonical_action],
        [{**canonical_row, "due_at": noncanonical}],
    )

    assert bad_action["candidates"] == []
    assert bad_row["candidates"] == []
```

- [ ] **Step 7: 运行匹配测试并确认因函数不存在而失败**

Run: `python3 -m pytest tests/test_reminder_list_backfill.py -q`

Expected: FAIL with `ImportError: cannot import name 'plan_list_backfill'`.

- [ ] **Step 8: 实现全局一对一匹配规划器**

```python
# append to nudge/reminder_lists.py
def plan_list_backfill(
    actions: Iterable[dict[str, Any]],
    apple_rows: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    action_list = [dict(action) for action in actions]
    row_list = [dict(row) for row in apple_rows]
    matches_by_action: dict[str, list[tuple[int, str]]] = {}
    claimants_by_row: dict[int, list[str]] = {}

    for action in action_list:
        action_id = str(action.get("id") or "")
        matches: list[tuple[int, str]] = []
        for index, row in enumerate(row_list):
            match_type = _match_type(action, row)
            if match_type:
                matches.append((index, match_type))
                claimants_by_row.setdefault(index, []).append(action_id)
        matches_by_action[action_id] = matches

    candidates: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    for action in action_list:
        action_id = str(action.get("id") or "")
        matches = matches_by_action[action_id]
        base = _action_output(action)
        if not matches:
            missing.append(base)
            continue
        if len(matches) != 1 or len(claimants_by_row[matches[0][0]]) != 1:
            ambiguous.append({
                **base,
                "matched_lists": sorted({str(row_list[index].get("list") or "") for index, _ in matches}),
                "matches": len(matches),
            })
            continue
        row_index, match_type = matches[0]
        row = row_list[row_index]
        candidates.append({
            **base,
            "current_reminder_list": None,
            "target_list": row["list"],
            "match_type": match_type,
        })
    return {"candidates": candidates, "missing": missing, "ambiguous": ambiguous}


def _match_type(action: dict[str, Any], row: dict[str, Any]) -> str | None:
    scheduled = parse_strict_minute(action.get("scheduled_at"))
    due = parse_strict_minute(row.get("due_at"))
    if scheduled is None or due is None or due != scheduled:
        return None
    scheduled_at = scheduled.strftime("%Y-%m-%d %H:%M")
    due_at = due.strftime("%Y-%m-%d %H:%M")
    summary = str(action.get("summary") or "")
    name = str(row.get("name") or "")
    if name == summary:
        return "exact_title"
    normalized_name = normalize_reminder_title(name, due_at)
    normalized_summary = normalize_reminder_title(summary, scheduled_at)
    if normalized_name and normalized_summary and normalized_name == normalized_summary:
        return "normalized_trailing_date"
    return None


def _action_output(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": action.get("id"),
        "summary": action.get("summary"),
        "scheduled_at": action.get("scheduled_at"),
        "status": action.get("status"),
    }
```

- [ ] **Step 9: 运行 Task 1 测试**

Run: `python3 -m pytest tests/test_reminder_list_backfill.py tests/test_commands_reminders_multi_list.py -q`

Expected: PASS.

- [ ] **Step 10: 运行提交前完整验证**

Run: `scripts/verify.sh`

Expected: all pytest, compile, CLI smoke, docs audit, packaging and public-safe content checks PASS.

- [ ] **Step 11: 提交 Task 1**

```bash
git add nudge/reminder_lists.py nudge/commands/reminders.py nudge/commands/daily.py tests/test_reminder_list_backfill.py tests/test_commands_reminders_multi_list.py
git commit -m "refactor: extract reminder list planning"
```

### Task 2: EventKit 按到期日读取全部 Reminder

**Files:**
- Modify: `nudge/apple/eventkit_reminders_due_today.swift:16-189`
- Modify: `nudge/apple/reminders.py:99-207`
- Modify: `tests/test_apple_reminders_safety.py`

- [ ] **Step 1: 写入 Python 包装与 Swift 契约失败测试**

```python
# append to tests/test_apple_reminders_safety.py
from datetime import date
from pathlib import Path
from subprocess import CompletedProcess


def test_query_all_due_on_date_uses_read_only_all_due_mode(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return CompletedProcess(
            cmd,
            0,
            (
                "Done\t09:00\tTasks\t2026-07-20 09:05\t2026-07-20 09:00\n"
                "Open\t10:00\tTasks\t\t2026-07-20 10:00\n"
            ),
            "",
        )

    monkeypatch.setattr(reminders.subprocess, "run", fake_run)

    ok, rows = reminders.query_all_due_on_date("Tasks", date(2026, 7, 20))

    assert ok is True
    assert calls[0][-1] == "all-due"
    assert rows == [
        {
            "name": "Done",
            "due_time": "09:00",
            "list": "Tasks",
            "completed_at": "2026-07-20 09:05",
            "due_at": "2026-07-20 09:00",
        },
        {
            "name": "Open",
            "due_time": "10:00",
            "list": "Tasks",
            "due_at": "2026-07-20 10:00",
        },
    ]


def test_eventkit_all_due_mode_is_read_only_and_filters_due_date():
    source = (Path(reminders.EVENTKIT_DUE_TODAY_SCRIPT)).read_text(encoding="utf-8")

    assert 'requestedMode != "all-due"' in source
    assert "predicateForReminders(in: calendars)" in source
    assert "dueDate < start || dueDate > end" in source
    assert "eventkit_reminders_mutate" not in source
```

- [ ] **Step 2: 运行测试并确认缺少查询函数**

Run: `python3 -m pytest tests/test_apple_reminders_safety.py -q`

Expected: FAIL with `AttributeError: module 'nudge.apple.reminders' has no attribute 'query_all_due_on_date'`.

- [ ] **Step 3: 为 Swift helper 增加 `all-due` 模式**

```swift
// nudge/apple/eventkit_reminders_due_today.swift
if !listOnly && requestedMode != "incomplete" && requestedMode != "completed" && requestedMode != "all-due" {
    fail("Invalid mode: \(requestedMode); expected incomplete, completed, or all-due", code: 4)
}

let predicate: NSPredicate
if requestedMode == "completed" {
    predicate = store.predicateForCompletedReminders(
        withCompletionDateStarting: start,
        ending: end,
        calendars: calendars
    )
} else if requestedMode == "all-due" {
    predicate = store.predicateForReminders(in: calendars)
} else {
    predicate = store.predicateForIncompleteReminders(
        withDueDateStarting: start,
        ending: end,
        calendars: calendars
    )
}
```

Replace the body of the `for reminder` loop with this complete filtering/output block. The new mode skips rows without a due date, while the two existing modes retain their current output behavior:

```swift
for reminder in reminders ?? [] {
    let title = sanitize(reminder.title ?? "")
    let list = sanitize(reminder.calendar.title)
    let dueDate = reminder.dueDateComponents?.date
    if requestedMode == "all-due" {
        guard let dueDate = dueDate else {
            continue
        }
        if dueDate < start || dueDate > end {
            continue
        }
    }
    let dueTime = dueDate.map { formatter.string(from: $0) } ?? ""
    let dueAt = dueDate.map { dueFormatter.string(from: $0) } ?? ""
    if requestedMode == "completed" || requestedMode == "all-due" {
        let completedAt = reminder.completionDate.map {
            completedFormatter.string(from: $0)
        } ?? ""
        rows.append("\(title)\t\(dueTime)\t\(list)\t\(completedAt)\t\(dueAt)")
    } else {
        rows.append("\(title)\t\(dueTime)\t\(list)\t\t\(dueAt)")
    }
}
```

- [ ] **Step 4: 增加 Python `query_all_due_on_date()`**

```python
# nudge/apple/reminders.py after query_completed_on_date()
def query_all_due_on_date(
    list_name: str,
    target_date,
    timeout: int = DEFAULT_READ_TIMEOUT,
) -> tuple[bool, list[dict] | str]:
    """Get completed and incomplete reminders due on one local date."""
    if not hasattr(target_date, "strftime"):
        return False, "target_date must be a date or datetime"
    cmd = [
        "/usr/bin/swift",
        str(EVENTKIT_DUE_TODAY_SCRIPT),
        list_name,
        target_date.strftime("%Y-%m-%d"),
        "all-due",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return False, "swift executable not found"
    except subprocess.TimeoutExpired:
        return False, "EventKit all-due reminder query timed out"
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or f"swift exited with code {result.returncode}"
        return False, error
    return True, _parse_due_today_rows(result.stdout)
```

- [ ] **Step 5: 运行 Apple 只读测试**

Run: `python3 -m pytest tests/test_apple_reminders_safety.py -q`

Expected: PASS.

- [ ] **Step 6: 运行提交前完整验证**

Run: `scripts/verify.sh`

Expected: all pytest, compile, CLI smoke, docs audit, packaging and public-safe content checks PASS.

- [ ] **Step 7: 提交 Task 2**

```bash
git add nudge/apple/eventkit_reminders_due_today.swift nudge/apple/reminders.py tests/test_apple_reminders_safety.py
git commit -m "feat: read all reminders due on a date"
```

### Task 3: SQLite 列表归属原子写入

**Files:**
- Modify: `nudge/state.py:58-76,628-729`
- Create: `tests/test_state_reminder_list_backfill.py`

- [ ] **Step 1: 写入成功、冲突和回滚失败测试**

```python
# tests/test_state_reminder_list_backfill.py
import sqlite3

import pytest

from nudge import state


def _pending(summary: str, at: str) -> str:
    return state.log_action("reminder", summary, scheduled_at=at, status="pending", reminder_list=None)


def test_apply_reminder_list_backfill_updates_only_list_field():
    action_id = _pending("Task", "2026-07-20 09:00")
    snapshot = state.get_action(action_id)

    applied = state.apply_reminder_list_backfill(
        [{"id": action_id, "target_list": "Tasks"}],
        snapshots={action_id: snapshot},
    )

    action = state.get_action(action_id)
    assert applied == [action_id]
    assert action["reminder_list"] == "Tasks"
    assert action["status"] == "pending"
    assert action["feedback"] is None
    assert action["external_id"] is None


def test_apply_reminder_list_backfill_rolls_back_whole_batch_on_conflict():
    first = _pending("First", "2026-07-20 09:00")
    second = _pending("Second", "2026-07-20 10:00")
    snapshots = {action_id: state.get_action(action_id) for action_id in (first, second)}
    with state._db() as conn:
        conn.execute("UPDATE actions SET reminder_list = 'Elsewhere' WHERE id = ?", (second,))

    with pytest.raises(state.ReminderListBackfillConflictError) as error:
        state.apply_reminder_list_backfill(
            [
                {"id": first, "target_list": "Tasks"},
                {"id": second, "target_list": "Health"},
            ],
            snapshots=snapshots,
        )

    assert error.value.action_ids == [second]
    assert state.get_action(first)["reminder_list"] is None
    assert state.get_action(second)["reminder_list"] == "Elsewhere"


def test_apply_reminder_list_backfill_rolls_back_on_sqlite_error():
    first = _pending("First SQL", "2026-07-20 11:00")
    second = _pending("Second SQL", "2026-07-20 12:00")
    snapshots = {action_id: state.get_action(action_id) for action_id in (first, second)}
    with state._db() as conn:
        conn.execute(
            f"""
            CREATE TRIGGER fail_reminder_list_backfill
            BEFORE UPDATE OF reminder_list ON actions
            WHEN NEW.id = '{second}'
            BEGIN
                SELECT RAISE(ABORT, 'forced backfill failure');
            END
            """
        )

    try:
        with pytest.raises(sqlite3.IntegrityError, match="forced backfill failure"):
            state.apply_reminder_list_backfill(
                [
                    {"id": first, "target_list": "Tasks"},
                    {"id": second, "target_list": "Health"},
                ],
                snapshots=snapshots,
            )
    finally:
        with state._db() as conn:
            conn.execute("DROP TRIGGER fail_reminder_list_backfill")

    assert state.get_action(first)["reminder_list"] is None
    assert state.get_action(second)["reminder_list"] is None


@pytest.mark.parametrize("target", ["", "   ", None, ["Tasks"]])
def test_apply_reminder_list_backfill_rejects_invalid_target(target):
    action_id = _pending("Task", "2026-07-20 09:00")
    with pytest.raises(ValueError, match="target_list"):
        state.apply_reminder_list_backfill(
            [{"id": action_id, "target_list": target}],
            snapshots={action_id: state.get_action(action_id)},
        )
```

- [ ] **Step 2: 运行测试并确认缺少状态函数**

Run: `python3 -m pytest tests/test_state_reminder_list_backfill.py -q`

Expected: FAIL with `AttributeError` for `apply_reminder_list_backfill`.

- [ ] **Step 3: 实现冲突类型和批量事务**

```python
# nudge/state.py near FeedbackInterviewConflictError
class ReminderListBackfillConflictError(RuntimeError):
    """Raised when one or more list-backfill snapshots are stale."""

    def __init__(self, action_ids: list[str]):
        self.action_ids = sorted(set(action_ids))
        super().__init__(f"reminder list backfill conflict: {', '.join(self.action_ids)}")


def apply_reminder_list_backfill(
    updates: list[dict],
    *,
    snapshots: dict[str, dict],
) -> list[str]:
    """Atomically assign reminder lists to unchanged legacy open actions."""
    if not isinstance(updates, list) or not updates:
        raise ValueError("reminder list backfill updates must be a non-empty list")
    if not isinstance(snapshots, dict):
        raise ValueError("reminder list backfill snapshots must be an object")

    prepared = []
    seen_ids = set()
    fields = ("type", "summary", "scheduled_at", "status", "reminder_list")
    for index, update in enumerate(updates, start=1):
        if not isinstance(update, dict):
            raise ValueError(f"updates[{index}] must be an object")
        action_id = str(update.get("id") or "").strip()
        target_list = update.get("target_list")
        if not action_id or action_id in seen_ids:
            raise ValueError(f"updates[{index}].id is missing or duplicated")
        if not isinstance(target_list, str) or not target_list.strip():
            raise ValueError(f"updates[{index}].target_list must be a non-empty string")
        snapshot = snapshots.get(action_id)
        if not isinstance(snapshot, dict):
            raise ValueError(f"missing snapshot for action: {action_id}")
        seen_ids.add(action_id)
        prepared.append({
            "id": action_id,
            "target_list": target_list.strip(),
            **{f"snapshot_{field}": snapshot.get(field) for field in fields},
        })

    conn = _get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in prepared)
        rows = conn.execute(
            f"SELECT id, type, summary, scheduled_at, status, reminder_list FROM actions WHERE id IN ({placeholders})",
            tuple(item["id"] for item in prepared),
        ).fetchall()
        current = {row["id"]: dict(row) for row in rows}
        conflicts = []
        for item in prepared:
            row = current.get(item["id"])
            if row is None or any(row[field] != item[f"snapshot_{field}"] for field in fields):
                conflicts.append(item["id"])
            elif row["type"] != "reminder" or row["status"] not in {"created", "pending"} or row["reminder_list"] is not None:
                conflicts.append(item["id"])
        if conflicts:
            raise ReminderListBackfillConflictError(conflicts)

        for item in prepared:
            cursor = conn.execute(
                """
                UPDATE actions SET reminder_list = ?
                WHERE id = ?
                  AND type IS ? AND summary IS ? AND scheduled_at IS ?
                  AND status IS ? AND reminder_list IS NULL
                """,
                (
                    item["target_list"], item["id"], item["snapshot_type"],
                    item["snapshot_summary"], item["snapshot_scheduled_at"], item["snapshot_status"],
                ),
            )
            if cursor.rowcount != 1:
                raise ReminderListBackfillConflictError([item["id"]])
        conn.commit()
        return [item["id"] for item in prepared]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

- [ ] **Step 4: 运行状态测试**

Run: `python3 -m pytest tests/test_state_reminder_list_backfill.py tests/test_state_initialization.py -q`

Expected: PASS.

- [ ] **Step 5: 运行提交前完整验证**

Run: `scripts/verify.sh`

Expected: all pytest, compile, CLI smoke, docs audit, packaging and public-safe content checks PASS.

- [ ] **Step 6: 提交 Task 3**

```bash
git add nudge/state.py tests/test_state_reminder_list_backfill.py
git commit -m "feat: atomically backfill reminder list ownership"
```

### Task 4: 默认只读的 `backfill-lists` CLI

**Files:**
- Create: `nudge/commands/reminder_list_backfill.py`
- Create: `tests/test_commands_reminder_list_backfill.py`
- Modify: `nudge/commands/reminders.py:37-43`

- [ ] **Step 1: 写入 dry-run、显式列表覆盖和查询失败测试**

```python
# tests/test_commands_reminder_list_backfill.py
import json
from pathlib import Path
import sqlite3

import click
from click.testing import CliRunner

from nudge.commands import reminder_list_backfill as command
from nudge.commands.reminders import reminders_command


ACTIONS = [{
    "id": "legacy",
    "type": "reminder",
    "summary": "Legacy",
    "scheduled_at": "2026-07-20 09:00",
    "status": "pending",
    "reminder_list": None,
}]


def test_backfill_lists_dry_run_uses_configured_lists_and_writes_nothing(monkeypatch):
    monkeypatch.setattr(command, "load_config", lambda path: {"reminders": {"sync_lists": ["Tasks", "Health"]}})
    monkeypatch.setattr(command, "get_actions", lambda: ACTIONS)
    monkeypatch.setattr(
        command,
        "query_all_due_on_date",
        lambda list_name, target_date: (
            True,
            [{
                "name": "Legacy",
                "due_time": "09:00",
                "due_at": "2026-07-20 09:00",
                "list": list_name,
                "notes": "MUST_NOT_LEAK",
            }]
            if list_name == "Tasks" else [],
        ),
    )
    monkeypatch.setattr(command, "backup_database", lambda: (_ for _ in ()).throw(AssertionError("backup called")))
    monkeypatch.setattr(command, "apply_reminder_list_backfill", lambda *a, **k: (_ for _ in ()).throw(AssertionError("write called")))

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["lists"] == ["Tasks", "Health"]
    assert payload["candidates"][0]["target_list"] == "Tasks"
    assert payload["updated"] == 0
    assert "MUST_NOT_LEAK" not in result.output


def test_emit_text_dry_run_shows_all_outcome_details_without_notes():
    payload = {
        "dry_run": True,
        "lists": ["Tasks"],
        "total_eligible": 4,
        "remaining": 0,
        "candidates": [{"id": "candidate-1", "summary": "Candidate", "scheduled_at": "2026-07-20 09:00", "target_list": "Tasks", "match_type": "exact_title", "notes": "MUST_NOT_LEAK"}],
        "missing": [{"id": "missing-1", "summary": "Missing", "scheduled_at": "2026-07-20 10:00", "notes": "MUST_NOT_LEAK"}],
        "ambiguous": [{"id": "ambiguous-1", "summary": "Ambiguous", "scheduled_at": "2026-07-20 11:00", "matches": 2, "matched_lists": ["Health", "Tasks"], "notes": "MUST_NOT_LEAK"}],
        "invalid": [{"id": "invalid-1", "summary": "Invalid", "scheduled_at": "bad", "reason": "invalid_summary_or_scheduled_at", "notes": "MUST_NOT_LEAK"}],
        "updated": 0,
        "backup": None,
        "conflicts": ["conflict-1"],
        "errors": [],
    }

    @click.command()
    def emit():
        command._emit(payload, False)

    result = CliRunner().invoke(emit)

    assert result.exit_code == 0, result.output
    for expected in (
        "DRY-RUN Reminder list backfill",
        "candidate id=candidate-1",
        "missing id=missing-1",
        "ambiguous id=ambiguous-1",
        "invalid id=invalid-1",
        "conflicts=conflict-1",
        "updated=0",
    ):
        assert expected in result.output
    assert "MUST_NOT_LEAK" not in result.output


def test_backfill_lists_repeated_list_overrides_config(monkeypatch):
    seen = []
    monkeypatch.setattr(command, "load_config", lambda path: {"reminders": {"sync_lists": ["Ignored"]}})
    monkeypatch.setattr(command, "get_actions", lambda: ACTIONS)
    monkeypatch.setattr(command, "query_all_due_on_date", lambda list_name, target_date: (seen.append(list_name) or True, []))

    result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--list", "GPT", "--list", "Tasks", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert seen == ["GPT", "Tasks"]


def test_backfill_lists_query_failure_disables_apply(monkeypatch):
    monkeypatch.setattr(command, "load_config", lambda path: {"reminders": {"sync_lists": ["Tasks"]}})
    monkeypatch.setattr(command, "get_actions", lambda: ACTIONS)
    monkeypatch.setattr(command, "query_all_due_on_date", lambda *args: (False, "permission denied"))

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["apply_allowed"] is False
    assert payload["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_QUERY_FAILED"


def test_backfill_lists_maps_config_and_range_errors_separately(monkeypatch):
    monkeypatch.setattr(command, "load_config", lambda path: (_ for _ in ()).throw(FileNotFoundError("missing")))

    config_result = CliRunner().invoke(reminders_command, ["backfill-lists", "--json"])
    range_result = CliRunner().invoke(
        reminders_command,
        ["backfill-lists", "--from", "not-a-date", "--json"],
    )

    assert config_result.exit_code == 1
    assert json.loads(config_result.output)["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_CONFIG_INVALID"
    assert range_result.exit_code == 1
    assert json.loads(range_result.output)["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_RANGE_INVALID"


def test_backfill_lists_rejects_yes_without_apply_before_query(monkeypatch):
    monkeypatch.setattr(command, "load_config", lambda path: (_ for _ in ()).throw(AssertionError("config read")))

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--yes", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output)["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_CONFIRMATION_INVALID"


def test_backfill_lists_maps_sqlite_read_failure_without_writing(monkeypatch):
    monkeypatch.setattr(command, "load_config", lambda path: {"reminders": {"sync_lists": ["Tasks"]}})
    monkeypatch.setattr(command, "get_actions", lambda: (_ for _ in ()).throw(sqlite3.Error("read failed")))

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output)["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_WRITE_FAILED"
```

- [ ] **Step 2: 运行 CLI 测试并确认命令不存在**

Run: `python3 -m pytest tests/test_commands_reminder_list_backfill.py -q`

Expected: FAIL because `backfill-lists` is not registered.

- [ ] **Step 3: 实现 CLI 查询编排和 dry-run payload**

```python
# nudge/commands/reminder_list_backfill.py
from __future__ import annotations

import json
import sqlite3
import sys
import tomllib
from datetime import date
from typing import Any

import click

from nudge.apple.reminders import query_all_due_on_date
from nudge.commands.db import backup_database
from nudge.config import load_config
from nudge.json_contract import versioned_payload
from nudge.reminder_lists import plan_list_backfill, resolve_sync_lists, select_list_backfill_actions
from nudge.state import (
    ReminderListBackfillConflictError,
    apply_reminder_list_backfill,
    configure_state,
    get_actions,
)


@click.command("backfill-lists")
@click.option("--from", "from_text", default=None, help="Include actions on/after YYYY-MM-DD")
@click.option("--to", "to_text", default=None, help="Exclude actions on/after YYYY-MM-DD")
@click.option("--list", "list_names", multiple=True, help="Reminder list; repeat to override config")
@click.option("--limit", "limit_text", default="100", show_default=True, metavar="1..500")
@click.option("--apply", "apply_changes", is_flag=True, help="Backfill local SQLite after confirmation")
@click.option("--yes", "assume_yes", is_flag=True, help="Skip interactive confirmation for --apply")
@click.option("--config", "-c", "config_path", default=None, help="Config file path")
@click.option("--json", "json_output", is_flag=True, help="Print stable JSON")
def backfill_lists_command(from_text, to_text, list_names, limit_text, apply_changes, assume_yes, config_path, json_output):
    """Backfill legacy reminder list ownership in local SQLite only."""
    if assume_yes and not apply_changes:
        payload = _error_payload(
            "REMINDER_LIST_BACKFILL_CONFIRMATION_INVALID",
            "--yes requires --apply",
            dry_run=True,
        )
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)
    try:
        date_from = date.fromisoformat(from_text) if from_text else None
        date_to = date.fromisoformat(to_text) if to_text else None
        limit = int(limit_text)
        if not 1 <= limit <= 500:
            raise ValueError("--limit must be between 1 and 500")
        if date_from and date_to and date_to <= date_from:
            raise ValueError("--to must be later than --from")
    except ValueError as exc:
        payload = _error_payload("REMINDER_LIST_BACKFILL_RANGE_INVALID", str(exc), dry_run=not apply_changes)
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)

    try:
        config = load_config(config_path)
        reminder_lists = resolve_sync_lists(list_names, config)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        payload = _error_payload("REMINDER_LIST_BACKFILL_CONFIG_INVALID", str(exc), dry_run=not apply_changes)
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)

    configure_state(config)
    try:
        payload, snapshots = _build_backfill_report(
            date_from=date_from,
            date_to=date_to,
            reminder_lists=reminder_lists,
            limit=limit,
        )
    except sqlite3.Error:
        payload = _error_payload(
            "REMINDER_LIST_BACKFILL_WRITE_FAILED",
            "SQLite read failed before any write",
            dry_run=not apply_changes,
        )
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)

    if not payload["ok"]:
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)
    payload["dry_run"] = not apply_changes
    _emit(payload, json_output)


def _build_backfill_report(*, date_from, date_to, reminder_lists, limit):
    batch = select_list_backfill_actions(get_actions(), date_from=date_from, date_to=date_to, limit=limit)
    apple_rows: list[dict[str, Any]] = []
    errors = []
    for list_name in reminder_lists:
        for target_date in batch.query_dates:
            ok, rows = query_all_due_on_date(list_name, target_date)
            if not ok:
                errors.append({
                    "code": "REMINDER_LIST_BACKFILL_QUERY_FAILED",
                    "list": list_name,
                    "date": target_date.isoformat(),
                    "message": str(rows),
                })
                continue
            for index, row in enumerate(rows):
                apple_rows.append({**row, "row_key": f"{list_name}:{target_date.isoformat()}:{index}"})
    planned = plan_list_backfill(batch.actions, apple_rows)
    snapshots = {str(action["id"]): action for action in batch.actions}
    payload = versioned_payload({
        "ok": not errors,
        "dry_run": True,
        "apply_allowed": not errors,
        "lists": reminder_lists,
        "range": {"from": date_from.isoformat() if date_from else None, "to": date_to.isoformat() if date_to else None},
        "limit": limit,
        "total_eligible": batch.total_eligible,
        "remaining": batch.remaining,
        **planned,
        "invalid": batch.invalid,
        "updated": 0,
        "backup": None,
        "conflicts": [],
        "errors": errors,
    })
    return payload, snapshots


def _error_payload(code: str, message: str, *, dry_run: bool) -> dict:
    return versioned_payload({
        "ok": False, "dry_run": dry_run, "apply_allowed": False,
        "lists": [], "range": {"from": None, "to": None}, "limit": 0,
        "total_eligible": 0, "remaining": 0, "candidates": [], "missing": [],
        "ambiguous": [], "invalid": [], "updated": 0, "backup": None,
        "conflicts": [], "errors": [{"code": code, "message": message}],
    })


def _emit(payload: dict, json_output: bool) -> None:
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    mode = "DRY-RUN" if payload.get("dry_run") else "APPLY"
    click.echo(f"{mode} Reminder list backfill · lists={', '.join(payload.get('lists') or [])}")
    click.echo(
        f"  eligible={payload.get('total_eligible')} candidates={len(payload.get('candidates') or [])} "
        f"missing={len(payload.get('missing') or [])} ambiguous={len(payload.get('ambiguous') or [])} "
        f"invalid={len(payload.get('invalid') or [])} remaining={payload.get('remaining')}"
    )
    click.echo(f"  updated={payload.get('updated', 0)}")
    backup = payload.get("backup")
    if backup:
        click.echo(f"  backup={backup.get('path')} integrity={backup.get('integrity_check')}")
    conflicts = payload.get("conflicts") or []
    if conflicts:
        click.echo(f"  conflicts={', '.join(str(item) for item in conflicts)}")
    for candidate in payload.get("candidates") or []:
        click.echo(
            f"  candidate id={candidate.get('id')} scheduled_at={candidate.get('scheduled_at')} "
            f"summary={candidate.get('summary')} target_list={candidate.get('target_list')} "
            f"match_type={candidate.get('match_type')}"
        )
    for missing in payload.get("missing") or []:
        click.echo(
            f"  missing id={missing.get('id')} scheduled_at={missing.get('scheduled_at')} "
            f"summary={missing.get('summary')}"
        )
    for ambiguous in payload.get("ambiguous") or []:
        click.echo(
            f"  ambiguous id={ambiguous.get('id')} scheduled_at={ambiguous.get('scheduled_at')} "
            f"summary={ambiguous.get('summary')} matches={ambiguous.get('matches')} "
            f"matched_lists={', '.join(ambiguous.get('matched_lists') or [])}"
        )
    for invalid in payload.get("invalid") or []:
        click.echo(
            f"  invalid id={invalid.get('id')} scheduled_at={invalid.get('scheduled_at')} "
            f"summary={invalid.get('summary')} reason={invalid.get('reason')}"
        )
    for error in payload.get("errors") or []:
        click.echo(f"  error {error['code']}: {error['message']}", err=True)
```

Register the command without a circular import:

```python
# nudge/commands/reminders.py imports
from nudge.commands.reminder_list_backfill import backfill_lists_command

# immediately after reminders_command definition
reminders_command.add_command(backfill_lists_command)
```

- [ ] **Step 4: 运行 CLI dry-run 测试**

Run: `python3 -m pytest tests/test_commands_reminder_list_backfill.py -q`

Expected: PASS for dry-run tests.

- [ ] **Step 5: 运行提交前完整验证**

Run: `scripts/verify.sh`

Expected: all pytest, compile, CLI smoke, docs audit, packaging and public-safe content checks PASS.

- [ ] **Step 6: 提交 Task 4**

```bash
git add nudge/commands/reminder_list_backfill.py nudge/commands/reminders.py tests/test_commands_reminder_list_backfill.py
git commit -m "feat: add reminder list backfill dry run"
```

### Task 5: 确认、自动备份和原子 apply

**Files:**
- Modify: `nudge/commands/reminder_list_backfill.py`
- Modify: `tests/test_commands_reminder_list_backfill.py`

- [ ] **Step 1: 写入确认、备份、冲突和零候选测试**

```python
# append to tests/test_commands_reminder_list_backfill.py
def _install_apply_fakes(monkeypatch, *, candidates=True):
    monkeypatch.setattr(command, "load_config", lambda path: {"reminders": {"sync_lists": ["Tasks"]}})
    monkeypatch.setattr(command, "get_actions", lambda: ACTIONS if candidates else [])
    monkeypatch.setattr(
        command,
        "query_all_due_on_date",
        lambda *args: (True, [{"name": "Legacy", "due_time": "09:00", "due_at": "2026-07-20 09:00", "list": "Tasks", "notes": "MUST_NOT_LEAK"}]),
    )


def test_backfill_lists_noninteractive_apply_requires_yes(monkeypatch):
    _install_apply_fakes(monkeypatch)
    monkeypatch.setattr(command, "_is_interactive_terminal", lambda: False)

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--apply", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output)["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_CONFIRMATION_REQUIRED"


def test_backfill_lists_apply_backs_up_before_atomic_write(monkeypatch, tmp_path):
    _install_apply_fakes(monkeypatch)
    calls = []
    backup = tmp_path / "nudge.db"
    monkeypatch.setattr(command, "backup_database", lambda: (calls.append("backup") or backup))
    monkeypatch.setattr(command, "apply_reminder_list_backfill", lambda updates, snapshots: (calls.append("apply") or ["legacy"]))

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--apply", "--yes", "--json"])

    assert result.exit_code == 0, result.output
    assert calls == ["backup", "apply"]
    payload = json.loads(result.output)
    assert payload["updated"] == 1
    assert payload["backup"]["path"] == str(backup)


def test_backfill_lists_text_apply_reports_candidate_update_and_backup_without_notes(monkeypatch, tmp_path):
    _install_apply_fakes(monkeypatch)
    backup = tmp_path / "nudge.db"
    monkeypatch.setattr(command, "backup_database", lambda: backup)
    monkeypatch.setattr(command, "apply_reminder_list_backfill", lambda updates, snapshots: ["legacy"])

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--apply", "--yes"])

    assert result.exit_code == 0, result.output
    assert "APPLY Reminder list backfill" in result.output
    assert "candidate id=legacy" in result.output
    assert "updated=1" in result.output
    assert f"backup={backup}" in result.output
    assert "integrity=ok" in result.output
    assert "MUST_NOT_LEAK" not in result.output


def test_backfill_lists_backup_failure_writes_nothing(monkeypatch):
    _install_apply_fakes(monkeypatch)
    monkeypatch.setattr(command, "backup_database", lambda: (_ for _ in ()).throw(RuntimeError("disk full")))
    monkeypatch.setattr(command, "apply_reminder_list_backfill", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("write called")))

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--apply", "--yes", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output)["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_BACKUP_FAILED"


def test_backfill_lists_conflict_returns_ids_and_zero_updates(monkeypatch, tmp_path):
    _install_apply_fakes(monkeypatch)
    monkeypatch.setattr(command, "backup_database", lambda: tmp_path / "backup.db")
    monkeypatch.setattr(
        command,
        "apply_reminder_list_backfill",
        lambda *args, **kwargs: (_ for _ in ()).throw(command.ReminderListBackfillConflictError(["legacy"])),
    )

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--apply", "--yes", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["errors"][0]["code"] == "REMINDER_LIST_BACKFILL_CONFLICT"
    assert payload["conflicts"] == ["legacy"]
    assert payload["updated"] == 0


def test_backfill_lists_apply_with_zero_candidates_skips_backup(monkeypatch):
    _install_apply_fakes(monkeypatch, candidates=False)
    monkeypatch.setattr(command, "backup_database", lambda: (_ for _ in ()).throw(AssertionError("backup called")))

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--apply", "--yes", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["updated"] == 0


def test_backfill_lists_interactive_cancel_skips_backup_and_write(monkeypatch):
    _install_apply_fakes(monkeypatch)
    monkeypatch.setattr(command, "_is_interactive_terminal", lambda: True)
    monkeypatch.setattr(command, "backup_database", lambda: (_ for _ in ()).throw(AssertionError("backup called")))
    monkeypatch.setattr(command, "apply_reminder_list_backfill", lambda *a, **k: (_ for _ in ()).throw(AssertionError("write called")))

    result = CliRunner().invoke(reminders_command, ["backfill-lists", "--apply"], input="n\n")

    assert result.exit_code == 1
    assert "REMINDER_LIST_BACKFILL_CANCELLED" in result.output


def test_backfill_command_has_no_apple_mutation_imports():
    source = Path(command.__file__).read_text(encoding="utf-8")

    for forbidden in (
        "complete_reminder",
        "delete_reminder",
        "set_reminder_external_id",
        "create_reminder",
    ):
        assert forbidden not in source
```

- [ ] **Step 2: 运行 apply 测试并确认当前命令未写入**

Run: `python3 -m pytest tests/test_commands_reminder_list_backfill.py -q`

Expected: FAIL because `--apply` still only emits the dry-run report.

- [ ] **Step 3: 实现确认、备份和错误映射**

Replace the success tail of `backfill_lists_command()` after `_build_backfill_report()` with:

```python
    if not payload["ok"]:
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)
    if not apply_changes:
        _emit(payload, json_output)
        return
    payload["dry_run"] = False
    if not payload["candidates"]:
        _emit(payload, json_output)
        return
    if not assume_yes:
        if json_output or not _is_interactive_terminal():
            payload = _with_error(
                payload,
                "REMINDER_LIST_BACKFILL_CONFIRMATION_REQUIRED",
                "non-interactive --apply requires --yes",
            )
            _emit(payload, json_output)
            raise click.exceptions.Exit(1)
        _emit(payload, False)
        if not click.confirm("确认仅回填以上 Nudge SQLite reminder_list？", default=False):
            payload = _with_error(payload, "REMINDER_LIST_BACKFILL_CANCELLED", "cancelled by user")
            _emit(payload, json_output)
            raise click.exceptions.Exit(1)

    try:
        backup_path = backup_database()
    except Exception as exc:
        payload = _with_error(payload, "REMINDER_LIST_BACKFILL_BACKUP_FAILED", str(exc))
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)
    payload["backup"] = {"path": str(backup_path), "integrity_check": "ok"}
    updates = [{"id": item["id"], "target_list": item["target_list"]} for item in payload["candidates"]]
    try:
        applied = apply_reminder_list_backfill(updates, snapshots=snapshots)
    except ReminderListBackfillConflictError as exc:
        payload["conflicts"] = exc.action_ids
        payload = _with_error(payload, "REMINDER_LIST_BACKFILL_CONFLICT", "action changed after candidate planning")
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)
    except ValueError as exc:
        payload = _with_error(payload, "REMINDER_LIST_BACKFILL_WRITE_FAILED", str(exc))
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)
    except Exception:
        payload = _with_error(payload, "REMINDER_LIST_BACKFILL_WRITE_FAILED", "SQLite batch write failed and rolled back")
        _emit(payload, json_output)
        raise click.exceptions.Exit(1)
    payload["updated"] = len(applied)
    _emit(payload, json_output)
```

Add the helpers:

```python
def _is_interactive_terminal() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _with_error(payload: dict, code: str, message: str) -> dict:
    updated = dict(payload)
    updated["ok"] = False
    updated["apply_allowed"] = False
    updated["updated"] = 0
    updated["errors"] = [*payload.get("errors", []), {"code": code, "message": message}]
    return updated
```

- [ ] **Step 4: 运行 CLI 完整测试**

Run: `python3 -m pytest tests/test_commands_reminder_list_backfill.py tests/test_state_reminder_list_backfill.py -q`

Expected: PASS.

- [ ] **Step 5: 运行所有 reminder 安全回归测试**

Run: `python3 -m pytest tests/test_commands_reminders_multi_list.py tests/test_apple_reminders_safety.py tests/test_commands_reminder_list_backfill.py -q`

Expected: PASS.

- [ ] **Step 6: 运行提交前完整验证**

Run: `scripts/verify.sh`

Expected: all pytest, compile, CLI smoke, docs audit, packaging and public-safe content checks PASS.

- [ ] **Step 7: 提交 Task 5**

```bash
git add nudge/commands/reminder_list_backfill.py tests/test_commands_reminder_list_backfill.py
git commit -m "feat: confirm and back up reminder list backfill"
```

### Task 6: 能力文档与验证工作流

**Files:**
- Modify: `README.md`
- Modify: `docs/commands.md`
- Modify: `docs/configuration.md`
- Modify: `scripts/verify.sh`
- Modify: `tests/test_verify_script.py`

- [ ] **Step 1: 写入 CLI smoke 失败测试**

```python
# append to tests/test_verify_script.py
def test_verify_script_smokes_reminder_list_backfill_help():
    content = VERIFY.read_text(encoding="utf-8")

    assert "bin/nudge reminders backfill-lists --help" in content
```

- [ ] **Step 2: 运行测试并确认 smoke 尚未加入**

Run: `python3 -m pytest tests/test_verify_script.py::test_verify_script_smokes_reminder_list_backfill_help -q`

Expected: FAIL on the missing command string.

- [ ] **Step 3: 更新验证脚本**

```bash
# scripts/verify.sh, CLI smoke section
run bin/nudge reminders backfill-lists --help >/dev/null
```

- [ ] **Step 4: 更新 README、命令和配置文档**

Add these exact behavior points:

```markdown
`nudge reminders backfill-lists` 默认只读 `[reminders].sync_lists`，只为仍未闭环且 `reminder_list IS NULL` 的 legacy action 规划列表归属。匹配要求标题（或仅去除尾部重复日期后的标题）与到期分钟一致，并且在全部候选列表中一对一唯一。

`--apply` 只更新 Nudge SQLite，不修改 Apple Reminders；TTY 统一确认后自动创建完整性备份，非交互调用必须显式追加 `--yes`。零匹配和歧义项保持不变。
```

Place the command examples in `docs/commands.md`:

```bash
nudge reminders backfill-lists --json
nudge reminders backfill-lists --list Tasks --list Health --from 2026-07-01 --to 2026-08-01 --json
nudge reminders backfill-lists --apply
```

Do not remove the TODO, add the final CHANGELOG completion record, or mark the design fully verified in this task. Those completion claims belong to Task 7 only after full verification and read-only Dogfood pass.

- [ ] **Step 5: 运行文档和验证脚本测试**

Run: `python3 -m pytest tests/test_verify_script.py -q && bin/nudge docs audit --json`

Expected: tests PASS; docs audit has zero errors. The existing historical TODO warning may remain until its separate cleanup task.

- [ ] **Step 6: 运行提交前完整验证**

Run: `scripts/verify.sh`

Expected: all pytest, compile, CLI smoke, docs audit, packaging and public-safe content checks PASS.

- [ ] **Step 7: 提交 Task 6**

```bash
git add README.md docs/commands.md docs/configuration.md scripts/verify.sh tests/test_verify_script.py
git commit -m "docs: document reminder list ownership backfill"
```

### Task 7: 完整验证、真实配置只读 Dogfood 与最终收尾

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `TODO.md`
- Modify: `docs/superpowers/specs/2026-07-19-reminder-list-backfill-design.md`

- [ ] **Step 1: 固定分支基线，检查完整分支 diff 与隐私边界**

Run this from the repository root. `BASE` is the explicit integration-base commit for every later `BASE..HEAD` check:

```bash
BASE="$(git merge-base HEAD main)"
test -n "$BASE"
export BASE
git diff --check "$BASE"..HEAD
git status --short
python3 - <<'PY'
from pathlib import Path
import os
import re
import subprocess

base = os.environ["BASE"]
diff_range = f"{base}..HEAD"
names = subprocess.check_output(
    ["git", "diff", "--name-only", "--diff-filter=ACMR", diff_range, "--"],
    text=True,
).splitlines()

blocked_names = {
    ".env",
    "config" + ".toml",
    "credentials" + ".json",
    "secrets" + ".yaml",
}
blocked_suffixes = {".db", ".sqlite", ".sqlite3"}
blocked_files = [
    name
    for name in names
    if Path(name).name in blocked_names
    or Path(name).name.startswith(".env.")
    or Path(name).suffix.lower() in blocked_suffixes
]

raw_diff = subprocess.check_output(
    ["git", "diff", "--no-ext-diff", "--unified=0", diff_range, "--"],
    text=True,
)
added_text = "\n".join(
    line[1:]
    for line in raw_diff.splitlines()
    if line.startswith("+") and not line.startswith("+++")
)

absolute_home = re.compile("/" + r"(?:Users|home)" + "/" + r"[^/\s\"']+/")
private_markers = (
    "nudge-" + "private",
    "DB_" + "backup",
    "百度" + "同步盘",
    "niaite-" + "email",
)
credential_patterns = (
    re.compile("A" + r"KIA[0-9A-Z]{16}"),
    re.compile("sk" + r"-[A-Za-z0-9_-]{20,}"),
    re.compile("gh" + r"[pousr]_[A-Za-z0-9]{30,}"),
    re.compile("xox" + r"[abprs]-[A-Za-z0-9-]{20,}"),
    re.compile("AIza" + r"[A-Za-z0-9_-]{30,}"),
    re.compile(r"-----BEGIN " + r"(?:RSA |EC |OPENSSH )?" + "PRIVATE" + r" KEY-----"),
)

problems = []
if blocked_files:
    problems.append(f"tracked private artifacts: {blocked_files}")
if absolute_home.search(added_text):
    problems.append("absolute user home path found in added diff content")
for marker in private_markers:
    if marker in added_text:
        problems.append(f"private directory marker found: {marker}")
for pattern in credential_patterns:
    if pattern.search(added_text):
        problems.append(f"credential/private-key pattern found: {pattern.pattern}")
if problems:
    raise SystemExit("\n".join(problems))
print(f"privacy scan passed for {diff_range}: {len(names)} changed files")
PY
```

Expected: explicit `BASE..HEAD` whitespace check exits 0; the reproducible scan finds no absolute user path, private-directory marker, common live credential/private-key shape, or newly tracked DB/config/environment artifact. Pattern strings are assembled in pieces so this plan does not match its own scanner.

- [ ] **Step 2: 运行首次完整项目验证**

Run: `scripts/verify.sh`

Expected: all pytest, compile, CLI smoke, docs audit, packaging and public-safe content checks PASS. Do not update completion records if this step fails.

- [ ] **Step 3: 确认测试未创建仓库本地状态库**

Run: `test ! -e .nudge/nudge.db && test ! -e nudge.db`

Expected: exit code 0.

- [ ] **Step 4: 在真实配置上只读运行候选报告**

Use an already exported local `NUDGE_CONFIG`; do not write its private path into repository files. Run the worktree's `bin/nudge`, not the globally installed symlink:

```bash
test -n "${NUDGE_CONFIG:-}"
BACKFILL_DB="$(python3 -c 'import sys; from nudge.config import load_config, resolve_state_dir; print(resolve_state_dir(load_config(sys.argv[1])) / "nudge.db")' "$NUDGE_CONFIG")"
test -f "$BACKFILL_DB"
BACKFILL_DB_MTIME_BEFORE="$(stat -f '%m' "$BACKFILL_DB")"
BACKFILL_REPORT="$(mktemp -t nudge-backfill-report)"
trap 'rm -f "$BACKFILL_REPORT"' EXIT
bin/nudge reminders backfill-lists --config "$NUDGE_CONFIG" --json > "$BACKFILL_REPORT"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], encoding="utf-8")); assert payload["dry_run"] is True; assert payload["backup"] is None; print(json.dumps({key: len(payload.get(key) or []) for key in ("candidates", "missing", "ambiguous", "invalid", "errors")}, ensure_ascii=False))' "$BACKFILL_REPORT"
BACKFILL_DB_MTIME_AFTER="$(stat -f '%m' "$BACKFILL_DB")"
test "$BACKFILL_DB_MTIME_BEFORE" = "$BACKFILL_DB_MTIME_AFTER"
```

Expected: JSON parses successfully; `dry_run=true`; no backup is created; the main database modification time is unchanged. Do not run `--apply` in this task.

- [ ] **Step 5: 回读主 SQLite 和 Apple mutation 边界**

Run:

```bash
python3 - <<'PY'
from pathlib import Path

source = Path("nudge/commands/reminder_list_backfill.py").read_text(encoding="utf-8")
assert "query_all_due_on_date" in source
for forbidden in (
    "complete_reminder",
    "delete_reminder",
    "set_reminder_external_id",
    "create_reminder",
):
    assert forbidden not in source
PY
```

Expected: the static Apple mutation boundary check exits with code 0.

- [ ] **Step 6: 汇报候选，不自动 apply**

Report only counts for `candidates`、`missing`、`ambiguous`、`invalid` and query errors. If candidates exist, ask the user for a separate explicit confirmation before running `--apply`; implementation completion does not authorize changing the real database.

- [ ] **Step 7: 仅在以上验证全部通过后更新最终完成记录**

In `CHANGELOG.md` under `[Unreleased]`, record the new local-only backfill, all-due read mode, confirmation, backup, transaction, successful public verification/read-only Dogfood, and no-Apple-mutation boundary.

Remove only this completed line from `TODO.md`:

```markdown
- [ ] 为升级前 `reminder_list IS NULL` 的旧 reminder action 设计只读候选与确认后 backfill 流程；在此之前，多列表完成同步只允许“明确 Apple 完成记录”作为写回证据，不根据列表中消失推断完成。
```

Keep the non-TTY structured feedback item unchanged. Change the design header to:

```markdown
- 状态：已实现并通过公开运行库完整验证
```

- [ ] **Step 8: 审计收尾文档**

Run: `bin/nudge docs audit --json && git diff --check`

Expected: docs audit has zero errors; the existing historical TODO warning may remain; worktree diff check exits 0.

- [ ] **Step 9: 收尾提交前再次运行完整验证**

Run: `scripts/verify.sh`

Expected: all pytest, compile, CLI smoke, docs audit, packaging and public-safe content checks PASS with the final completion records present.

- [ ] **Step 10: 暂存并提交最终收尾文档**

```bash
git add CHANGELOG.md TODO.md docs/superpowers/specs/2026-07-19-reminder-list-backfill-design.md
git diff --cached --check
git commit -m "docs: close reminder list ownership backfill"
```

- [ ] **Step 11: 用明确基线复核最终分支状态**

```bash
BASE="$(git merge-base HEAD main)"
test -n "$BASE"
export BASE
git diff --check "$BASE"..HEAD
git status --short --branch
git log -8 --oneline
```

Then rerun the complete Python privacy-scan block from Step 1 against this final `BASE..HEAD` range so the closing documentation commit is covered too.

Expected: final explicit `BASE..HEAD` diff check and repeated privacy scan both exit 0; the implementation branch contains the planned commits and no unrelated working-tree changes.
