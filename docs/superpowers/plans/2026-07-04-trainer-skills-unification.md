# Trainer Skills Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `nudge trainer` a friendly compatibility wrapper around the `strength-basics-12w` Skill runtime while preserving legacy trainer data and a deliberate `--legacy-llm` escape hatch.

**Architecture:** `trainer plan` will default to the deterministic Skills runtime (`strength-basics-12w`) by building a Skill context from `[user.fitness]`, previewing or materializing through the same helpers used by `skills start`, and storing a normal `skill_instance`. The previous LLM weekly planner remains available behind `trainer plan --legacy-llm`; `trainer status` prefers active strength Skill instances but falls back to old `weekly_workout` plans. `trainer log` stays compatible for existing workout actions and nudges users toward `nudge log done --metric effort=8` for Skill-backed actions.

**Tech Stack:** Python 3.12+, Click, existing Nudge Skill runtime, existing SQLite state helpers, existing fake Apple backend tests.

---

## Global Constraints

- Do not commit unless the user explicitly authorizes `git commit` in this session.
- Do not delete or rewrite the existing LLM trainer functions in `nudge.brain`; only stop using them by default.
- Do not change the Skill YAML schema or add dependencies.
- All new tests must isolate `nudge.state.STATE_DIR` / `DB_PATH` / `LEGACY_JSON` to `tmp_path`.
- All tests must be public-safe and run offline on Linux using fake Apple backends.
- Keep `trainer log` backwards-compatible with legacy `workout` actions.
- Full verification command: `scripts/verify.sh`.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `nudge/commands/trainer.py` | Modify | Add Skill-backed default planner, profile-to-context mapping, status preference for Skill instances, legacy fallback path. |
| `tests/test_commands_trainer_skills.py` | Create | Offline tests for Skill-backed trainer plan/status/log compatibility using fake Apple backends. |
| `README.md` | Modify | Document `trainer` as the fitness-friendly wrapper over Skills and the legacy flag. |
| `TODO.md` | Modify | Mark trainer/skills unification as completed for the default plan/status path and leave legacy cleanup as follow-up. |

---

### Task 1: Test scaffolding and trainer profile → Skill context mapping

**Files:**
- Modify: `nudge/commands/trainer.py`
- Create: `tests/test_commands_trainer_skills.py`

**Interfaces:**
- New constants in `trainer.py`:
  - `STRENGTH_SKILL_ID = "strength-basics-12w"`
- New helper:
  - `_fitness_to_strength_context(profile: dict, *, start_date: str | None = None) -> dict`
- Mapping rules:
  - Reads `profile["fitness"]` when present; accepts either config root profile or a fitness dict directly.
  - `fitness.current_frequency` or `fitness.strength_frequency` maps to `assessment.current_frequency` if already one of `never`, `one_or_two`, `three_plus`.
  - Numeric frequencies map: `0 -> never`, `1/2 -> one_or_two`, `>=3 -> three_plus`.
  - `fitness.preferred_session_length` or `fitness.session_minutes` maps to `assessment.preferred_session_length` as float.
  - `fitness.preferred_days` and `fitness.preferred_time` map into `profile` for Skill dry-run scheduling.
  - `start_date` argument wins over config start date and is written to `profile.start_date`.
  - Missing values use safe defaults: current_frequency=`one_or_two`, preferred_session_length=`45.0`.

- [ ] **Step 1: Write failing tests for context mapping**

Create `tests/test_commands_trainer_skills.py`:

```python
"""Public-safe tests for trainer compatibility over the Skills runtime."""

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


def _wire_trainer_env(monkeypatch, tmp_path, config):
    state = _isolate_state(monkeypatch, tmp_path)
    import nudge.commands.trainer as trainer_cmd

    calendar = _FakeCalendar()
    backends = AppleBackends(
        calendar=calendar,
        reminders=_FakeReminders(),
        notes=_FakeNotes(),
        clock=_FakeClock(),
    )
    monkeypatch.setattr(trainer_cmd, "load_config", lambda path=None: config)
    monkeypatch.setattr(trainer_cmd, "configure_state", lambda cfg=None: tmp_path)
    monkeypatch.setattr(trainer_cmd, "resolve_apple_backends", lambda cfg: backends)
    return state, trainer_cmd, calendar


def test_fitness_to_strength_context_maps_frequency_and_preferences():
    from nudge.commands.trainer import _fitness_to_strength_context

    context = _fitness_to_strength_context(
        {
            "fitness": {
                "strength_frequency": 0,
                "preferred_session_length": 35,
                "preferred_days": ["Tuesday", "Thursday"],
                "preferred_time": "18:30",
            }
        },
        start_date="2026-07-06",
    )

    assert context["assessment"] == {
        "current_frequency": "never",
        "preferred_session_length": 35.0,
    }
    assert context["profile"] == {
        "start_date": "2026-07-06",
        "preferred_days": ["Tuesday", "Thursday"],
        "preferred_time": "18:30",
    }


def test_fitness_to_strength_context_defaults_when_sparse():
    from nudge.commands.trainer import _fitness_to_strength_context

    context = _fitness_to_strength_context({"fitness": {}}, start_date="2026-07-06")

    assert context["assessment"]["current_frequency"] == "one_or_two"
    assert context["assessment"]["preferred_session_length"] == 45.0
    assert context["profile"]["start_date"] == "2026-07-06"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest -q tests/test_commands_trainer_skills.py
```

Expected: fails with `ImportError` or `AttributeError` because `_fitness_to_strength_context` does not exist.

- [ ] **Step 3: Implement the mapping helper**

In `nudge/commands/trainer.py`, add imports:

```python
from datetime import date, datetime, timedelta

from nudge.apple.adapters import resolve_apple_backends
from nudge.commands.skills import _materialize_actions
from nudge.config import get_family_aliases, get_defaults
from nudge.skills.dryrun import dry_run_skill
from nudge.skills.runtime import (
    create_skill_instance,
    list_skill_instances,
    record_materialized_week,
    skill_weeks_total,
)
from nudge.skills.schema import load_skill_source, validate_skill
from nudge.state import configure_state
```

Keep existing imports until Task 2 moves the legacy implementation behind a helper.

Add below `trainer_command()`:

```python
STRENGTH_SKILL_ID = "strength-basics-12w"


def _fitness_to_strength_context(profile: dict, *, start_date: str | None = None) -> dict:
    """Build the strength Skill context from [user.fitness] config."""
    fitness = profile.get("fitness") if "fitness" in profile else profile
    fitness = fitness or {}

    raw_frequency = fitness.get("current_frequency", fitness.get("strength_frequency"))
    if raw_frequency in {"never", "one_or_two", "three_plus"}:
        frequency = str(raw_frequency)
    else:
        try:
            count = int(raw_frequency)
        except (TypeError, ValueError):
            count = 2
        if count <= 0:
            frequency = "never"
        elif count <= 2:
            frequency = "one_or_two"
        else:
            frequency = "three_plus"

    raw_minutes = fitness.get("preferred_session_length", fitness.get("session_minutes", 45))
    try:
        minutes = float(raw_minutes)
    except (TypeError, ValueError):
        minutes = 45.0

    skill_profile = {}
    chosen_start = start_date or fitness.get("start_date")
    if chosen_start:
        skill_profile["start_date"] = str(chosen_start)
    if fitness.get("preferred_days"):
        skill_profile["preferred_days"] = list(fitness["preferred_days"])
    if fitness.get("preferred_time"):
        skill_profile["preferred_time"] = str(fitness["preferred_time"])

    return {
        "assessment": {
            "current_frequency": frequency,
            "preferred_session_length": minutes,
        },
        "profile": skill_profile,
    }
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
python -m pytest -q tests/test_commands_trainer_skills.py
```

Expected: 2 passed.

---

### Task 2: Make `trainer plan` default to Skill runtime, keep `--legacy-llm`

**Files:**
- Modify: `nudge/commands/trainer.py`
- Modify: `tests/test_commands_trainer_skills.py`

**Interfaces:**
- `trainer plan` default path uses `strength-basics-12w` Skill.
- New options:
  - `--weeks 1..12`, default `1`.
  - `--start-date YYYY-MM-DD`, default today or fitness config.
  - `--yes/-y` to skip confirmation.
  - `--json` for machine output.
  - `--legacy-llm` to run previous LLM weekly planner.
- Existing `--dry-run` and `--config` remain.
- JSON output must be a versioned payload from `nudge.json_contract.versioned_payload`.
- `--dry-run` writes nothing to Apple or SQLite.
- Real Skill-backed write creates a `skill_instance`, materializes first week, and advances cursor only if all actions succeed.

- [ ] **Step 1: Preserve the old trainer implementation as a helper**

In `nudge/commands/trainer.py`, rename the current `plan(dry_run, config_path)` body into:

```python
def _legacy_llm_plan(dry_run: bool, config_path: str | None) -> None:
    """Legacy LLM weekly workout planner kept as an explicit escape hatch."""
    ...existing plan body unchanged...
```

Then replace the `plan` click signature with the new signature in Step 4.

- [ ] **Step 2: Write failing tests for Skill-backed plan dry-run and apply**

Append to `tests/test_commands_trainer_skills.py`:

```python
def _fitness_config():
    return {
        "user": {
            "fitness": {
                "strength_frequency": 0,
                "preferred_session_length": 35,
                "preferred_days": ["Monday", "Wednesday", "Friday"],
                "preferred_time": "07:00",
            }
        }
    }


def test_trainer_plan_dry_run_uses_strength_skill_without_writes(monkeypatch, tmp_path):
    state, trainer_cmd, calendar = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--dry-run", "--start-date", "2026-07-06", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["skill_id"] == "strength-basics-12w"
    assert len(payload["actions"]) == 3
    assert calendar.created == []
    assert state.get_actions() == []


def test_trainer_plan_creates_strength_skill_instance(monkeypatch, tmp_path):
    state, trainer_cmd, calendar = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())

    runner = CliRunner()
    result = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--start-date", "2026-07-06", "--yes", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["skill_id"] == "strength-basics-12w"
    assert payload["legacy"] is False
    assert len(payload["created"]) == 3
    assert len(calendar.created) == 3

    from nudge.skills.runtime import list_skill_instances

    instance = list_skill_instances()[0]
    assert instance["skill_id"] == "strength-basics-12w"
    assert instance["materialized_through_week"] == 1
    assert instance["context"]["assessment"]["current_frequency"] == "never"

    actions = state.get_actions(plan_id=instance["plan_id"])
    assert len(actions) == 3
    assert all(a["external_id"] for a in actions)
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
python -m pytest -q tests/test_commands_trainer_skills.py
```

Expected: new tests fail because `trainer plan` has no `--weeks`, `--start-date`, `--yes`, `--json`, and still uses legacy LLM.

- [ ] **Step 4: Implement Skill-backed `trainer plan`**

Add import:

```python
import json

from nudge.json_contract import versioned_payload
```

Replace the `plan` command with:

```python
@trainer_command.command("plan")
@click.option("--dry-run", "-n", is_flag=True, help="Preview without creating events")
@click.option("--config", "-c", "config_path", default=None)
@click.option("--weeks", default=1, type=click.IntRange(1, 12), help="首次落地的周数")
@click.option("--start-date", "start_date_value", default=None, help="开始日期 YYYY-MM-DD，默认今天")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="跳过确认")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
@click.option("--legacy-llm", is_flag=True, help="使用旧版 LLM 周训练计划生成器")
def plan(dry_run, config_path, weeks, start_date_value, assume_yes, json_output, legacy_llm):
    """Create a workout plan. Defaults to the strength Skill runtime."""
    if legacy_llm:
        if json_output:
            raise click.ClickException("trainer plan --legacy-llm 不支持 --json")
        _legacy_llm_plan(dry_run, config_path)
        return

    config = load_config(config_path)
    configure_state(config)
    profile = get_user_profile(config)
    if not profile.get("fitness"):
        raise click.ClickException(
            "请先在 config.toml 中填写 [user.fitness] 配置（健身水平、目标、器械等）"
        )

    start_date = start_date_value or date.today().isoformat()
    date.fromisoformat(start_date)
    context = _fitness_to_strength_context(profile, start_date=start_date)
    skill = validate_skill(load_skill_source(STRENGTH_SKILL_ID))
    result = dry_run_skill(skill, context, weeks=weeks)

    if dry_run:
        payload = {
            "ok": True,
            "legacy": False,
            "dry_run": True,
            "skill_id": STRENGTH_SKILL_ID,
            "actions": result.actions,
            "personalization_applied": result.personalization_applied,
        }
        if json_output:
            click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        else:
            click.echo("DRY-RUN trainer plan（Skill runtime）：")
            for action in result.actions:
                click.echo(f"  - W{action['week']} {action['start']} {action['summary']}")
        return

    if not assume_yes and not json_output:
        click.confirm(f"写入 {len(result.actions)} 个训练到 Apple Calendar？", default=True, abort=True)

    plan_id = create_skill_instance(
        result.skill,
        context,
        start_date=start_date,
        weeks_total=skill_weeks_total(result.skill),
        materialized_through_week=0,
        personalization_applied=result.personalization_applied,
    )
    created, failed = _materialize_actions(result.actions, plan_id=plan_id, config=config, quiet=json_output)
    if created and not failed:
        record_materialized_week(plan_id, weeks)
    payload = {
        "ok": not failed,
        "legacy": False,
        "skill_id": STRENGTH_SKILL_ID,
        "plan_id": plan_id,
        "created": created,
        "failed": failed,
        "personalization_applied": result.personalization_applied,
    }
    if created and failed:
        payload["retry_warning"] = (
            "部分训练已写入 Apple 并登记本地 action；不要整周重试，请只处理 failed 项或人工清理后重试。"
        )
    if json_output:
        click.echo(json.dumps(versioned_payload(payload), ensure_ascii=False))
        if failed:
            raise click.exceptions.Exit(1)
        return
    click.echo(f"PASS trainer plan 已通过 Skill runtime 创建: {plan_id}（写入 {len(created)} 个，失败 {len(failed)} 个）")
    if created and failed:
        click.echo("WARN 部分训练已写入；不要整周重试，请只处理 failed 项或人工清理后重试。", err=True)
    if failed:
        raise click.exceptions.Exit(1)
```

- [ ] **Step 5: Run tests to verify pass**

Run:

```bash
python -m pytest -q tests/test_commands_trainer_skills.py
```

Expected: 4 passed.

- [ ] **Step 6: Run related regression tests**

Run:

```bash
python -m pytest -q tests/test_commands_skills_runtime.py tests/test_commands_trainer_skills.py
```

Expected: all tests pass.

---

### Task 3: Make `trainer status` prefer strength Skill instances, fallback to legacy plans

**Files:**
- Modify: `nudge/commands/trainer.py`
- Modify: `tests/test_commands_trainer_skills.py`

**Interfaces:**
- `trainer status` output order:
  1. If active `strength-basics-12w` Skill instances exist, show the newest/first active Skill instance and its action progress.
  2. If none exist, keep the existing legacy `weekly_workout` status behavior.
- No JSON mode for `trainer status` in this plan.

- [ ] **Step 1: Write failing test for Skill-first status**

Append:

```python
def test_trainer_status_prefers_strength_skill_instance(monkeypatch, tmp_path):
    state, trainer_cmd, _ = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())
    runner = CliRunner()
    plan = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--start-date", "2026-07-06", "--yes", "--json"],
    )
    assert plan.exit_code == 0, plan.output

    result = runner.invoke(trainer_cmd.trainer_command, ["status"])

    assert result.exit_code == 0, result.output
    assert "Skill 训练计划" in result.output
    assert "strength-basics-12w" in result.output
    assert "W1/12" in result.output
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest -q tests/test_commands_trainer_skills.py::test_trainer_status_prefers_strength_skill_instance
```

Expected: fails because legacy status only checks `goal == "weekly_workout"`.

- [ ] **Step 3: Extract legacy status body into helper**

In `nudge/commands/trainer.py`, move the existing `status()` body into:

```python
def _legacy_workout_status() -> None:
    """Show status for legacy weekly_workout plans."""
    ...existing status body unchanged...
```

- [ ] **Step 4: Add Skill status helper and replace command body**

Add:

```python
def _show_strength_skill_status() -> bool:
    """Show active strength Skill progress. Returns True when one was shown."""
    instances = [
        item for item in list_skill_instances()
        if item.get("skill_id") == STRENGTH_SKILL_ID
    ]
    if not instances:
        return False
    instance = instances[0]
    plan_id = instance["plan_id"]
    actions = get_actions(plan_id=plan_id)
    total = len(actions)
    done = sum(1 for a in actions if a.get("status") == "done")
    skipped = sum(1 for a in actions if a.get("status") == "skipped")
    pending = total - done - skipped
    weeks_total = instance.get("weeks_total") or "?"
    click.echo(f"Skill 训练计划 · {STRENGTH_SKILL_ID}\n")
    click.echo(f"  实例: {plan_id}")
    click.echo(f"  进度: W{instance.get('materialized_through_week')}/{weeks_total}")
    click.echo(f"  总计: {total} 次训练")
    click.echo(f"  ✓ 完成: {done}")
    click.echo(f"  ✗ 跳过: {skipped}")
    click.echo(f"  ○ 待完成: {pending}")
    click.echo("\n  下一步: nudge log done --metric effort=8；nudge skills adapt " + plan_id)
    return True
```

Replace `status()` with:

```python
@trainer_command.command("status")
def status():
    """Show current workout plan progress."""
    if _show_strength_skill_status():
        return
    _legacy_workout_status()
```

- [ ] **Step 5: Run tests**

Run:

```bash
python -m pytest -q tests/test_commands_trainer_skills.py
```

Expected: all trainer Skill tests pass.

---

### Task 4: Keep `trainer log` compatible and add Skill-backed guidance

**Files:**
- Modify: `nudge/commands/trainer.py`
- Modify: `tests/test_commands_trainer_skills.py`

**Interfaces:**
- If legacy `workout` actions exist, `trainer log` keeps existing behavior.
- If no legacy workout actions exist but an active strength Skill instance exists, `trainer log` does not parse via LLM; it prints guidance to use the generic logger:
  - `nudge log done --metric effort=8`
  - `nudge skills status`
  - `nudge skills adapt <plan-id>`

- [ ] **Step 1: Write failing test for Skill-backed guidance**

Append:

```python
def test_trainer_log_guides_for_skill_backed_actions(monkeypatch, tmp_path):
    _state, trainer_cmd, _ = _wire_trainer_env(monkeypatch, tmp_path, _fitness_config())
    runner = CliRunner()
    plan = runner.invoke(
        trainer_cmd.trainer_command,
        ["plan", "--start-date", "2026-07-06", "--yes", "--json"],
    )
    assert plan.exit_code == 0, plan.output

    result = runner.invoke(trainer_cmd.trainer_command, ["log", "完成了，强度8"])

    assert result.exit_code == 0, result.output
    assert "nudge log done --metric effort=8" in result.output
    assert "nudge skills adapt" in result.output
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest -q tests/test_commands_trainer_skills.py::test_trainer_log_guides_for_skill_backed_actions
```

Expected: fails because current command says no pending training and references old `nudge.py trainer plan`.

- [ ] **Step 3: Add guidance branch**

In `log(message, config_path)`, after `if not workout_actions:` and before returning, check active strength Skill instances:

```python
    if not workout_actions:
        strength_instances = [
            item for item in list_skill_instances()
            if item.get("skill_id") == STRENGTH_SKILL_ID
        ]
        if strength_instances:
            plan_id = strength_instances[0]["plan_id"]
            click.echo("当前训练计划由 Skills runtime 管理。")
            click.echo("请用通用打卡记录本次训练，例如：")
            click.echo("  nudge log done --metric effort=8")
            click.echo(f"查看进度: nudge skills status；下周调整: nudge skills adapt {plan_id}")
            return
        click.echo("没有待完成的训练。先用 `nudge trainer plan` 创建计划。")
        return
```

Keep the rest of legacy workout parsing unchanged.

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest -q tests/test_commands_trainer_skills.py
```

Expected: all trainer Skill tests pass.

---

### Task 5: Documentation and TODO cleanup

**Files:**
- Modify: `README.md`
- Modify: `TODO.md`

**Interfaces:**
- README describes `trainer plan` as the fitness-friendly wrapper over `skills start strength-basics-12w`.
- README mentions `--legacy-llm` as escape hatch.
- TODO marks `trainer` / `skills` default-path unification complete and leaves legacy LLM removal as follow-up.

- [ ] **Step 1: Update README**

In `README.md` after the `Skills Lifecycle` section, add:

```markdown
## Trainer Compatibility

`nudge trainer plan` is the fitness-focused entry point for the built-in `strength-basics-12w` Skill. It reads `[user.fitness]`, creates a local Skill instance, and writes the first week through the same Apple-safe runtime used by `nudge skills start`.

```bash
nudge trainer plan --dry-run
nudge trainer plan --yes
nudge log done --metric effort=8
nudge trainer status
```

The previous LLM-generated weekly workout planner is still available as an explicit compatibility path: `nudge trainer plan --legacy-llm`.
```

- [ ] **Step 2: Update TODO**

In the `trainer 与 skills 双轨计划机制重叠` item, append:

```markdown
  - 状态:2026-07-04 已完成默认路径统一:`trainer plan/status` 默认走 `strength-basics-12w` Skill runtime,旧 LLM 周计划保留为 `trainer plan --legacy-llm`;剩余:评估是否删除旧 LLM planner 与 `trainer log` 自然语言解析。
```

- [ ] **Step 3: Run docs-sensitive verification**

Run:

```bash
scripts/verify.sh
```

Expected: public verification passes.

---

### Task 6: Final verification and review

**Files:**
- No planned code changes unless verification or review finds issues.

- [ ] **Step 1: Run full verification**

Run:

```bash
scripts/verify.sh
```

Expected:

```text
Nudge public verification passed
```

- [ ] **Step 2: Run trainer-specific smoke tests**

Run:

```bash
python -m pytest -q tests/test_commands_trainer_skills.py tests/test_commands_skills_runtime.py tests/test_commands_log_metric.py
```

Expected: all selected tests pass.

- [ ] **Step 3: Request final code review**

Dispatch a reviewer with this scope:

```text
Review trainer/skills unification. Confirm trainer plan defaults to strength Skill runtime, legacy LLM path remains explicit, status prefers Skill instances with legacy fallback, trainer log remains compatible, JSON/dry-run behavior is stable, and tests isolate state.
```

Expected: reviewer returns `APPROVED` or only non-blocking Minor issues.

- [ ] **Step 4: Report completion without committing**

Because global rules prohibit commit without explicit user authorization, do not commit. Final response must include:

- Files changed.
- Verification commands and exact pass/fail result.
- Unverified items: real macOS Apple writes and real terminal UX for non-test interactive flows.
- Remaining TODO: optional removal of legacy LLM planner and deeper `trainer log` unification.
